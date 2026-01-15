# trade_tracker.py
"""
交易追踪模块：记录完整的开平仓配对信息
- 开仓时记录到活跃交易缓存
- 持仓期间追踪峰值收益和最大回撤
- 平仓时计算完整统计并保存
"""
import json
import time
from database import redis_client

# Redis Keys
KEY_ACTIVE_TRADES = "active_trades"      # 活跃交易（未平仓）
KEY_COMPLETED_TRADES = "completed_trades" # 已完成交易（完整记录）
KEY_TRADING_RECORDS = "trading_records"   # 原有的简单记录（保持兼容）


def sync_positions_to_active_trades(current_positions: list):
    """
    同步当前持仓到活跃交易记录
    - 如果有持仓但没有活跃交易记录（比如限价单成交），自动补记录
    - 检查并设置缺失的 TP/SL
    - 返回新增的交易记录列表
    """
    new_trades = []
    
    for p in current_positions:
        size = float(p.get("size", 0))
        if size == 0:
            continue
        
        symbol = p.get("symbol")
        side = "LONG" if size > 0 else "SHORT"
        key = f"{symbol}:{side}"
        
        # 检查是否已有活跃交易记录
        existing = redis_client.hget(KEY_ACTIVE_TRADES, key)
        if existing:
            # 已有记录，检查是否需要补设 TP/SL（限价单成交后）
            trade_data = json.loads(existing)
            if trade_data.get("pending_tp_sl"):
                # 标记需要设置 TP/SL
                trade_data["needs_tp_sl_setup"] = True
                trade_data.pop("pending_tp_sl", None)
                redis_client.hset(KEY_ACTIVE_TRADES, key, json.dumps(trade_data))
            continue
        
        # 没有记录，说明是限价单成交或其他方式开仓，补记录
        entry_price = float(p.get("entry", 0))
        quantity = abs(size)
        leverage = int(p.get("leverage", 1))
        
        trade = record_open_trade(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            order_type="limit",  # 假设是限价单成交
            fee=0,  # 无法获取历史手续费
            leverage=leverage
        )
        # 标记需要设置 TP/SL
        trade["needs_tp_sl_setup"] = True
        redis_client.hset(KEY_ACTIVE_TRADES, key, json.dumps(trade))
        
        new_trades.append(trade)
        print(f"📝 补记录活跃交易 | {symbol} | {side} | entry={entry_price}")
    
    return new_trades


def record_open_trade(symbol: str, side: str, entry_price: float, quantity: float,
                      order_type: str = "market", fee: float = 0, leverage: int = 1):
    """
    记录开仓交易
    side: "LONG" 或 "SHORT"
    """
    trade_id = f"{symbol}_{side}_{int(time.time() * 1000)}"
    
    trade = {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "entry_time": int(time.time()),
        "quantity": quantity,
        "order_type": order_type,
        "entry_fee": fee,
        "leverage": leverage,
        # 追踪字段
        "peak_pnl": 0.0,
        "peak_price": entry_price,
        "max_drawdown": 0.0,
        "trough_price": entry_price,
    }
    
    # 存储到活跃交易（用 symbol:side 作为 key，支持同币种双向持仓）
    key = f"{symbol}:{side}"
    redis_client.hset(KEY_ACTIVE_TRADES, key, json.dumps(trade))
    
    return trade


def update_trade_stats(symbol: str, side: str, current_price: float):
    """
    更新活跃交易的峰值收益和最大回撤
    应该在每次价格更新时调用
    """
    key = f"{symbol}:{side}"
    raw = redis_client.hget(KEY_ACTIVE_TRADES, key)
    if not raw:
        return None
    
    trade = json.loads(raw)
    entry_price = trade["entry_price"]
    quantity = trade["quantity"]
    
    # 计算当前 PnL
    if side == "LONG":
        current_pnl = (current_price - entry_price) * quantity
    else:  # SHORT
        current_pnl = (entry_price - current_price) * quantity
    
    # 更新峰值
    if current_pnl > trade["peak_pnl"]:
        trade["peak_pnl"] = current_pnl
        trade["peak_price"] = current_price
    
    # 更新最大回撤（从峰值回落）
    drawdown = trade["peak_pnl"] - current_pnl
    if drawdown > trade["max_drawdown"]:
        trade["max_drawdown"] = drawdown
        trade["trough_price"] = current_price
    
    redis_client.hset(KEY_ACTIVE_TRADES, key, json.dumps(trade))
    return trade


def record_close_trade(symbol: str, side: str, exit_price: float, exit_quantity: float,
                       close_type: str = "market", fee: float = 0):
    """
    记录平仓交易，生成完整的交易记录
    返回完整的交易统计
    """
    key = f"{symbol}:{side}"
    raw = redis_client.hget(KEY_ACTIVE_TRADES, key)
    
    if not raw:
        # 没有找到对应的开仓记录，创建一个简化记录
        return _create_simple_close_record(symbol, side, exit_price, exit_quantity, close_type, fee)
    
    trade = json.loads(raw)
    entry_price = trade["entry_price"]
    entry_time = trade["entry_time"]
    quantity = trade["quantity"]
    
    # 计算最终 PnL
    if side == "LONG":
        net_pnl = (exit_price - entry_price) * exit_quantity
    else:  # SHORT
        net_pnl = (entry_price - exit_price) * exit_quantity
    
    # ========= 平仓时更新峰值和回撤 =========
    # 确保峰值收益至少等于最终收益（如果最终收益更高）
    peak_pnl = trade.get("peak_pnl", 0)
    if net_pnl > peak_pnl:
        peak_pnl = net_pnl
    
    # 计算最大回撤（从峰值到最低点的回落）
    max_drawdown = trade.get("max_drawdown", 0)
    # 如果最终收益低于峰值，检查是否是新的最大回撤
    if peak_pnl > net_pnl:
        current_drawdown = peak_pnl - net_pnl
        if current_drawdown > max_drawdown:
            max_drawdown = current_drawdown
    
    # 计算持仓时长
    exit_time = int(time.time())
    hold_seconds = exit_time - entry_time
    hold_minutes = hold_seconds // 60
    
    # 总手续费
    total_fee = trade.get("entry_fee", 0) + fee
    
    # 净收益（扣除手续费）
    net_profit = net_pnl - total_fee
    
    # 收益率
    position_value = entry_price * quantity
    pnl_pct = (net_pnl / position_value * 100) if position_value > 0 else 0
    
    # 完整交易记录
    completed = {
        "trade_id": trade["trade_id"],
        "symbol": symbol,
        "side": side,
        # 开仓信息
        "entry_price": entry_price,
        "entry_time": entry_time,
        "entry_type": trade.get("order_type", "market"),
        # 平仓信息
        "exit_price": exit_price,
        "exit_time": exit_time,
        "exit_type": close_type,
        # 数量
        "quantity": exit_quantity,
        "leverage": trade.get("leverage", 1),
        # 收益统计
        "net_pnl": round(net_pnl, 4),
        "net_profit": round(net_profit, 4),
        "pnl_pct": round(pnl_pct, 2),
        # 峰值和回撤（使用更新后的值）
        "peak_pnl": round(peak_pnl, 4),
        "max_drawdown": round(max_drawdown, 4),
        # 手续费
        "entry_fee": trade.get("entry_fee", 0),
        "exit_fee": fee,
        "total_fee": round(total_fee, 4),
        # 持仓时长
        "hold_seconds": hold_seconds,
        "hold_minutes": hold_minutes,
        # 状态
        "status": "CLOSED",
    }
    
    # 保存到已完成交易
    redis_client.lpush(KEY_COMPLETED_TRADES, json.dumps(completed))
    
    # 从活跃交易中移除
    redis_client.hdel(KEY_ACTIVE_TRADES, key)
    
    return completed


def _create_simple_close_record(symbol, side, exit_price, quantity, close_type, fee):
    """创建简化的平仓记录（没有找到对应开仓时使用）"""
    exit_time = int(time.time())
    
    record = {
        "trade_id": f"{symbol}_{side}_{exit_time}",
        "symbol": symbol,
        "side": side,
        "entry_price": None,
        "entry_time": None,
        "entry_type": None,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "exit_type": close_type,
        "quantity": quantity,
        "leverage": 1,
        "net_pnl": None,
        "net_profit": None,
        "pnl_pct": None,
        "peak_pnl": None,
        "max_drawdown": None,
        "entry_fee": 0,
        "exit_fee": fee,
        "total_fee": fee,
        "hold_seconds": None,
        "hold_minutes": None,
        "status": "CLOSED_NO_ENTRY",
    }
    
    redis_client.lpush(KEY_COMPLETED_TRADES, json.dumps(record))
    return record


def get_active_trades():
    """获取所有活跃交易"""
    raw = redis_client.hgetall(KEY_ACTIVE_TRADES)
    trades = []
    for k, v in raw.items():
        try:
            trades.append(json.loads(v))
        except:
            pass
    return trades


def get_completed_trades(limit: int = 100):
    """获取已完成交易"""
    raw = redis_client.lrange(KEY_COMPLETED_TRADES, 0, limit - 1)
    trades = []
    for r in raw:
        try:
            trades.append(json.loads(r))
        except:
            pass
    return trades


def get_active_trade(symbol: str, side: str):
    """获取指定的活跃交易"""
    key = f"{symbol}:{side}"
    raw = redis_client.hget(KEY_ACTIVE_TRADES, key)
    if raw:
        return json.loads(raw)
    return None


def check_trailing_stop(symbol: str, side: str, current_price: float, entry_price: float) -> dict:
    """
    检查是否触发动态回撤止盈（自适应ATR版本）
    
    核心逻辑：
    1. 盈利越高，ATR倍数越小（止盈越紧，锁定利润）
    2. 设置最大回撤上限，防止ATR太大导致回吐过多
    3. 低门槛激活，尽早开始追踪峰值
    
    返回: {"triggered": True/False, "reason": "...", "profit_pct": x, "drawdown_pct": x}
    """
    from config import (
        TRAILING_STOP_ENABLED, 
        TRAILING_STOP_ACTIVATE_PCT,
        ATR_TRAILING_STOP_ENABLED,
        ATR_TRAILING_TIERS,
        ATR_MAX_DRAWDOWN_PCT
    )
    
    if not TRAILING_STOP_ENABLED:
        return {"triggered": False, "reason": "移动止盈未启用"}
    
    # 获取活跃交易记录
    trade = get_active_trade(symbol, side)
    if not trade:
        return {"triggered": False, "reason": "未找到活跃交易记录"}
    
    peak_price = trade.get("peak_price", entry_price)
    
    # 计算当前盈亏百分比
    if side == "LONG":
        current_pnl_pct = (current_price - entry_price) / entry_price * 100
        peak_pnl_pct = (peak_price - entry_price) / entry_price * 100
        price_drawdown = peak_price - current_price  # 价格回撤金额
        drawdown_pct = (peak_price - current_price) / entry_price * 100  # 回撤百分比
    else:  # SHORT
        current_pnl_pct = (entry_price - current_price) / entry_price * 100
        peak_pnl_pct = (entry_price - peak_price) / entry_price * 100
        price_drawdown = current_price - peak_price  # 价格回撤金额
        drawdown_pct = (current_price - peak_price) / entry_price * 100  # 回撤百分比
    
    # 检查是否达到激活条件
    if peak_pnl_pct < TRAILING_STOP_ACTIVATE_PCT:
        return {
            "triggered": False, 
            "reason": f"峰值盈利 {peak_pnl_pct:.2f}% 未达激活条件 {TRAILING_STOP_ACTIVATE_PCT}%",
            "profit_pct": current_pnl_pct,
            "peak_pnl_pct": peak_pnl_pct
        }
    
    # ========== 自适应 ATR 动态止盈 ==========
    if ATR_TRAILING_STOP_ENABLED:
        atr = _get_symbol_atr(symbol)
        if atr and atr > 0:
            # 根据盈利区间选择ATR倍数（盈利越高，倍数越小）
            atr_mult = 1.0  # 默认
            for tier in ATR_TRAILING_TIERS:
                if tier["min_profit"] <= peak_pnl_pct < tier["max_profit"]:
                    atr_mult = tier["atr_mult"]
                    break
            
            # 计算ATR允许的回撤
            atr_allowed_drawdown = atr * atr_mult
            
            # 计算最大回撤上限（防止ATR太大）
            max_drawdown_price = entry_price * ATR_MAX_DRAWDOWN_PCT / 100
            
            # 取两者中较小的作为实际允许回撤
            allowed_drawdown_price = min(atr_allowed_drawdown, max_drawdown_price)
            
            # 判断是否触发
            if price_drawdown >= allowed_drawdown_price:
                trigger_type = "ATR" if atr_allowed_drawdown <= max_drawdown_price else "最大回撤"
                return {
                    "triggered": True,
                    "reason": f"🎯 {trigger_type}止盈 | 峰值盈利{peak_pnl_pct:.2f}% | 回撤{drawdown_pct:.2f}% > 阈值{allowed_drawdown_price/entry_price*100:.2f}% | ATR={atr:.2f} 倍数{atr_mult}",
                    "profit_pct": current_pnl_pct,
                    "peak_pnl_pct": peak_pnl_pct,
                    "atr": atr,
                    "atr_mult": atr_mult,
                    "price_drawdown": price_drawdown,
                    "drawdown_pct": drawdown_pct
                }
            
            return {
                "triggered": False,
                "reason": f"ATR追踪 | 峰值{peak_pnl_pct:.2f}% 当前{current_pnl_pct:.2f}% | 回撤{drawdown_pct:.2f}% < 阈值{allowed_drawdown_price/entry_price*100:.2f}% | ATR={atr:.2f}×{atr_mult}",
                "profit_pct": current_pnl_pct,
                "peak_pnl_pct": peak_pnl_pct,
                "atr": atr,
                "atr_mult": atr_mult,
                "price_drawdown": price_drawdown,
                "drawdown_pct": drawdown_pct
            }
        else:
            # ATR 不可用，降级到百分比止盈
            print(f"⚠️ ATR不可用 | {symbol} | 降级到百分比止盈")
    
    # ========== 百分比回撤止盈（ATR不可用时的备用）==========
    from config import TRAILING_STOP_TIERS
    
    if peak_pnl_pct > 0:
        drawdown_from_peak_pct = (peak_pnl_pct - current_pnl_pct) / peak_pnl_pct * 100
    else:
        drawdown_from_peak_pct = 0
    
    allowed_drawdown = 50  # 默认
    for tier in TRAILING_STOP_TIERS:
        if tier["min_profit"] <= peak_pnl_pct < tier["max_profit"]:
            allowed_drawdown = tier["drawdown_pct"]
            break
    
    if drawdown_from_peak_pct >= allowed_drawdown:
        return {
            "triggered": True,
            "reason": f"🎯 百分比止盈 | 峰值{peak_pnl_pct:.2f}% → 当前{current_pnl_pct:.2f}% | 回撤{drawdown_from_peak_pct:.1f}% > 阈值{allowed_drawdown}%",
            "profit_pct": current_pnl_pct,
            "peak_pnl_pct": peak_pnl_pct,
            "drawdown_from_peak": drawdown_from_peak_pct,
            "allowed_drawdown": allowed_drawdown
        }
    
    return {
        "triggered": False,
        "reason": f"追踪中 | 峰值{peak_pnl_pct:.2f}% 当前{current_pnl_pct:.2f}% | 回撤{drawdown_from_peak_pct:.1f}% < 阈值{allowed_drawdown}%",
        "profit_pct": current_pnl_pct,
        "peak_pnl_pct": peak_pnl_pct,
        "drawdown_from_peak": drawdown_from_peak_pct,
        "allowed_drawdown": allowed_drawdown
    }


def _get_symbol_atr(symbol: str) -> float:
    """从 Redis 获取币种的 ATR"""
    import json
    try:
        # 从 15m 指标数据获取 ATR
        rkey = f"historical_data:{symbol}:15m"
        data = redis_client.hgetall(rkey)
        if not data or len(data) < 20:
            return None
        
        import numpy as np
        import talib
        
        rows = sorted(data.items(), key=lambda x: int(x[0]))
        rows = [{"Timestamp": int(ts), **json.loads(v)} for ts, v in rows]
        
        highs = np.array([float(k["High"]) for k in rows], dtype=np.float64)
        lows = np.array([float(k["Low"]) for k in rows], dtype=np.float64)
        closes = np.array([float(k["Close"]) for k in rows], dtype=np.float64)
        
        atr = talib.ATR(highs, lows, closes, timeperiod=14)
        return float(atr[-1]) if not np.isnan(atr[-1]) else None
    except Exception:
        return None


def check_and_record_auto_closed(current_positions: list):
    """
    检查是否有仓位被止损/止盈自动平仓
    current_positions: 当前账户持仓列表 [{"symbol": "BTCUSDT", "size": 0.1, ...}, ...]
    
    改进：通过交易所订单历史验证，避免误判
    """
    from account_positions import client
    
    # 获取所有活跃交易
    active_trades = get_active_trades()
    if not active_trades:
        return []
    
    # 构建当前持仓的 symbol:side 集合
    current_pos_keys = set()
    for p in current_positions:
        size = float(p.get("size", 0))
        if size != 0:
            symbol = p.get("symbol")
            side = "LONG" if size > 0 else "SHORT"
            current_pos_keys.add(f"{symbol}:{side}")
    
    closed_trades = []
    
    for trade in active_trades:
        symbol = trade.get("symbol")
        side = trade.get("side")
        key = f"{symbol}:{side}"
        
        # 如果活跃交易不在当前持仓中，需要验证是否真的被平仓
        if key not in current_pos_keys:
            entry_time = trade.get("entry_time", 0)
            
            # ========= 通过订单历史验证是否真的平仓 =========
            exit_price = None
            exit_fee = 0
            verified_closed = False
            
            try:
                # 获取最近成交记录来验证平仓
                trades_history = client.futures_account_trades(symbol=symbol, limit=20)
                if trades_history:
                    entry_time_ms = entry_time * 1000  # 转为毫秒
                    
                    for t in reversed(trades_history):
                        trade_time = t.get("time", 0)
                        # 找到开仓之后的成交记录
                        if trade_time > entry_time_ms:
                            # 检查是否是平仓方向
                            is_buyer = t.get("buyer", False)
                            pos_side = t.get("positionSide", "")
                            
                            # 验证方向匹配
                            if pos_side == side:
                                # LONG 平仓是卖出，SHORT 平仓是买入
                                if (side == "LONG" and not is_buyer) or (side == "SHORT" and is_buyer):
                                    exit_price = float(t.get("price", 0))
                                    exit_fee = float(t.get("commission", 0))
                                    verified_closed = True
                                    break
                
                # 如果没有找到平仓成交记录，可能是数据延迟，跳过本次检查
                if not verified_closed:
                    # 检查是否有 REALIZED_PNL 记录作为备用验证
                    try:
                        income = client.futures_income_history(
                            symbol=symbol,
                            incomeType="REALIZED_PNL",
                            limit=10
                        )
                        if income:
                            for inc in income:
                                inc_time = int(inc.get("time", 0))
                                if inc_time > entry_time * 1000 and inc.get("symbol") == symbol:
                                    realized_pnl = float(inc.get("income", 0))
                                    trade["realized_pnl_from_exchange"] = realized_pnl
                                    verified_closed = True
                                    # 使用入场价作为备用（不准确但有记录）
                                    exit_price = trade.get("entry_price", 0)
                                    break
                    except Exception:
                        pass
                
                # 如果仍未验证，跳过（可能是数据延迟或其他原因）
                if not verified_closed:
                    print(f"⚠️ 无法验证 {symbol}:{side} 是否已平仓，跳过本次检查")
                    continue
                    
            except Exception as e:
                print(f"⚠️ 验证平仓信息失败: {e}")
                continue
            
            # 记录平仓
            completed = _record_auto_close(trade, exit_price, exit_fee)
            if completed:
                closed_trades.append(completed)
    
    return closed_trades


def _record_auto_close(trade: dict, exit_price: float, exit_fee: float = 0):
    """记录自动平仓（止损/止盈触发）"""
    symbol = trade.get("symbol")
    side = trade.get("side")
    entry_price = trade.get("entry_price", 0)
    quantity = trade.get("quantity", 0)
    entry_time = trade.get("entry_time", 0)
    
    # 优先使用交易所返回的实际 PnL
    if "realized_pnl_from_exchange" in trade:
        net_pnl = trade["realized_pnl_from_exchange"]
    else:
        # 计算 PnL
        if side == "LONG":
            net_pnl = (exit_price - entry_price) * quantity
        else:
            net_pnl = (entry_price - exit_price) * quantity
    
    exit_time = int(time.time())
    hold_seconds = exit_time - entry_time if entry_time else 0
    hold_minutes = hold_seconds // 60
    
    # 更新峰值和回撤
    peak_pnl = trade.get("peak_pnl", 0)
    if net_pnl > peak_pnl:
        peak_pnl = net_pnl
    
    max_drawdown = trade.get("max_drawdown", 0)
    if peak_pnl > net_pnl:
        current_drawdown = peak_pnl - net_pnl
        if current_drawdown > max_drawdown:
            max_drawdown = current_drawdown
    
    total_fee = trade.get("entry_fee", 0) + exit_fee
    position_value = entry_price * quantity if entry_price and quantity else 0
    pnl_pct = (net_pnl / position_value * 100) if position_value > 0 else 0
    
    completed = {
        "trade_id": trade.get("trade_id", f"{symbol}_{side}_{exit_time}"),
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "entry_time": entry_time,
        "entry_type": trade.get("order_type", "market"),
        "exit_price": exit_price,
        "exit_time": exit_time,
        "exit_type": "auto_sl_tp",  # 标记为自动止损/止盈
        "quantity": quantity,
        "leverage": trade.get("leverage", 1),
        "net_pnl": round(net_pnl, 4),
        "net_profit": round(net_pnl - total_fee, 4),
        "pnl_pct": round(pnl_pct, 2),
        "peak_pnl": round(peak_pnl, 4),
        "max_drawdown": round(max_drawdown, 4),
        "entry_fee": trade.get("entry_fee", 0),
        "exit_fee": exit_fee,
        "total_fee": round(total_fee, 4),
        "hold_seconds": hold_seconds,
        "hold_minutes": hold_minutes,
        "status": "CLOSED_AUTO",
    }
    
    # 保存到已完成交易
    redis_client.lpush(KEY_COMPLETED_TRADES, json.dumps(completed))
    
    # 从活跃交易中移除
    key = f"{symbol}:{side}"
    redis_client.hdel(KEY_ACTIVE_TRADES, key)
    
    return completed
