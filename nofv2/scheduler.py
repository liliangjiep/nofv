import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import List
from config import (
    monitor_symbols, MAX_POSITIONS, SCAN_INTERVAL,
    PRICE_MONITOR_INTERVAL, TRAILING_STOP_ENABLED
)
from indicators import calculate_signal_single
from deepseek_batch_pusher import push_batch_to_deepseek
from kline_fetcher import fetch_all
from position_cache import position_records
from account_positions import get_account_status, account_snapshot
from trader import execute_trade_async
from profit_tracker import update_profit_curve
from database import redis_client
from logger import log_info, log_error, log_trade, log_debug
from trade_tracker import update_trade_stats, get_active_trades, get_active_trade, check_and_record_auto_closed, check_trailing_stop, sync_positions_to_active_trades, KEY_ACTIVE_TRADES
from trader import check_and_cancel_expired_limit_orders, sync_limit_order_records
import json

# ========= 新仓保护配置 =========
NEW_POSITION_PROTECT_SECONDS = 300  # 新仓保护时间（秒），5分钟内禁止平仓（从15分钟缩短）
TRAILING_STOP_BYPASS_PROFIT_PCT = 5.0  # 盈利超过此百分比时，动态止盈可绕过新仓保护



# ========= 工具函数 =========
_RUN_LOCK = asyncio.Lock()
def get_pos_symbols_from_account_snapshot() -> List[str]:
    syms = []
    for p in (account_snapshot.get("positions") or []):
        try:
            size = float(p.get("size", 0))
            if size != 0:
                sym = p.get("symbol")
                if sym:
                    syms.append(sym)
        except Exception:
            continue
    return list(dict.fromkeys(syms))
 
def is_scan_boundary(now: datetime, tolerance: int = 2) -> bool:
    return now.minute % SCAN_INTERVAL == 0 and now.second <= tolerance

def seconds_to_next_scan_close(now: datetime) -> float:
    """返回距离下一个扫描整点（K线收盘）还有多少秒"""
    minute = (now.minute // SCAN_INTERVAL + 1) * SCAN_INTERVAL
    next_run = now.replace(second=0, microsecond=0)
    if minute >= 60:
        next_run = next_run.replace(minute=0) + timedelta(hours=1)
    else:
        next_run = next_run.replace(minute=minute)
    return max(1.0, (next_run - now).total_seconds())

def is_trade_action(action: str, mode: str) -> bool:
    """
    mode = "manage"：仅允许风控动作（禁止开新仓）
    mode = "scan"：允许开仓/平仓/更新
    """
    if mode == "manage":
        return action in {
            "update_stop_loss",
            "update_take_profit",
            "close_long",
            "close_short",
            "reverse",
            "increase_position",
            "decrease_position",
        }
    # scan
    return action in {
        "open_long",
        "open_short",
        "open_long_market",
        "open_short_market",
        "open_long_limit",
        "open_short_limit",
        "close_long",
        "close_short",
        "reverse",
        "increase_position",
        "decrease_position",
        "update_stop_loss",
        "update_take_profit",
    }

def valid_action(action: str) -> bool:
    """动作闭集：用于保留/记录信号（包含 hold/wait），但不一定下单"""
    return action in {
        "open_long", "open_short",
        "open_long_market", "open_short_market",
        "open_long_limit", "open_short_limit",
        "close_long", "close_short",
        "reverse",
        "increase_position", "decrease_position",
        "update_stop_loss", "update_take_profit",
        "hold", "wait",
    }


def normalize_action(sig: dict, pos_symbols_map: dict = None) -> dict:
    """
    标准化动作名：
    - 把 AI 可能返回的非标准动作名转换为标准动作名
    - 根据实际持仓方向判断 close 动作
    
    pos_symbols_map: {symbol: "LONG" | "SHORT"} 当前持仓方向映射
    """
    action = sig.get("action", "")
    symbol = sig.get("symbol", "")
    
    # 非标准动作名转换
    if action.lower() in ("set_tp", "set_take_profit", "add_tp", "modify_tp"):
        sig = sig.copy()
        sig["action"] = "update_take_profit"
    elif action.lower() in ("set_sl", "set_stop_loss", "add_sl", "modify_sl"):
        sig = sig.copy()
        sig["action"] = "update_stop_loss"
    elif action.lower() in ("modify_tp_sl", "update_tp_sl", "set_tp_sl"):
        # 同时修改止盈止损，优先处理止损
        sig = sig.copy()
        sig["action"] = "update_stop_loss"
    elif action == "close":
        # AI 返回 close，根据实际持仓方向判断
        sig = sig.copy()
        
        # 优先使用实际持仓方向
        if pos_symbols_map and symbol in pos_symbols_map:
            actual_side = pos_symbols_map[symbol]
            sig["action"] = "close_long" if actual_side == "LONG" else "close_short"
        else:
            # 备用：从信号中获取方向信息
            direction = sig.get("direction", "").lower()
            if direction == "short":
                sig["action"] = "close_short"
            elif direction == "long":
                sig["action"] = "close_long"
            else:
                # 无法判断方向，保留原始 action，让 trader 处理
                pass
    
    return sig


# ========= 新仓保护逻辑 =========
# 记录每个币种的开仓时间
_position_open_times = {}

def record_position_open(symbol: str):
    """记录开仓时间"""
    _position_open_times[symbol] = time.time()

def clear_position_record(symbol: str):
    """清除仓位记录（平仓后调用）"""
    _position_open_times.pop(symbol, None)

def is_position_protected(symbol: str) -> bool:
    """检查仓位是否在保护期内"""
    open_time = _position_open_times.get(symbol)
    if open_time is None:
        return False
    elapsed = time.time() - open_time
    return elapsed < NEW_POSITION_PROTECT_SECONDS

def get_position_age_seconds(symbol: str) -> float:
    """获取仓位持有时间（秒）"""
    open_time = _position_open_times.get(symbol)
    if open_time is None:
        return float('inf')  # 没有记录，视为老仓位
    return time.time() - open_time

# ========= 核心：单轮执行 =========
async def run_once(mode: str = "scan"):
    """
    mode:
      - "manage": 只管理持仓币（1m）
      - "scan": 扫描主流+持仓（15m）
    """
    async with _RUN_LOCK:  # ✅ 防止 manage/scan 两个 loop 互相踩 monitor_symbols
        print(f"🚀 执行一轮交易调度 | mode={mode}")

        # 刷新账户/持仓与收益曲线
        get_account_status()
        update_profit_curve()
        
        # ========= 同步持仓到活跃交易（处理限价单成交） =========
        current_positions = account_snapshot.get("positions") or []
        new_trades = sync_positions_to_active_trades(current_positions)
        for trade in new_trades:
            log_info(f"📝 限价单成交 | {trade['symbol']} | {trade['side']} | entry={trade['entry_price']}")
        
        # ========= 为限价单成交的仓位设置默认 TP/SL =========
        for p in current_positions:
            size = float(p.get("size", 0))
            if size == 0:
                continue
            symbol = p.get("symbol")
            side = "LONG" if size > 0 else "SHORT"
            
            # 检查是否需要设置 TP/SL
            trade_data = get_active_trade(symbol, side)
            if trade_data and trade_data.get("needs_tp_sl_setup"):
                entry_price = float(p.get("entry", 0))
                if entry_price > 0:
                    # 设置默认 TP/SL（基于入场价的百分比）
                    if side == "LONG":
                        default_sl = entry_price * 0.97  # 3% 止损
                        default_tp = entry_price * 1.06  # 6% 止盈
                    else:  # SHORT
                        default_sl = entry_price * 1.03  # 3% 止损
                        default_tp = entry_price * 0.94  # 6% 止盈
                    
                    try:
                        from trader import _update_tp_sl_async
                        await _update_tp_sl_async(symbol, side, sl=default_sl, tp=default_tp, current_price=entry_price)
                        log_info(f"🎯 限价单成交后设置 TP/SL | {symbol} | {side} | SL={default_sl:.4f} TP={default_tp:.4f}")
                        
                        # 清除标记
                        trade_data.pop("needs_tp_sl_setup", None)
                        redis_client.hset(KEY_ACTIVE_TRADES, f"{symbol}:{side}", json.dumps(trade_data))
                    except Exception as e:
                        log_error(f"⚠️ 设置限价单 TP/SL 失败 | {symbol} | {e}")
        
        # ========= 检查止损/止盈自动平仓 =========
        auto_closed = check_and_record_auto_closed(current_positions)
        for closed in auto_closed:
            log_info(f"🔔 AUTO_CLOSE | {closed['symbol']} | {closed['side']} | 止损/止盈触发 | 净收益: {closed['net_pnl']:.2f} USDT")
        
        # ========= 检查并撤销超时限价单 =========
        try:
            cancelled_orders = await check_and_cancel_expired_limit_orders()
            if cancelled_orders:
                log_info(f"⏰ 本轮撤销 {len(cancelled_orders)} 个超时限价单")
            # 同步限价单记录（清理已成交的）
            await sync_limit_order_records()
        except Exception as e:
            log_error(f"⚠️ 限价单检查异常: {e}")
        
        # ========= 更新活跃交易的峰值收益和最大回撤 =========
        trailing_stop_signals = []  # 收集动态回撤止盈信号
        for p in current_positions:
            try:
                size = float(p.get("size", 0))
                if size != 0:
                    symbol = p.get("symbol")
                    side = "LONG" if size > 0 else "SHORT"
                    mark_price = float(p.get("mark_price", 0))
                    entry_price = float(p.get("entry", 0))
                    if symbol and mark_price > 0:
                        update_trade_stats(symbol, side, mark_price)
                        
                        # 检查动态回撤止盈
                        if entry_price > 0:
                            ts_result = check_trailing_stop(symbol, side, mark_price, entry_price)
                            if ts_result.get("triggered"):
                                close_action = "close_long" if side == "LONG" else "close_short"
                                trailing_stop_signals.append({
                                    "symbol": symbol,
                                    "action": close_action
                                    # reason 只用于日志，不传给 execute_trade_async
                                })
                                log_info(f"🎯 动态回撤止盈触发 | {symbol} | {side} | {ts_result.get('reason')}")
            except Exception:
                continue
        # print("DEBUG position_records len =", len(position_records or []))
        # print("DEBUG account_snapshot positions len =", len((account_snapshot.get("positions") or [])))
        pos_symbols = get_pos_symbols_from_account_snapshot()
        ai500_raw = redis_client.lrange("AI500_SYMBOLS", 0, -1)
        # Redis 返回 bytes，需要解码
        ai500_symbols = [s.decode() if isinstance(s, bytes) else s for s in ai500_raw]
        has_position = bool(pos_symbols)
        
        # manage 模式下如果没有持仓，直接跳过
        if mode == "manage" and not has_position:
            print("📊 manage 模式无持仓，跳过本轮")
            return
        
        # 调试日志
        print(f"📊 持仓币种: {pos_symbols}")
        print(f"📊 AI500币种: {ai500_symbols}")

        # 本轮监控池（跟 aibtc 一致：每次都扫描所有币种）
        # 合并：固定币种 + 持仓币种 + AI500
        from config import monitor_symbols as base_symbols
        all_symbols = list(base_symbols) + pos_symbols + ai500_symbols
        monitor_symbols[:] = list(dict.fromkeys(all_symbols))
        print(f"📊 本轮监控币种: {monitor_symbols}")

        # ✅ 关键：保存本轮 symbols 的本地副本（后面清理用它，避免并发被改）
        symbols_this_round = list(monitor_symbols)

        try:
            # 拉K线与算指标
            fetch_all()
            for sym in symbols_this_round:
                calculate_signal_single(sym)

            # ========= 纯 AI 决策模式 =========
            start_ai = time.perf_counter()
            ai_res = await push_batch_to_deepseek()
            end_ai = time.perf_counter()
            print(f"⏱ AI返回耗时: {round(end_ai - start_ai, 3)} 秒")

            if not ai_res or not isinstance(ai_res, list):
                print("⚠ AI 未返回有效信号，不推送，不下单")
                return

            # 构建持仓方向映射，用于 close 动作判断
            pos_symbols_map = {}
            for p in current_positions:
                size = float(p.get("size", 0))
                if size != 0:
                    pos_symbols_map[p.get("symbol")] = "LONG" if size > 0 else "SHORT"

            # 标准化动作名
            ai_res = [normalize_action(sig, pos_symbols_map) for sig in ai_res if sig and isinstance(sig, dict)]

            # 过滤：只保留动作闭集内信号（含 wait/hold），排除 None
            signals = [sig for sig in ai_res if sig and isinstance(sig, dict) and valid_action(sig.get("action", ""))]

            # manage 模式：只允许持仓币信号（避免模型对非持仓币发号施令）
            if mode == "manage":
                signals = [s for s in signals if s.get("symbol") in pos_symbols]

            # 只对“需要交易/改单”的动作执行；wait/hold 不执行但可以留作日志
            exec_list = [s for s in signals if is_trade_action(s.get("action", ""), mode)]

            # 检查最大持仓数量限制
            current_pos_count = len(pos_symbols)
            if current_pos_count >= MAX_POSITIONS:
                open_actions = ("open_long", "open_short", "open_long_market", "open_short_market",
                                "open_long_limit", "open_short_limit")
                filtered = [s for s in exec_list if s.get("action") not in open_actions]
                if len(filtered) < len(exec_list):
                    log_info(f"⚠️ 已达最大持仓数 {MAX_POSITIONS}，跳过 {len(exec_list) - len(filtered)} 个开仓信号")
                exec_list = filtered

            # ========= 新仓保护过滤 =========
            protected_exec_list = []
            for sig in exec_list:
                action = sig.get("action", "")
                symbol = sig.get("symbol", "")
                
                # 开仓动作：记录开仓时间
                if action in ("open_long", "open_short", "open_long_market", "open_short_market", 
                              "open_long_limit", "open_short_limit"):
                    record_position_open(symbol)
                    protected_exec_list.append(sig)
                    continue
                
                # 平仓/反转动作：检查是否在保护期
                if action in ("close_long", "close_short", "reverse"):
                    if is_position_protected(symbol):
                        age = get_position_age_seconds(symbol)
                        remaining = NEW_POSITION_PROTECT_SECONDS - age
                        log_info(f"🛡️ 新仓保护 | {symbol} | 跳过 {action} | 剩余保护 {int(remaining)}秒")
                        continue
                    else:
                        # 平仓成功，清除记录
                        clear_position_record(symbol)
                
                protected_exec_list.append(sig)
            
            exec_list = protected_exec_list

            # ========= 加入动态回撤止盈信号 =========
            if trailing_stop_signals:
                for ts_sig in trailing_stop_signals:
                    symbol = ts_sig.get("symbol")
                    # 检查是否在保护期（但高盈利时可绕过）
                    if is_position_protected(symbol):
                        # 获取当前盈利百分比，判断是否可以绕过保护
                        can_bypass = False
                        for p in current_positions:
                            if p.get("symbol") == symbol:
                                entry = float(p.get("entry", 0))
                                mark = float(p.get("mark_price", 0))
                                size = float(p.get("size", 0))
                                if entry > 0 and mark > 0:
                                    if size > 0:  # LONG
                                        profit_pct = (mark - entry) / entry * 100
                                    else:  # SHORT
                                        profit_pct = (entry - mark) / entry * 100
                                    if profit_pct >= TRAILING_STOP_BYPASS_PROFIT_PCT:
                                        can_bypass = True
                                        log_info(f"🎯 高盈利绕过保护 | {symbol} | 盈利 {profit_pct:.2f}% >= {TRAILING_STOP_BYPASS_PROFIT_PCT}%")
                                break
                        
                        if not can_bypass:
                            age = get_position_age_seconds(symbol)
                            remaining = NEW_POSITION_PROTECT_SECONDS - age
                            log_info(f"🛡️ 新仓保护 | {symbol} | 跳过动态止盈 | 剩余保护 {int(remaining)}秒")
                            continue
                    
                    # 检查是否已有该币种的平仓信号（避免重复）
                    existing = [s for s in exec_list if s.get("symbol") == symbol]
                    if not existing:
                        exec_list.append(ts_sig)
                        clear_position_record(symbol)
                        log_info(f"🎯 加入动态止盈信号 | {symbol} | {ts_sig.get('action')}")

            # 并发下单
            tasks = []
            for sig in exec_list:
                log_trade(sig.get("symbol"), sig.get("action"), f"AI信号 | SL={sig.get('stop_loss')} TP={sig.get('take_profit')} size={sig.get('position_size') or sig.get('order_value')}")
                tasks.append(asyncio.create_task(
                    execute_trade_async(
                        symbol=sig.get("symbol"),
                        action=sig.get("action"),
                        stop_loss=sig.get("stop_loss"),
                        take_profit=sig.get("take_profit"),
                        position_size=(
                            sig.get("position_size")
                            or sig.get("order_value")
                            or sig.get("amount")
                        ),
                        quantity=sig.get("quantity"),
                        order_type=sig.get("order_type"),  # 新增：market 或 limit
                        entry=sig.get("entry")             # 新增：限价单入场价
                    )
                ))

            if tasks:
                start_exec = time.perf_counter()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                end_exec = time.perf_counter()
                
                # 检查并记录异常
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        sig = exec_list[i] if i < len(exec_list) else {}
                        log_error(f"❌ 下单异常 | {sig.get('symbol')} | {sig.get('action')} | {result}")
                
                log_info(f"⏱ 并行下单耗时: {round(end_exec - start_exec, 3)} 秒")
            else:
                log_debug("ℹ 本轮无需要执行的下单动作（可能是 wait/hold 或无信号）")

            # 3️⃣ 推送 TG（暂时禁用）
            # if exec_list:
            #     log_info(f"📨 待推送 TG: {len(exec_list)} 条信号")

        finally:
            # 🧹 清理 Redis 旧 K 线：只在 scan 模式做，避免 manage 每分钟 keys 扫描
            # 改进：保留持仓币种的数据，即使不在本轮扫描中
            if mode == "scan":
                try:
                    # 合并本轮扫描币种 + 当前持仓币种，都需要保留
                    valid = set(symbols_this_round)
                    valid.update(pos_symbols)  # 确保持仓币种数据不被删除
                    
                    for key in redis_client.keys("historical_data:*"):
                        k = key if isinstance(key, str) else key.decode()
                        parts = k.split(":")
                        if len(parts) == 3:
                            _, symbol, _ = parts
                            if symbol not in valid:
                                redis_client.delete(key)
                except Exception as e:
                    print(f"⚠️ Redis清理异常: {e}")

        print("🎯 本轮调度完成\n")

# ========= 调度 Loop =========
async def scan_loop():
    """对齐扫描间隔收盘：扫描全市场机会（启动时先等到下一个整点）"""
    # ✅ 启动时先对齐到下一个扫描整点，避免立刻全量扫
    now = datetime.now(timezone.utc)
    first_sleep = seconds_to_next_scan_close(now)
    print(f"⏳ 首次全量扫描将在 {int(first_sleep)} 秒后（下一个{SCAN_INTERVAL}m整点）")
    await asyncio.sleep(first_sleep)

    while True:
        try:
            await run_once(mode="scan")
        except Exception as e:
            import traceback
            print(f"❌ scan_loop 异常: {e}")
            print(f"❌ 详细堆栈:\n{traceback.format_exc()}")

        now = datetime.now(timezone.utc)
        sleep_seconds = seconds_to_next_scan_close(now)
        print(f"⏳ 距离下次{SCAN_INTERVAL}m扫描还有 {int(sleep_seconds)} 秒")
        await asyncio.sleep(sleep_seconds)


# ========= 独立价格监控任务 =========
async def price_monitor_loop():
    """
    独立的价格监控任务，高频更新峰值和检查移动止盈
    每 PRICE_MONITOR_INTERVAL 秒执行一次
    
    注意：如果 TRAILING_STOP_ENABLED = False，此任务会直接退出
    """
    # 如果动态止盈未启用，直接退出任务
    if not TRAILING_STOP_ENABLED:
        print("ℹ️ 动态止盈未启用，价格监控任务跳过")
        return
    
    print(f"🔍 价格监控任务启动，间隔 {PRICE_MONITOR_INTERVAL} 秒")
    
    while True:
        try:
            # 获取当前持仓（同步函数）
            get_account_status()
            positions = account_snapshot.get("positions", [])
            
            if not positions:
                await asyncio.sleep(PRICE_MONITOR_INTERVAL)
                continue
            
            trailing_stop_signals = []
            
            for p in positions:
                try:
                    size = float(p.get("size", 0))
                    if size == 0:
                        continue
                    
                    symbol = p.get("symbol")
                    side = "LONG" if size > 0 else "SHORT"
                    mark_price = float(p.get("mark_price", 0))
                    entry_price = float(p.get("entry", 0))
                    
                    if not symbol or mark_price <= 0 or entry_price <= 0:
                        continue
                    
                    # 更新峰值统计
                    update_trade_stats(symbol, side, mark_price)
                    
                    # 检查移动止盈
                    ts_result = check_trailing_stop(symbol, side, mark_price, entry_price)
                    if ts_result.get("triggered"):
                        close_action = "close_long" if side == "LONG" else "close_short"
                        trailing_stop_signals.append({
                            "symbol": symbol,
                            "action": close_action,
                            "side": side,
                            "quantity": abs(size)
                            # reason 只用于日志，不传给 execute_trade_async
                        })
                        log_info(f"🎯 动态回撤止盈触发 | {symbol} | {side} | {ts_result.get('reason')}")
                
                except Exception as e:
                    continue
            
            # 执行移动止盈平仓（带重试）
            if trailing_stop_signals:
                for sig in trailing_stop_signals:
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            result = await execute_trade_async(
                                symbol=sig["symbol"],
                                action=sig["action"],
                                position_size=0,  # 平仓不需要
                                stop_loss=None,
                                take_profit=None,
                                order_type="market"
                            )
                            if result:
                                log_info(f"🎯 移动止盈平仓完成 | {sig['symbol']} | {sig['side']}")
                                break
                            else:
                                log_error(f"⚠️ 移动止盈平仓返回空 | {sig['symbol']} | 第{attempt+1}次")
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(1)
                        except Exception as e:
                            log_error(f"❌ 移动止盈平仓失败 | {sig['symbol']} | 第{attempt+1}次 | {e}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
        
        except Exception as e:
            log_error(f"❌ 价格监控异常: {e}")
        
        await asyncio.sleep(PRICE_MONITOR_INTERVAL)


async def schedule_loop_async_with_monitor():
    """只保留 scan_loop + 价格监控"""
    print(f"⏳ 启动调度：{SCAN_INTERVAL}m 全市场扫描 + {PRICE_MONITOR_INTERVAL}s 价格监控")
    await asyncio.gather(
        scan_loop(),
        price_monitor_loop(),
    )
