# global_context.py
"""
全局上下文模块 - 提供市场情绪、账户风险、机会排名等
对标投喂数据中的 global_context 结构
"""
import json
from typing import Optional, Dict, List, Any
from database import redis_client
from account_positions import account_snapshot


def get_tf_snapshot(symbol: str, tf: str) -> Optional[dict]:
    """获取指定周期的快照数据"""
    try:
        v = redis_client.get(f"signal_snapshot:{symbol}:{tf}")
        return json.loads(v) if v else None
    except Exception:
        return None


def get_unified_payload(symbol: str) -> Optional[dict]:
    """获取统一payload"""
    try:
        v = redis_client.get(f"unified_payload:{symbol}")
        return json.loads(v) if v else None
    except Exception:
        return None


def calc_market_regime(symbols: List[str]) -> dict:
    """
    计算市场制度
    - BTC/ETH 趋势
    - 市场情绪
    - 风险偏好
    """
    btc_trend = "unknown"
    eth_trend = "unknown"
    bullish_count = 0
    bearish_count = 0
    total_analyzed = 0
    
    # BTC 趋势
    btc_4h = get_tf_snapshot("BTCUSDT", "4h")
    if btc_4h and btc_4h.get("structure", {}).get("valid"):
        btc_trend = btc_4h["structure"].get("trend", "range")
    
    # ETH 趋势
    eth_4h = get_tf_snapshot("ETHUSDT", "4h")
    if eth_4h and eth_4h.get("structure", {}).get("valid"):
        eth_trend = eth_4h["structure"].get("trend", "range")
    
    # 统计所有币种的趋势
    for symbol in symbols:
        tf4h = get_tf_snapshot(symbol, "4h")
        if not tf4h or not tf4h.get("structure", {}).get("valid"):
            continue
        
        total_analyzed += 1
        trend = tf4h["structure"].get("trend")
        bias = tf4h["structure"].get("bias", 0)
        
        if trend == "up" or bias > 0:
            bullish_count += 1
        elif trend == "down" or bias < 0:
            bearish_count += 1
    
    # 计算看涨比例
    bullish_ratio = bullish_count / total_analyzed if total_analyzed > 0 else 0.5
    
    # 市场情绪
    if bullish_ratio >= 0.7:
        sentiment = "strong_bullish"
    elif bullish_ratio >= 0.55:
        sentiment = "bullish"
    elif bullish_ratio <= 0.3:
        sentiment = "strong_bearish"
    elif bullish_ratio <= 0.45:
        sentiment = "bearish"
    else:
        sentiment = "neutral"
    
    # 风险偏好
    if sentiment in ("strong_bullish", "bullish") and btc_trend == "up":
        risk_appetite = "risk_on"
    elif sentiment in ("strong_bearish", "bearish") and btc_trend == "down":
        risk_appetite = "risk_off"
    else:
        risk_appetite = "neutral"
    
    return {
        "btc_trend": btc_trend,
        "eth_trend": eth_trend,
        "market_sentiment": sentiment,
        "bullish_ratio": round(bullish_ratio, 2),
        "risk_appetite": risk_appetite,
        "symbols_analyzed": total_analyzed
    }


def calc_account_risk() -> dict:
    """
    计算账户风险
    - 总敞口
    - 敞口比例
    - 风险状态
    """
    balance = account_snapshot.get("balance", 0)
    available = account_snapshot.get("available", 0)
    positions = account_snapshot.get("positions", [])
    
    if balance <= 0:
        return {"available": False}
    
    # 计算持仓敞口
    long_exposure = 0
    short_exposure = 0
    position_count = 0
    
    for p in positions:
        size = float(p.get("size", 0))
        entry = float(p.get("entry", 0))
        leverage = int(p.get("leverage", 1))
        
        position_value = abs(size) * entry
        
        if size > 0:
            long_exposure += position_value
        else:
            short_exposure += position_value
        
        position_count += 1
    
    total_exposure = long_exposure + short_exposure
    exposure_ratio = total_exposure / balance if balance > 0 else 0
    
    # 剩余容量
    remaining_capacity = available * 30  # 假设最大30倍杠杆
    
    # 风险状态
    if exposure_ratio >= 0.8:
        risk_status = "high"
    elif exposure_ratio >= 0.5:
        risk_status = "medium"
    else:
        risk_status = "low"
    
    return {
        "available": True,
        "total_exposure": round(total_exposure, 2),
        "exposure_ratio": round(exposure_ratio, 2),
        "position_exposure": round(total_exposure, 2),
        "order_exposure": 0,  # 暂不计算挂单敞口
        "long_exposure": round(long_exposure, 2),
        "short_exposure": round(short_exposure, 2),
        "remaining_capacity": round(remaining_capacity, 2),
        "risk_status": risk_status,
        "position_count": position_count,
        "order_count": 0
    }


def calc_opportunity_ranking(symbols: List[str]) -> dict:
    """
    计算机会排名
    - 根据裁判结果、偏向强度、反转风险等综合评分
    """
    rankings = []
    allow_count = 0
    good_count = 0
    
    for symbol in symbols:
        payload = get_unified_payload(symbol)
        tf15m = get_tf_snapshot(symbol, "15m")
        tf4h = get_tf_snapshot(symbol, "4h")
        
        if not tf15m:
            continue
        
        score = 0
        factors = []
        verdict = "NO_TRADE"
        bias_direction = "neutral"
        
        # 裁判结果
        if payload:
            referee = payload.get("referee", {})
            verdict = referee.get("verdict", "NO_TRADE")
            
            if verdict == "ALLOW_TRADE":
                score += 3
                factors.append("referee_allow")
                allow_count += 1
        
        # AI增强数据（如果有）
        ai_enh = tf15m.get("ai_enhancement", {})
        overall_bias = ai_enh.get("overall_bias", {})
        
        if overall_bias:
            bias_direction = overall_bias.get("bias_direction", "neutral")
            bias_strength = overall_bias.get("bias_strength", "none")
            reversal_risk = overall_bias.get("reversal_risk", "low")
            
            if bias_strength == "strong":
                score += 2
                factors.append("strong_bias")
            elif bias_strength == "moderate":
                score += 1
                factors.append("moderate_bias")
            
            if reversal_risk == "low":
                score += 1
                factors.append("low_reversal_risk")
        
        # 位置评分
        range_loc = tf15m.get("range_location", "middle")
        if range_loc in ("near_low", "near_high"):
            score += 1
            factors.append("at_key_level")
        elif range_loc in ("above_range", "below_range"):
            factors.append("out_of_range")
        else:
            factors.append("near_key_level")
        
        # Order flow
        order_flow = ai_enh.get("order_flow", {})
        if order_flow.get("available"):
            last_5 = order_flow.get("last_5_bars", {})
            bias = last_5.get("bias", "neutral")
            if bias in ("strong_buy_pressure", "strong_sell_pressure"):
                score += 1
                factors.append("strong_order_flow")
        
        # 成交量
        vol_analysis = order_flow.get("volume_analysis", {}) if order_flow else {}
        if vol_analysis.get("is_volume_spike"):
            score += 1
            factors.append("volume_spike")
        
        # 潜在设置的风险回报
        setups = ai_enh.get("potential_setups", {})
        long_setup = setups.get("long_at_support", {})
        short_setup = setups.get("short_at_resistance", {})
        
        best_rr = max(
            long_setup.get("risk_reward", 0) if long_setup else 0,
            short_setup.get("risk_reward", 0) if short_setup else 0
        )
        if best_rr >= 2:
            score += 1
            factors.append("good_risk_reward")
        
        if score >= 4:
            good_count += 1
        
        rankings.append({
            "symbol": symbol,
            "score": score,
            "factors": factors,
            "verdict": verdict,
            "bias_direction": bias_direction
        })
    
    # 按分数排序
    rankings.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "ranking": rankings[:10],  # 只返回前10
        "top_count": allow_count,
        "good_count": good_count,
        "total_analyzed": len(rankings)
    }


def calc_position_distribution() -> dict:
    """
    计算持仓分布
    """
    positions = account_snapshot.get("positions", [])
    
    if not positions:
        return {
            "has_positions": False,
            "long_count": 0,
            "short_count": 0,
            "long_positions": [],
            "short_positions": [],
            "net_direction": "balanced"
        }
    
    long_positions = []
    short_positions = []
    
    for p in positions:
        size = float(p.get("size", 0))
        symbol = p.get("symbol", "")
        
        if size > 0:
            long_positions.append(symbol)
        else:
            short_positions.append(symbol)
    
    long_count = len(long_positions)
    short_count = len(short_positions)
    
    if long_count > short_count + 1:
        net_direction = "net_long"
    elif short_count > long_count + 1:
        net_direction = "net_short"
    else:
        net_direction = "balanced"
    
    return {
        "has_positions": True,
        "long_count": long_count,
        "short_count": short_count,
        "long_positions": long_positions,
        "short_positions": short_positions,
        "net_direction": net_direction
    }


def build_global_context(symbols: List[str]) -> dict:
    """
    构建完整的全局上下文
    对标投喂数据中的 global_context 结构
    """
    return {
        "market_regime": calc_market_regime(symbols),
        "account_risk": calc_account_risk(),
        "opportunity_ranking": calc_opportunity_ranking(symbols),
        "position_distribution": calc_position_distribution()
    }


def get_open_limit_orders() -> List[dict]:
    """
    获取当前挂单列表
    TODO: 从交易所API获取
    """
    # 暂时返回空列表，后续可以从 account_positions 扩展
    return []
