import asyncio
import time
from database import redis_client
import json
from binance.client import Client
from binance.exceptions import BinanceAPIException
from config import BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_ENVIRONMENT, PROXY
from account_positions import get_account_status
from trade_tracker import record_open_trade, record_close_trade, update_trade_stats
from logger import log_info, log_error, log_trade, log_debug
import math

requests_params = {
    "proxies": {"http": PROXY, "https": PROXY},
    "timeout": 30  # 增加超时时间到 30 秒
} if PROXY else {"timeout": 30}
client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET, testnet=BINANCE_ENVIRONMENT, requests_params=requests_params)
REDIS_KEY = "trading_records"

TP_SL_TYPES = {
    "sl": ["STOP", "STOP_MARKET"],
    "tp": ["TAKE_PROFIT", "TAKE_PROFIT_MARKET"]
}

# ====== 调试开关：只在你需要时打印 openAlgoOrders 样本 ======
DEBUG_ALGO_SAMPLE = False   # 上线建议改 False

def save_trade_record(record: dict):
    """保存交易记录"""
    redis_client.lpush(REDIS_KEY, json.dumps(record))


# ========= 限价单管理 =========
REDIS_KEY_LIMIT_ORDERS = "pending_limit_orders"  # 记录未成交限价单


def record_limit_order(symbol: str, order_id: int, side: str, position_side: str, price: float, quantity: float):
    """记录限价单信息，用于后续超时检查"""
    order_info = {
        "symbol": symbol,
        "order_id": order_id,
        "side": side,
        "position_side": position_side,
        "price": price,
        "quantity": quantity,
        "create_time": int(time.time())
    }
    redis_client.hset(REDIS_KEY_LIMIT_ORDERS, f"{symbol}:{order_id}", json.dumps(order_info))
    log_info(f"📝 记录限价单 | {symbol} | {position_side} | orderId={order_id} | price={price}")


def remove_limit_order_record(symbol: str, order_id: int):
    """移除限价单记录（成交或撤销后调用）"""
    redis_client.hdel(REDIS_KEY_LIMIT_ORDERS, f"{symbol}:{order_id}")


async def check_and_cancel_expired_limit_orders():
    """
    检查并撤销超时的限价单
    改进版：直接从交易所获取所有未成交限价单，不依赖本地记录
    返回撤销的订单列表
    """
    from config import LIMIT_ORDER_TIMEOUT_MINUTES, LIMIT_ORDER_CHECK_ENABLED
    
    if not LIMIT_ORDER_CHECK_ENABLED:
        return []
    
    cancelled = []
    now = int(time.time() * 1000)  # 毫秒
    timeout_ms = LIMIT_ORDER_TIMEOUT_MINUTES * 60 * 1000
    
    try:
        # 直接从交易所获取所有未成交订单
        all_open_orders = await async_to_thread(client.futures_get_open_orders)
        
        for order in all_open_orders:
            # 只处理限价单（LIMIT 类型）
            if order.get("type") != "LIMIT":
                continue
            
            # 只处理未成交状态
            if order.get("status") not in ["NEW", "PARTIALLY_FILLED"]:
                continue
            
            order_time = order.get("time", 0)
            elapsed_ms = now - order_time
            
            if elapsed_ms >= timeout_ms:
                symbol = order.get("symbol")
                order_id = order.get("orderId")
                position_side = order.get("positionSide", "")
                price = order.get("price", 0)
                elapsed_minutes = elapsed_ms // 60000
                
                try:
                    await async_to_thread(client.futures_cancel_order, symbol=symbol, orderId=order_id)
                    log_info(f"⏰ 限价单超时撤销 | {symbol} | {position_side} | orderId={order_id} | price={price} | 已挂 {elapsed_minutes} 分钟")
                    cancelled.append({
                        "symbol": symbol,
                        "order_id": order_id,
                        "position_side": position_side,
                        "price": price,
                        "elapsed_minutes": elapsed_minutes
                    })
                    
                    # 同时清理本地记录（如果有）
                    remove_limit_order_record(symbol, order_id)
                    
                except Exception as e:
                    if "Unknown order" in str(e) or "-2011" in str(e):
                        log_info(f"ℹ️ 限价单已不存在 | {symbol} | orderId={order_id}")
                    else:
                        log_error(f"⚠️ 撤销限价单失败 | {symbol} | orderId={order_id} | {e}")
    
    except Exception as e:
        log_error(f"⚠️ 获取未成交订单失败: {e}")
    
    return cancelled


async def sync_limit_order_records():
    """
    同步限价单记录：清理已成交/已撤销的记录
    应该在每轮扫描时调用
    """
    all_records = redis_client.hgetall(REDIS_KEY_LIMIT_ORDERS)
    
    if not all_records:
        return
    
    # 按 symbol 分组
    symbols = set()
    for key in all_records.keys():
        key_str = key.decode() if isinstance(key, bytes) else key
        symbol = key_str.split(":")[0]
        symbols.add(symbol)
    
    # 获取每个 symbol 的当前挂单
    for symbol in symbols:
        try:
            open_orders = await async_to_thread(client.futures_get_open_orders, symbol=symbol)
            open_order_ids = {o.get("orderId") for o in open_orders}
            
            # 检查记录中的订单是否还存在
            for key, value in all_records.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                if not key_str.startswith(f"{symbol}:"):
                    continue
                
                order_info = json.loads(value)
                order_id = order_info.get("order_id")
                
                if order_id not in open_order_ids:
                    # 订单已不存在，移除记录
                    remove_limit_order_record(symbol, order_id)
                    log_debug(f"🧹 清理已成交/撤销的限价单记录 | {symbol} | orderId={order_id}")
        
        except Exception as e:
            log_error(f"⚠️ 同步限价单记录失败 | {symbol} | {e}")

# -----------------------------
# 异步工具函数
# -----------------------------
async def async_to_thread(func, *args, **kwargs):
    """将阻塞函数异步化（兼容 Python 3.8）"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

# -----------------------------
# 异步价格、数量、最小下单额
# -----------------------------
async def get_min_notional_async(symbol: str, default=0):
    info = await async_to_thread(client.futures_exchange_info)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol:
            for f in s.get("filters", []):
                if f.get("filterType") == "MIN_NOTIONAL":
                    try:
                        return float(f.get("notional", default))
                    except Exception:
                        return default
    return default

async def normalize_qty_async(symbol: str, qty: float):
    info = await async_to_thread(client.futures_exchange_info)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol:
            step = 1
            min_qty = 0
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    step = float(f.get("stepSize", 1))
                    min_qty = float(f.get("minQty", 0))
            decimals = max(0, -int(math.log10(step)))
            qty = max(qty, min_qty)
            qty = math.ceil(qty / step) * step
            qty = round(qty, decimals)

            min_notional = await get_min_notional_async(symbol)
            mark_price = float((await async_to_thread(client.futures_mark_price, symbol=symbol))["markPrice"])
            notional = qty * mark_price
            if notional < min_notional:
                qty = math.ceil(min_notional / mark_price / step) * step
                qty = round(qty, decimals)
            return qty
    return qty

async def normalize_price_async(symbol: str, price: float):
    info = await async_to_thread(client.futures_exchange_info)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol:
            tick_size = 0.01
            min_price = 0.0
            max_price = 0.0
            for f in s.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", 0.01))
                    min_price = float(f.get("minPrice", 0))
                    max_price = float(f.get("maxPrice", 0))
            price = math.floor(price / tick_size) * tick_size
            decimals = max(0, -int(math.log10(tick_size)))
            price = round(price, decimals)
            price = max(price, min_price)
            price = min(price, max_price)
            return price
    return price

# -----------------------------
# 异步 TP/SL 撤单与下单
# -----------------------------
async def _print_open_algo_sample_by_id(algo_id, symbol, tag):
    """创建成功后打印 openAlgoOrders 里对应的订单 dict（只打印一条）"""
    if not DEBUG_ALGO_SAMPLE:
        return
    try:
        all_orders = await async_to_thread(client.futures_get_open_algo_orders)
        sample = next((o for o in all_orders if o.get("algoId") == algo_id), None)
        if sample:
            print(f"📦【{tag}_OPEN_ALGO_KEYS】", list(sample.keys()))
            print(f"📦【{tag}_OPEN_ALGO】", sample)
        else:
            print(f"⚠【{tag}_OPEN_ALGO】未在 openAlgoOrders 中找到 algoId={algo_id} symbol={symbol}")
    except Exception as e:
        print(f"⚠【{tag}_OPEN_ALGO】查询失败: {e}")

async def get_current_sl_tp_async(symbol: str, position_side: str):
    current_sl = None
    current_tp = None

    # -------- 1) Algo 条件单（主来源）--------
    try:
        algo_all = await async_to_thread(client.futures_get_open_algo_orders)
        algo_orders = [o for o in algo_all if o.get("symbol") == symbol]
    except Exception:
        algo_orders = []

    for o in algo_orders:
        if o.get("positionSide") != position_side:
            continue

        order_type = o.get("orderType")  # e.g. STOP_MARKET / TAKE_PROFIT_MARKET
        # 不同接口可能叫 triggerPrice / stopPrice，这里做兼容
        trig = o.get("triggerPrice") or o.get("stopPrice") or o.get("price")
        if trig is None:
            continue

        try:
            sp = float(trig)
        except Exception:
            continue

        # SL
        if order_type in TP_SL_TYPES["sl"]:
            if current_sl is None:
                current_sl = sp
            else:
                if position_side == "LONG":
                    current_sl = max(current_sl, sp)  # 多单 SL 越高越保护
                else:
                    current_sl = min(current_sl, sp)  # 空单 SL 越低越保护

        # TP
        if order_type in TP_SL_TYPES["tp"]:
            if current_tp is None:
                current_tp = sp
            else:
                if position_side == "LONG":
                    current_tp = min(current_tp, sp)  # 多单 TP 越低越先触发
                else:
                    current_tp = max(current_tp, sp)  # 空单 TP 越高越先触发

    # -------- 2) 基础挂单（兼容）--------
    try:
        open_orders = await async_to_thread(client.futures_get_open_orders, symbol=symbol)
    except Exception:
        open_orders = []

    for o in open_orders:
        if o.get("positionSide") != position_side:
            continue
        typ = o.get("type")  # STOP / STOP_MARKET / TAKE_PROFIT / TAKE_PROFIT_MARKET
        stop_price = o.get("stopPrice")
        if stop_price is None:
            continue

        try:
            sp = float(stop_price)
        except Exception:
            continue

        if typ in TP_SL_TYPES["sl"]:
            if current_sl is None:
                current_sl = sp
            else:
                if position_side == "LONG":
                    current_sl = max(current_sl, sp)
                else:
                    current_sl = min(current_sl, sp)

        if typ in TP_SL_TYPES["tp"]:
            if current_tp is None:
                current_tp = sp
            else:
                if position_side == "LONG":
                    current_tp = min(current_tp, sp)
                else:
                    current_tp = max(current_tp, sp)

    return current_sl, current_tp

def is_sl_update_valid(position_side: str, current_price: float, current_sl: float, new_sl: float) -> bool:
    """
    止损更新合法性校验（放宽版）：
    - 只检查止损位置是否在正确的方向（不会立即触发）
    - 允许 AI 根据市场情况调整止损（收紧或放宽都可以）
    """
    if position_side == "LONG":
        # 多单：止损必须在当前价下方
        valid = new_sl < current_price
        if not valid:
            log_info(f"⛔ SL校验失败 | LONG | new_sl={new_sl} >= price={current_price}")
        return valid
    else:  # SHORT
        # 空单：止损必须在当前价上方
        valid = new_sl > current_price
        if not valid:
            log_info(f"⛔ SL校验失败 | SHORT | new_sl={new_sl} <= price={current_price}")
        return valid

def is_tp_update_valid(position_side: str, current_price: float, current_tp: float, new_tp: float) -> bool:
    """
    止盈更新合法性校验（放宽版）：
    - 只检查止盈位置是否在正确的方向（不会立即触发）
    - 允许 AI 根据市场情况调整止盈（延伸或收紧都可以）
    """
    if position_side == "LONG":
        # 多单：止盈必须在当前价上方
        valid = new_tp > current_price
        if not valid:
            log_info(f"TP校验失败 | LONG | new_tp={new_tp} <= price={current_price}")
        return valid
    else:  # SHORT
        # 空单：止盈必须在当前价下方
        valid = new_tp < current_price
        if not valid:
            log_info(f"TP校验失败 | SHORT | new_tp={new_tp} >= price={current_price}")
        return valid

async def cancel_algo_order_async(symbol, algoId=None, clientAlgoId=None):
    if not algoId and not clientAlgoId:
        print("⚠ 必须提供 algoId 或 clientAlgoId")
        return

    # print(f"\n🧹【CANCEL_TRY】symbol={symbol} algoId={algoId} clientAlgoId={clientAlgoId}")

    try:
        await async_to_thread(
            client.futures_cancel_algo_order,
            symbol=symbol,
            algoId=algoId,
            clientAlgoId=clientAlgoId
        )
        # print(f"✅【CANCEL_OK】algoId={algoId} clientAlgoId={clientAlgoId}")
        return

    except Exception as e:
        # -2011 通常是竞态（已触发/已撤/不存在）——只在报错后检查一次再决定是否忽略
        if "code=-2011" in str(e):
            try:
                current_all = await async_to_thread(client.futures_get_open_algo_orders)
                current = [o for o in current_all if o.get("symbol") == symbol]

                still_exists = any(
                    (algoId is not None and o.get("algoId") == algoId) or
                    (clientAlgoId is not None and o.get("clientAlgoId") == clientAlgoId)
                    for o in current
                )
                print(
                    f"🧹【CANCEL_CHECK_AFTER_FAIL】still_exists={still_exists} "
                    f"openAlgoCount(all)={len(current_all)} openAlgoCount(symbol)={len(current)}"
                )
                if still_exists is False:
                    print(f"ℹ【CANCEL_SKIP】忽略 -2011：已不在 open 列表(可能已触发/已撤): algoId={algoId}")
                    return
            except Exception as e2:
                print(f"⚠【CANCEL_CHECK_AFTER_FAIL】检查失败: {e2}")

        print(f"⚠【CANCEL_FAIL】algoId={algoId} clientAlgoId={clientAlgoId} err={e}")

async def _cancel_tp_sl_async(symbol, position_side, cancel_sl=True, cancel_tp=True):
    types_to_cancel = []
    if cancel_sl:
        types_to_cancel += TP_SL_TYPES["sl"]
    if cancel_tp:
        types_to_cancel += TP_SL_TYPES["tp"]
    if not types_to_cancel:
        return

    # print(
        # f"\n♻【CANCEL_BEGIN】symbol={symbol} positionSide={position_side} "
        # f"cancel_sl={cancel_sl} cancel_tp={cancel_tp} types={types_to_cancel}"
    # )

    tasks = []

    # 1) 基础挂单（保留兼容）
    try:
        open_orders = await async_to_thread(client.futures_get_open_orders, symbol=symbol)
    except Exception as e:
        print(f"⚠ 获取基础挂单失败: {e}")
        open_orders = []

    seen_ids = set()
    for o in open_orders:
        if (
            o.get("positionSide") == position_side
            and o.get("type") in types_to_cancel
            and o.get("status") in ["NEW", "PARTIALLY_FILLED"]
        ):
            oid = o.get("orderId")
            if oid and oid not in seen_ids:
                seen_ids.add(oid)
                tasks.append(async_to_thread(client.futures_cancel_order, symbol=symbol, orderId=oid))

    # 2) Algo 条件单：全量拉取再本地过滤（你已验证必须这样做）
    try:
        algo_orders_all = await async_to_thread(client.futures_get_open_algo_orders)
        algo_orders = [o for o in algo_orders_all if o.get("symbol") == symbol]
    except Exception as e:
        print(f"⚠ 获取条件单(openAlgoOrders)失败: {e}")
        algo_orders = []

    seen_algo = set()
    for o in algo_orders:
        if (
            o.get("positionSide") == position_side
            and o.get("orderType") in types_to_cancel
            and o.get("algoStatus") in ["NEW"]
        ):
            key = (o.get("symbol"), o.get("algoId"), o.get("clientAlgoId"))
            if key in seen_algo:
                continue
            seen_algo.add(key)

            tasks.append(cancel_algo_order_async(
                symbol=o.get("symbol"),  # ✅ 用订单自身 symbol
                algoId=o.get("algoId"),
                clientAlgoId=o.get("clientAlgoId")
            ))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def _place_tp_sl_async(symbol, position_side, sl=None, tp=None):
    results = []
    tasks = []

    # ✅ 注意：closePosition 条件单的返回里 timeInForce 可能是 GTE_GTC，属于交易所内部实现
    # ✅ 不要用 timeInForce/quantity 判断有效性，应该看 algoStatus/orderType/triggerPrice

    if sl:
        sl_val = await normalize_price_async(symbol, float(sl))

        async def place_sl():
            try:
                order = await async_to_thread(
                    client.futures_create_algo_order,
                    algoType="CONDITIONAL",
                    symbol=symbol,
                    side="SELL" if position_side == "LONG" else "BUY",
                    positionSide=position_side,
                    type="STOP_MARKET",
                    triggerPrice=str(sl_val),
                    closePosition="true",
                    workingType="MARK_PRICE",
                    timeInForce="GTC",
                    newOrderRespType="RESULT"
                )
                # print(
                    # f"🛑【SL_CREATED】{symbol} {position_side} trigger={order.get('triggerPrice')} "
                    # f"algoId={order.get('algoId')} status={order.get('algoStatus')}"
                # )
                results.append(order)

                if order.get("algoId") is not None:
                    await _print_open_algo_sample_by_id(order.get("algoId"), symbol, "SL")

            except Exception as e:
                print(f"⚠ 止损条件单下单失败 {symbol}: {e}")

        tasks.append(place_sl())

    if tp:
        tp_val = await normalize_price_async(symbol, float(tp))

        async def place_tp():
            try:
                order = await async_to_thread(
                    client.futures_create_algo_order,
                    algoType="CONDITIONAL",
                    symbol=symbol,
                    side="SELL" if position_side == "LONG" else "BUY",
                    positionSide=position_side,
                    type="TAKE_PROFIT_MARKET",
                    triggerPrice=str(tp_val),
                    closePosition="true",
                    workingType="MARK_PRICE",
                    timeInForce="GTC",
                    newOrderRespType="RESULT"
                )
                # print(
                    # f"🎯【TP_CREATED】{symbol} {position_side} trigger={order.get('triggerPrice')} "
                    # f"algoId={order.get('algoId')} status={order.get('algoStatus')}"
                # )
                results.append(order)

                if order.get("algoId") is not None:
                    await _print_open_algo_sample_by_id(order.get("algoId"), symbol, "TP")

            except Exception as e:
                print(f"⚠ 止盈条件单下单失败 {symbol}: {e}")

        tasks.append(place_tp())

    if tasks:
        await asyncio.gather(*tasks)
    return results

async def _update_tp_sl_async(symbol, position_side, sl=None, tp=None, current_price=None):
    # --- 在取消旧单之前做校验 ---

    if sl is not None:
        current_sl, _ = await get_current_sl_tp_async(symbol, position_side)
        if current_sl is not None and current_price is not None:
            new_sl = float(sl)
            if not is_sl_update_valid(position_side, float(current_price), float(current_sl), new_sl):
                # print(f"⛔ 拒绝止损更新：{symbol} {position_side} current_sl={current_sl} new_sl={new_sl} price={current_price}")
                return None

    if tp is not None:
        _, current_tp = await get_current_sl_tp_async(symbol, position_side)
        if current_tp is not None and current_price is not None:
            new_tp = float(tp)
            if not is_tp_update_valid(position_side, float(current_price), float(current_tp), new_tp):
                # print(f"⛔ 拒绝止盈更新：{symbol} {position_side} current_tp={current_tp} new_tp={new_tp} price={current_price}")
                return None

    await _cancel_tp_sl_async(symbol, position_side, cancel_sl=bool(sl), cancel_tp=bool(tp))
    return await _place_tp_sl_async(symbol, position_side, sl, tp)

# -----------------------------
# 主交易执行异步版
# -----------------------------
async def execute_trade_async(symbol: str, action: str, stop_loss=None, take_profit=None,
                              quantity=None, position_size=None, order_type=None, entry=None):
    """
    order_type: "market" (默认) 或 "limit"
    entry: 限价单入场价格 (order_type="limit" 时必须)
    """
    log_trade(symbol, action, f"开始执行 | SL={stop_loss} TP={take_profit} size={position_size}")
    try:
        acc = get_account_status()
        pos = next((p for p in acc["positions"] if p["symbol"] == symbol), None)
        mark = float(pos["mark_price"]) if pos else float((await async_to_thread(client.futures_mark_price, symbol=symbol))["markPrice"])

        # 确定订单类型
        # 如果 action 本身就是 _limit 后缀，或者 order_type=limit，都视为限价单
        is_limit_action = action.endswith("_limit")
        use_limit = is_limit_action or (order_type and order_type.lower() == "limit" and entry is not None)
        exec_price = float(entry) if (use_limit and entry) else mark

        qty = None
        if position_size:
            qty = float(position_size) / exec_price
        elif quantity:
            qty = float(quantity)
        elif action in ["open_long", "open_short", "open_long_market", "open_short_market", 
                        "open_long_limit", "open_short_limit", "increase_position"]:
            log_error(f"⚠ {symbol} 缺少 position_size 或 quantity")
            return None

        if qty:
            qty = await normalize_qty_async(symbol, qty)
            log_info(f"ℹ {symbol} 最终下单数量: {qty}, {'限价' if use_limit else '市价'}: {exec_price}")

        current = abs(pos["size"]) if pos else 0

        async def place_order(is_open=False, is_close=False, position_side=None, **kwargs):
            order = await async_to_thread(client.futures_create_order, **kwargs)
            order_id = order.get("orderId")
            order_status = order.get("status")
            
            # 记录订单结果
            log_info(f"📋 {symbol} 订单结果: orderId={order_id}, status={order_status}")
            
            # 获取实际手续费（从成交记录中获取）
            order_fee = 0
            if order_id:
                try:
                    await asyncio.sleep(0.5)  # 等待成交记录生成
                    trades = await async_to_thread(
                        client.futures_account_trades,
                        symbol=kwargs.get("symbol"),
                        orderId=order_id
                    )
                    for t in trades:
                        order_fee += float(t.get("commission", 0))
                except Exception as e:
                    log_error(f"⚠️ 获取手续费失败: {e}")
            
            # 保存简单记录（保持兼容）
            # 市价单使用实际成交价（如果有）
            actual_price = float(order.get("avgPrice", 0)) if order.get("avgPrice") else exec_price
            if actual_price == 0:
                actual_price = exec_price
            
            # 判断是否是限价单（status=NEW 表示挂单中，未成交）
            is_limit_order = order.get("status") == "NEW" and kwargs.get("type") == "LIMIT"
            
            save_trade_record({
                "symbol": symbol,
                "action": action,
                "order": kwargs,
                "order_type": "limit" if use_limit else "market",
                "price": actual_price,
                "quantity": kwargs.get("quantity"),
                "status": order.get("status"),
                "timestamp": int(time.time()),
                "pnl": 0,
                "fee": order_fee
            })
            
            # 交易追踪：开仓记录
            # 注意：限价单未成交时不记录，避免被误判为自动平仓
            if is_open and position_side and not is_limit_order:
                record_open_trade(
                    symbol=symbol,
                    side=position_side,
                    entry_price=actual_price,  # 使用实际成交价
                    quantity=float(kwargs.get("quantity", 0)),
                    order_type="limit" if use_limit else "market",
                    fee=order_fee,
                    leverage=pos.get("leverage", 1) if pos else 1
                )
            
            # 交易追踪：平仓记录
            if is_close and position_side:
                completed = record_close_trade(
                    symbol=symbol,
                    side=position_side,
                    exit_price=actual_price,  # 使用实际成交价
                    exit_quantity=float(kwargs.get("quantity", 0)),
                    close_type="limit" if use_limit else "market",
                    fee=order_fee
                )
                if completed:
                    log_trade(symbol, "CLOSED", f"{position_side} 净收益: {completed.get('net_pnl', 0):.2f} USDT")
            
            return order

        if action == "open_long" or action == "open_long_market":
            # 做多（支持市价和限价）
            if use_limit:
                # 限价做多
                limit_price = await normalize_price_async(symbol, entry if entry else exec_price)
                order = await place_order(is_open=True, position_side="LONG",
                                          symbol=symbol, side="BUY", positionSide="LONG",
                                          type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
                # 记录限价单，用于超时检查
                if order and order.get("orderId"):
                    record_limit_order(symbol, order.get("orderId"), "BUY", "LONG", limit_price, qty)
                return order
            else:
                # 市价做多
                order = await place_order(is_open=True, position_side="LONG",
                                          symbol=symbol, side="BUY", positionSide="LONG",
                                          type="MARKET", quantity=qty)
                await _update_tp_sl_async(symbol, "LONG", sl=stop_loss, tp=take_profit, current_price=exec_price)
                return order

        elif action == "open_long_limit":
            # 限价做多（挂单等回踩）- 保留兼容
            limit_price = await normalize_price_async(symbol, entry if entry else exec_price)
            order = await place_order(is_open=True, position_side="LONG",
                                      symbol=symbol, side="BUY", positionSide="LONG",
                                      type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
            # 记录限价单，用于超时检查
            if order and order.get("orderId"):
                record_limit_order(symbol, order.get("orderId"), "BUY", "LONG", limit_price, qty)
            return order

        elif action == "open_short" or action == "open_short_market":
            # 做空（支持市价和限价）
            if use_limit:
                # 限价做空
                limit_price = await normalize_price_async(symbol, entry if entry else exec_price)
                order = await place_order(is_open=True, position_side="SHORT",
                                          symbol=symbol, side="SELL", positionSide="SHORT",
                                          type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
                # 记录限价单，用于超时检查
                if order and order.get("orderId"):
                    record_limit_order(symbol, order.get("orderId"), "SELL", "SHORT", limit_price, qty)
                return order
            else:
                # 市价做空
                order = await place_order(is_open=True, position_side="SHORT",
                                          symbol=symbol, side="SELL", positionSide="SHORT",
                                          type="MARKET", quantity=qty)
                await _update_tp_sl_async(symbol, "SHORT", sl=stop_loss, tp=take_profit, current_price=exec_price)
                return order

        elif action == "open_short_limit":
            # 限价做空（挂单等反弹）- 保留兼容
            limit_price = await normalize_price_async(symbol, entry if entry else exec_price)
            order = await place_order(is_open=True, position_side="SHORT",
                                      symbol=symbol, side="SELL", positionSide="SHORT",
                                      type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
            # 记录限价单，用于超时检查
            if order and order.get("orderId"):
                record_limit_order(symbol, order.get("orderId"), "SELL", "SHORT", limit_price, qty)
            return order

        elif action == "close_long":
            if not pos or pos["size"] <= 0:
                log_error(f"⚠️ close_long 失败: pos={pos}, 无法平仓")
                return None
            log_info(f"📤 close_long 执行: {symbol} 数量={current}")
            return await place_order(is_close=True, position_side="LONG",
                                     symbol=symbol, side="SELL", positionSide="LONG", type="MARKET", quantity=current)

        elif action == "close_short":
            if not pos or pos["size"] >= 0:
                log_error(f"⚠️ close_short 失败: pos={pos}, 无法平仓")
                return None
            log_info(f"📤 close_short 执行: {symbol} 数量={current}")
            return await place_order(is_close=True, position_side="SHORT",
                                     symbol=symbol, side="BUY", positionSide="SHORT", type="MARKET", quantity=current)

        elif action == "reverse":
            if not pos or current <= 0:
                return None
            if pos["size"] > 0:
                await place_order(is_close=True, position_side="LONG",
                                  symbol=symbol, side="SELL", positionSide="LONG", type="MARKET", quantity=current)
                if use_limit:
                    limit_price = await normalize_price_async(symbol, exec_price)
                    order = await place_order(is_open=True, position_side="SHORT",
                                              symbol=symbol, side="SELL", positionSide="SHORT",
                                              type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
                else:
                    order = await place_order(is_open=True, position_side="SHORT",
                                              symbol=symbol, side="SELL", positionSide="SHORT", type="MARKET", quantity=qty)
                await _update_tp_sl_async(symbol, "SHORT", sl=stop_loss, tp=take_profit, current_price=exec_price)
                return order
            else:
                await place_order(is_close=True, position_side="SHORT",
                                  symbol=symbol, side="BUY", positionSide="SHORT", type="MARKET", quantity=current)
                if use_limit:
                    limit_price = await normalize_price_async(symbol, exec_price)
                    order = await place_order(is_open=True, position_side="LONG",
                                              symbol=symbol, side="BUY", positionSide="LONG",
                                              type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
                else:
                    order = await place_order(is_open=True, position_side="LONG",
                                              symbol=symbol, side="BUY", positionSide="LONG", type="MARKET", quantity=qty)
                await _update_tp_sl_async(symbol, "LONG", sl=stop_loss, tp=take_profit, current_price=exec_price)
                return order

        elif action == "increase_position":
            if not qty:
                print(f"⚠ {symbol} increase_position 缺少下单数量")
                return None
            if pos["size"] > 0:
                if use_limit:
                    limit_price = await normalize_price_async(symbol, exec_price)
                    return await place_order(symbol=symbol, side="BUY", positionSide="LONG",
                                             type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
                return await place_order(symbol=symbol, side="BUY", positionSide="LONG", type="MARKET", quantity=qty)
            elif pos["size"] < 0:
                if use_limit:
                    limit_price = await normalize_price_async(symbol, exec_price)
                    return await place_order(symbol=symbol, side="SELL", positionSide="SHORT",
                                             type="LIMIT", quantity=qty, price=limit_price, timeInForce="GTC")
                return await place_order(symbol=symbol, side="SELL", positionSide="SHORT", type="MARKET", quantity=qty)

        elif action == "decrease_position":
            if not pos:
                return None
            reduce_qty = qty if qty else current / 2
            reduce_qty = min(reduce_qty, current)
            if pos["size"] > 0:
                return await place_order(symbol=symbol, side="SELL", positionSide="LONG", type="MARKET", quantity=reduce_qty)
            elif pos["size"] < 0:
                return await place_order(symbol=symbol, side="BUY", positionSide="SHORT", type="MARKET", quantity=reduce_qty)

        elif action == "update_stop_loss":
            if pos:
                side = "LONG" if pos["size"] > 0 else "SHORT"
                return await _update_tp_sl_async(symbol, side, sl=stop_loss, tp=None, current_price=mark)
            return None

        elif action == "update_take_profit":
            if pos:
                side = "LONG" if pos["size"] > 0 else "SHORT"
                return await _update_tp_sl_async(symbol, side, sl=None, tp=take_profit, current_price=mark)
            return None

        else:
            print(f"⚠ 未识别动作: {action}")
            return None

    except BinanceAPIException as e:
        print(f"❌ Binance 下单异常 → {symbol}: {e}")
        return None
    except Exception as e:
        print(f"❌ 其他异常 → {symbol}: {e}")
        return None
