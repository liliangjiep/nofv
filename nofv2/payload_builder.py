"""
Payload 构建器 - 裁判系统和统一数据保存
"""
import json
from database import redis_client


def referee_snapshot(tf4h_snap: dict, tf1h_snap: dict, tf15m_ind: dict) -> dict:
    """
    裁判系统：根据多周期数据判断是否允许交易
    
    返回:
    {
        "verdict": "ALLOW_TRADE" | "NO_TRADE",
        "reason_code": "PASSED" | "15M_NO_TRIGGER" | "1H_CHOCH_TRANSITION" | ...,
        "context": {...}
    }
    """
    # 默认不允许交易
    verdict = "NO_TRADE"
    reason_code = "UNKNOWN"
    strategy_type = None
    
    # 提取各周期数据
    tf4h_trend = "unknown"
    tf4h_location = "unknown"
    tf4h_pos = 0.5
    
    tf1h_trend = "unknown"
    tf1h_break = "none"
    
    tf15m_signal = tf15m_ind.get("signal", "none")
    tf15m_trend = "unknown"
    
    # 4H 数据
    if tf4h_snap:
        struct_4h = tf4h_snap.get("structure", {})
        tf4h_trend = struct_4h.get("trend", "unknown")
        tf4h_location = tf4h_snap.get("range_location", "unknown")
        tf4h_pos = tf4h_snap.get("range_pos", 0.5)
    
    # 1H 数据
    if tf1h_snap:
        struct_1h = tf1h_snap.get("structure", {})
        tf1h_trend = struct_1h.get("trend", "unknown")
        tf1h_break = struct_1h.get("last_break", "none")
    
    # 15M 数据
    struct_15m = tf15m_ind.get("structure_summary", {})
    if struct_15m:
        tf15m_trend = struct_15m.get("trend", "unknown")
    
    context = {
        "4h_trend": tf4h_trend,
        "4h_location": tf4h_location,
        "4h_pos": tf4h_pos,
        "1h_trend": tf1h_trend,
        "1h_break": tf1h_break,
        "15m_signal": tf15m_signal,
        "15m_trend": tf15m_trend
    }
    
    # 裁判逻辑
    # 1. 15M 必须有信号
    if tf15m_signal == "none":
        reason_code = "15M_NO_TRIGGER"
        return {"verdict": verdict, "reason_code": reason_code, "context": context}
    
    # 2. 1H 处于 CHOCH 过渡期
    if tf1h_break in ("choch_up", "choch_down"):
        reason_code = "1H_CHOCH_TRANSITION"
        return {"verdict": verdict, "reason_code": reason_code, "context": context}
    
    # 3. 4H 趋势与 15M 信号方向冲突
    if tf4h_trend == "down" and tf15m_signal == "break_confirmed" and tf15m_trend == "up":
        reason_code = "4H_TREND_CONFLICT"
        return {"verdict": verdict, "reason_code": reason_code, "context": context}
    
    if tf4h_trend == "up" and tf15m_signal == "break_confirmed" and tf15m_trend == "down":
        reason_code = "4H_TREND_CONFLICT"
        return {"verdict": verdict, "reason_code": reason_code, "context": context}
    
    # 4. 通过所有检查，允许交易
    verdict = "ALLOW_TRADE"
    reason_code = "PASSED"
    strategy_type = "trend_pullback"
    
    result = {"verdict": verdict, "reason_code": reason_code, "context": context}
    if strategy_type:
        result["strategy_type"] = strategy_type
    
    return result


def save_unified_payload(symbol: str) -> dict:
    """
    保存统一的 payload 到 Redis
    """
    try:
        # 获取各周期快照
        tf4h_raw = redis_client.get(f"signal_snapshot:{symbol}:4h")
        tf1h_raw = redis_client.get(f"signal_snapshot:{symbol}:1h")
        tf15m_raw = redis_client.get(f"signal_snapshot:{symbol}:15m")
        
        tf4h = json.loads(tf4h_raw) if tf4h_raw else None
        tf1h = json.loads(tf1h_raw) if tf1h_raw else None
        tf15m = json.loads(tf15m_raw) if tf15m_raw else None
        
        if not tf15m:
            return None
        
        # 构建 unified payload
        payload = {
            "symbol": symbol,
            "tf4h": tf4h,
            "tf1h": tf1h,
            "tf15m": tf15m,
            "referee": tf15m.get("referee", {})
        }
        
        # 保存到 Redis
        redis_client.set(f"unified_payload:{symbol}", json.dumps(payload))
        
        return payload
        
    except Exception as e:
        print(f"⚠️ save_unified_payload 失败 {symbol}: {e}")
        return None
