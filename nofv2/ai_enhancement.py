# ai_enhancement.py
"""
AI增强模块 - 提供多周期技术分析、买卖压力、关键位、潜在交易设置等
对标投喂数据中的 ai_enhancement 结构
"""
import json
import numpy as np
import talib
from typing import Optional, Dict, List, Any
from database import redis_client


def get_tf_snapshot(symbol: str, tf: str) -> Optional[dict]:
    """获取指定周期的快照数据"""
    try:
        v = redis_client.get(f"signal_snapshot:{symbol}:{tf}")
        return json.loads(v) if v else None
    except Exception:
        return None


def get_klines_from_redis(symbol: str, interval: str, limit: int = 50) -> List[dict]:
    """从Redis获取K线数据"""
    rkey = f"historical_data:{symbol}:{interval}"
    data = redis_client.hgetall(rkey)
    if not data:
        return []
    
    rows = sorted(data.items(), key=lambda x: int(x[0]))
    rows = [{"Timestamp": int(ts), **json.loads(v)} for ts, v in rows]
    return rows[-limit:] if len(rows) > limit else rows


def calc_ema_slope(ema_series: np.ndarray, lookback: int = 5) -> str:
    """计算EMA斜率方向"""
    if ema_series is None or len(ema_series) < lookback + 1:
        return "unknown"
    
    valid = ema_series[np.isfinite(ema_series)]
    if len(valid) < lookback + 1:
        return "unknown"
    
    recent = valid[-lookback:]
    diff = recent[-1] - recent[0]
    pct_change = abs(diff / recent[0]) if recent[0] != 0 else 0
    
    if pct_change < 0.001:  # 0.1% 以内视为平
        return "flat"
    return "rising" if diff > 0 else "falling"


def calc_trend_strength(adx_value: float) -> str:
    """根据ADX判断趋势强度"""
    if adx_value is None:
        return "unknown"
    if adx_value >= 40:
        return "strong"
    if adx_value >= 25:
        return "moderate"
    if adx_value >= 15:
        return "weak"
    return "none"


def calc_trend_quality(adx: float, di_plus: float, di_minus: float) -> str:
    """趋势质量：ADX + DI 方向一致性"""
    if adx is None or di_plus is None or di_minus is None:
        return "unknown"
    
    di_diff = abs(di_plus - di_minus)
    if adx >= 25 and di_diff >= 10:
        return "good"
    if adx >= 20 and di_diff >= 5:
        return "moderate"
    return "poor"


def calc_momentum_state(rsi: float) -> str:
    """动量状态"""
    if rsi is None:
        return "unknown"
    if rsi >= 70:
        return "overbought"
    if rsi <= 30:
        return "oversold"
    if rsi >= 55:
        return "bullish"
    if rsi <= 45:
        return "bearish"
    return "neutral"


def calc_di_direction(di_plus: float, di_minus: float) -> str:
    """DI方向"""
    if di_plus is None or di_minus is None:
        return "unknown"
    diff = di_plus - di_minus
    if abs(diff) < 3:
        return "neutral"
    return "bullish" if diff > 0 else "bearish"


def calc_continuation_prob(trend: str, adx: float, di_plus: float, di_minus: float) -> str:
    """趋势延续概率"""
    if trend == "range":
        return "low"
    if adx is None:
        return "unknown"
    
    # 趋势方向与DI一致性
    if trend == "up" and di_plus is not None and di_minus is not None:
        if di_plus > di_minus and adx >= 25:
            return "high" if adx >= 35 else "medium"
    elif trend == "down" and di_plus is not None and di_minus is not None:
        if di_minus > di_plus and adx >= 25:
            return "high" if adx >= 35 else "medium"
    
    return "low"


def calc_exhaustion_signal(rsi: float, adx: float, trend: str) -> str:
    """疲劳信号检测"""
    if rsi is None or adx is None:
        return "none"
    
    # 上涨趋势中RSI超买 + ADX开始回落
    if trend == "up" and rsi >= 70:
        return "early" if adx >= 30 else "none"
    
    # 下跌趋势中RSI超卖 + ADX开始回落
    if trend == "down" and rsi <= 30:
        return "early" if adx >= 30 else "none"
    
    return "none"


def calc_volatility_state(atr_ratio: float, atr_ma_ratio: float = None) -> str:
    """波动率状态"""
    if atr_ratio is None:
        return "unknown"
    
    if atr_ratio >= 0.03:
        return "expanding"
    if atr_ratio <= 0.01:
        return "contracting"
    return "normal"


def calc_price_location(close: float, range_high: float, range_low: float) -> str:
    """价格位置：premium/value/discount"""
    if range_high is None or range_low is None or range_high <= range_low:
        return "unknown"
    
    range_size = range_high - range_low
    pos = (close - range_low) / range_size
    
    if pos >= 0.7:
        return "premium"
    if pos <= 0.3:
        return "discount"
    return "value"


def calc_structure_state(trend: str, last_break: str, range_pos: float) -> str:
    """结构状态"""
    if trend == "up":
        if last_break == "bos_up":
            return "impulse_up"
        if last_break in ("choch_down", "choch_up"):
            return "pullback_down"
        return "consolidation"
    
    if trend == "down":
        if last_break == "bos_down":
            return "impulse_down"
        if last_break in ("choch_up", "choch_down"):
            return "pullback_up"
        return "consolidation"
    
    return "consolidation"


def calc_trade_space(atr: float, close: float) -> str:
    """交易空间"""
    if atr is None or close is None or close == 0:
        return "unknown"
    
    atr_pct = atr / close
    if atr_pct >= 0.02:
        return "wide"
    if atr_pct <= 0.005:
        return "tight"
    return "normal"


def calc_key_level_status(close: float, levels: dict, threshold_pct: float = 0.5) -> tuple:
    """检测是否接近关键位"""
    if not levels or close is None:
        return "none", None
    
    for level_name, level_price in levels.items():
        if level_price is None or level_price == 0:
            continue
        
        distance_pct = abs(close - level_price) / level_price * 100
        if distance_pct <= threshold_pct:
            level_type = "support" if close >= level_price else "resistance"
            return f"touching_{level_name}", level_type
        elif distance_pct <= 1.5:
            level_type = "support" if close >= level_price else "resistance"
            return f"near_{level_name}", level_type
    
    return "none", None


def calc_order_flow(klines: List[dict], last_n: int = 5) -> dict:
    """计算买卖压力（Order Flow）"""
    if not klines or len(klines) < last_n:
        return {"available": False}
    
    def calc_flow(bars: List[dict]) -> dict:
        total_buy = sum(float(k.get("TakerBuyVolume", 0)) for k in bars)
        total_vol = sum(float(k.get("Volume", 0)) for k in bars)
        total_sell = total_vol - total_buy
        
        delta = total_buy - total_sell
        ratio = total_buy / total_sell if total_sell > 0 else 999
        
        if ratio >= 1.2:
            bias = "strong_buy_pressure"
        elif ratio >= 1.05:
            bias = "mild_buy_pressure"
        elif ratio <= 0.8:
            bias = "strong_sell_pressure"
        elif ratio <= 0.95:
            bias = "mild_sell_pressure"
        else:
            bias = "neutral"
        
        return {
            "total_buy_volume": round(total_buy, 2),
            "total_sell_volume": round(total_sell, 2),
            "delta": round(delta, 2),
            "buy_sell_ratio": round(ratio, 4),
            "bias": bias
        }
    
    last_5 = klines[-5:]
    last_10 = klines[-10:] if len(klines) >= 10 else klines
    
    # 成交量分析
    volumes = [float(k.get("Volume", 0)) for k in klines]
    avg_vol = np.mean(volumes) if volumes else 0
    last_vol = volumes[-1] if volumes else 0
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 0
    is_spike = vol_ratio >= 2.0
    
    return {
        "available": True,
        "last_5_bars": calc_flow(last_5),
        "last_10_bars": calc_flow(last_10),
        "volume_analysis": {
            "avg_volume": round(avg_vol, 2),
            "last_bar_volume": round(last_vol, 2),
            "volume_ratio": round(vol_ratio, 2),
            "is_volume_spike": is_spike
        }
    }


def calc_volume_confirmation(order_flow: dict, trend: str) -> str:
    """成交量确认"""
    if not order_flow.get("available"):
        return "unknown"
    
    last_5 = order_flow.get("last_5_bars", {})
    bias = last_5.get("bias", "neutral")
    vol_spike = order_flow.get("volume_analysis", {}).get("is_volume_spike", False)
    
    if trend == "up":
        if bias in ("strong_buy_pressure", "mild_buy_pressure") and vol_spike:
            return "strong"
        if bias in ("strong_buy_pressure", "mild_buy_pressure"):
            return "moderate"
    elif trend == "down":
        if bias in ("strong_sell_pressure", "mild_sell_pressure") and vol_spike:
            return "strong"
        if bias in ("strong_sell_pressure", "mild_sell_pressure"):
            return "moderate"
    
    return "weak"


def calc_obv_direction(klines: List[dict]) -> str:
    """OBV方向判断"""
    if not klines or len(klines) < 10:
        return "unknown"
    
    closes = np.array([float(k["Close"]) for k in klines])
    volumes = np.array([float(k.get("Volume", 0)) for k in klines])
    
    obv = np.zeros(len(closes))
    obv[0] = volumes[0]
    
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            obv[i] = obv[i-1] + volumes[i]
        elif closes[i] < closes[i-1]:
            obv[i] = obv[i-1] - volumes[i]
        else:
            obv[i] = obv[i-1]
    
    # 比较OBV趋势与价格趋势
    price_trend = closes[-1] > closes[-5]
    obv_trend = obv[-1] > obv[-5]
    
    if price_trend == obv_trend:
        return "confirming"
    return "diverging"


def calc_micro_structure(klines: List[dict]) -> str:
    """微观结构分析"""
    if not klines or len(klines) < 5:
        return "unclear"
    
    recent = klines[-5:]
    highs = [float(k["High"]) for k in recent]
    lows = [float(k["Low"]) for k in recent]
    
    # 检查高点和低点的趋势
    higher_highs = all(highs[i] >= highs[i-1] for i in range(1, len(highs)))
    higher_lows = all(lows[i] >= lows[i-1] for i in range(1, len(lows)))
    lower_highs = all(highs[i] <= highs[i-1] for i in range(1, len(highs)))
    lower_lows = all(lows[i] <= lows[i-1] for i in range(1, len(lows)))
    
    if higher_highs and higher_lows:
        return "higher_highs_lows"
    if lower_highs and lower_lows:
        return "lower_highs_lows"
    if higher_lows and not higher_highs:
        return "higher_lows"
    if lower_highs and not lower_lows:
        return "lower_highs"
    
    # 检查压缩
    range_sizes = [highs[i] - lows[i] for i in range(len(highs))]
    if all(range_sizes[i] <= range_sizes[i-1] for i in range(1, len(range_sizes))):
        return "compression"
    
    return "unclear"


def calc_rejection_strength(klines: List[dict]) -> tuple:
    """拒绝强度（影线分析）"""
    if not klines or len(klines) < 1:
        return "none", None
    
    last = klines[-1]
    o, h, l, c = float(last["Open"]), float(last["High"]), float(last["Low"]), float(last["Close"])
    
    total = h - l
    if total == 0:
        return "none", None
    
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    
    upper_ratio = upper_wick / total
    lower_ratio = lower_wick / total
    
    # 强拒绝：影线占比超过60%
    if upper_ratio >= 0.6:
        return "strong", "bearish"
    if lower_ratio >= 0.6:
        return "strong", "bullish"
    
    # 弱拒绝：影线占比超过40%
    if upper_ratio >= 0.4:
        return "weak", "bearish"
    if lower_ratio >= 0.4:
        return "weak", "bullish"
    
    return "none", None


def calc_overall_bias(tf4h: dict, tf1h: dict, tf15m: dict) -> dict:
    """计算综合偏向"""
    bias_score = 0
    bias_factors = []
    reversal_factors = []
    trend_conflict = False
    
    # 4H 趋势
    trend_4h = tf4h.get("trend") if tf4h else None
    if trend_4h == "up":
        bias_score += 2
        bias_factors.append("4h_trend_up")
    elif trend_4h == "down":
        bias_score -= 2
        bias_factors.append("4h_trend_down")
    
    # 4H DI方向
    di_4h = tf4h.get("di_direction") if tf4h else None
    if di_4h == "bullish":
        bias_score += 1
        bias_factors.append("4h_di_bullish")
    elif di_4h == "bearish":
        bias_score -= 1
        bias_factors.append("4h_di_bearish")
    
    # 1H 价格位置
    loc_1h = tf1h.get("price_location") if tf1h else None
    if loc_1h == "discount":
        bias_score += 1
        bias_factors.append("1h_discount")
    elif loc_1h == "premium":
        bias_factors.append("1h_premium")
    
    # 15M 微观结构
    micro_15m = tf15m.get("micro_structure") if tf15m else None
    if micro_15m == "higher_highs_lows":
        bias_score += 1
        bias_factors.append("15m_bullish_structure")
    elif micro_15m in ("lower_highs_lows", "lower_highs"):
        bias_score -= 1
        bias_factors.append("15m_bearish_structure")
    
    # 检测趋势冲突
    trend_1h = tf1h.get("trend") if tf1h else None
    if trend_4h and trend_1h and trend_4h != trend_1h and trend_4h != "range" and trend_1h != "range":
        trend_conflict = True
        bias_factors.append("trend_conflict_detected")
    
    # 反转风险
    reversal_score = 0
    exhaustion_4h = tf4h.get("exhaustion_signal") if tf4h else None
    if exhaustion_4h == "early":
        reversal_score += 1
        reversal_factors.append("early_exhaustion")
    
    vol_state_1h = tf1h.get("volatility_state") if tf1h else None
    if vol_state_1h == "expanding":
        reversal_score += 1
        reversal_factors.append("expanding_stretched")
    
    # 确定偏向方向和强度
    if bias_score >= 3:
        direction, strength = "bullish", "strong"
    elif bias_score >= 1:
        direction, strength = "bullish", "moderate" if bias_score >= 2 else "weak"
    elif bias_score <= -3:
        direction, strength = "bearish", "strong"
    elif bias_score <= -1:
        direction, strength = "bearish", "moderate" if bias_score <= -2 else "weak"
    else:
        direction, strength = "neutral", "none"
    
    # 交易建议
    trade_suggestion = None
    if trend_conflict:
        if trend_4h == "up" and trend_1h == "down":
            trade_suggestion = "pullback_in_uptrend_wait_support_long"
        elif trend_4h == "down" and trend_1h == "up":
            trade_suggestion = "bounce_in_downtrend_no_short"
    
    return {
        "available": True,
        "bias_direction": direction,
        "bias_strength": strength,
        "bias_score": bias_score,
        "bias_factors": bias_factors,
        "reversal_risk": "medium" if reversal_score >= 2 else "low" if reversal_score == 1 else "low",
        "reversal_score": reversal_score,
        "reversal_factors": reversal_factors,
        "trend_conflict": trend_conflict,
        "trade_suggestion": trade_suggestion
    }


def calc_key_levels(symbol: str, current_price: float, tf4h: dict, tf1h: dict, tf15m: dict) -> dict:
    """计算关键支撑阻力位"""
    levels = {
        "current_price": current_price,
        "4h_range_high": None,
        "4h_range_low": None,
        "4h_swing_high": None,
        "4h_swing_low": None,
        "1h_swing_high": None,
        "1h_swing_low": None,
        "15m_swing_high": None,
        "15m_swing_low": None,
    }
    
    # 从各周期提取关键位
    if tf4h and tf4h.get("structure"):
        s = tf4h["structure"]
        levels["4h_range_high"] = s.get("range_high")
        levels["4h_range_low"] = s.get("range_low")
        levels["4h_swing_high"] = s.get("swing_high")
        levels["4h_swing_low"] = s.get("swing_low")
    
    if tf1h and tf1h.get("structure"):
        s = tf1h["structure"]
        levels["1h_swing_high"] = s.get("swing_high")
        levels["1h_swing_low"] = s.get("swing_low")
    
    if tf15m and tf15m.get("structure"):
        s = tf15m["structure"]
        levels["15m_swing_high"] = s.get("swing_high")
        levels["15m_swing_low"] = s.get("swing_low")
    
    # 计算最近支撑和阻力
    supports = []
    resistances = []
    
    for key, price in levels.items():
        if key == "current_price" or price is None:
            continue
        
        distance_pct = round((current_price - price) / price * 100, 3) if price != 0 else 0
        
        if price < current_price:
            supports.append({
                "level": key,
                "price": price,
                "distance_pct": round(abs(distance_pct), 3)
            })
        else:
            resistances.append({
                "level": key,
                "price": price,
                "distance_pct": round(abs(distance_pct), 3)
            })
    
    # 按距离排序
    supports.sort(key=lambda x: x["distance_pct"])
    resistances.sort(key=lambda x: x["distance_pct"])
    
    levels["nearest_supports"] = supports[:3]
    levels["nearest_resistances"] = resistances[:3]
    
    return levels


def calc_potential_setups(current_price: float, key_levels: dict, atr: float) -> dict:
    """计算潜在交易设置"""
    setups = {}
    
    supports = key_levels.get("nearest_supports", [])
    resistances = key_levels.get("nearest_resistances", [])
    
    if not atr or atr == 0:
        return {"long_at_support": None, "short_at_resistance": None}
    
    # 做多设置（在支撑位）
    if supports:
        support = supports[0]
        entry = support["price"]
        stop_loss = round(entry - atr * 1.5, 6)
        
        # 找最近的阻力作为目标
        tp1 = resistances[0]["price"] if resistances else round(entry + atr * 2, 6)
        tp2 = resistances[1]["price"] if len(resistances) > 1 else None
        
        risk = entry - stop_loss
        reward = tp1 - entry
        rr = round(reward / risk, 2) if risk > 0 else 0
        
        setups["long_at_support"] = {
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "risk_pct": round(risk / entry * 100, 3) if entry > 0 else 0,
            "risk_reward": rr,
            "distance_to_entry_pct": support["distance_pct"]
        }
    
    # 做空设置（在阻力位）
    if resistances:
        resistance = resistances[0]
        entry = resistance["price"]
        stop_loss = round(entry + atr * 1.5, 6)
        
        # 找最近的支撑作为目标
        tp1 = supports[0]["price"] if supports else round(entry - atr * 2, 6)
        tp2 = supports[1]["price"] if len(supports) > 1 else None
        
        risk = stop_loss - entry
        reward = entry - tp1
        rr = round(reward / risk, 2) if risk > 0 else 0
        
        setups["short_at_resistance"] = {
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "risk_pct": round(risk / entry * 100, 3) if entry > 0 else 0,
            "risk_reward": rr,
            "distance_to_entry_pct": resistance["distance_pct"]
        }
    
    return setups


def calc_signal_analysis(tf15m: dict, tf4h: dict) -> dict:
    """信号分析"""
    signal = tf15m.get("signal", "none") if tf15m else "none"
    last_break = tf15m.get("structure", {}).get("last_break", "none") if tf15m else "none"
    range_pos = tf15m.get("range_pos") if tf15m else None
    
    confluence_factors = []
    
    # 检查多周期对齐
    trend_4h = tf4h.get("structure", {}).get("trend") if tf4h else None
    trend_15m = tf15m.get("structure", {}).get("trend") if tf15m else None
    
    if trend_4h == trend_15m and trend_4h in ("up", "down"):
        confluence_factors.append(f"all_tf_aligned_{trend_4h}")
    elif trend_4h == "up" and trend_15m == "down":
        confluence_factors.append("1h_15m_aligned_down")
    elif trend_4h == "down" and trend_15m == "up":
        confluence_factors.append("1h_15m_aligned_up")
    
    # 检查结构突破
    if last_break == "bos_up":
        confluence_factors.append("15m_bos_up")
    elif last_break == "bos_down":
        confluence_factors.append("15m_bos_down")
    elif last_break == "choch_up":
        confluence_factors.append("15m_choch_up_reversal")
    elif last_break == "choch_down":
        confluence_factors.append("15m_choch_down_reversal")
    
    # 检查位置
    loc_4h = tf4h.get("range_location") if tf4h else None
    if loc_4h == "near_low":
        confluence_factors.append("4h_near_support")
    elif loc_4h == "near_high":
        confluence_factors.append("4h_near_resistance")
    
    # EMA对齐
    ema = tf15m.get("ema", {}) if tf15m else {}
    ema_20 = ema.get("EMA_20")
    ema_50 = ema.get("EMA_50")
    if ema_20 and ema_50 and ema_20 > ema_50:
        confluence_factors.append("ema_bullish_alignment")
    elif ema_20 and ema_50 and ema_20 < ema_50:
        confluence_factors.append("ema_bearish_alignment")
    
    # 距离触发点
    distance_to_trigger = {}
    if range_pos is not None:
        distance_to_trigger = {
            "to_near_low_0.2": round(range_pos - 0.2, 4) if range_pos > 0.2 else 0,
            "to_near_high_0.8": round(0.8 - range_pos, 4) if range_pos < 0.8 else 0,
            "current_pos": round(range_pos, 4)
        }
    
    reason = "signal_triggered" if signal != "none" else "signal_conditions_not_met"
    if signal == "none" and last_break == "none":
        reason = "no_15m_structure_break"
    
    return {
        "current_signal": signal,
        "reason": reason,
        "potential_signal": None,
        "15m_last_break": last_break,
        "distance_to_trigger": distance_to_trigger,
        "confluence_factors": confluence_factors
    }


def calc_market_context(atr_ratio: float, trend: str) -> dict:
    """市场上下文"""
    if atr_ratio is None:
        volatility = "unknown"
    elif atr_ratio >= 0.025:
        volatility = "high"
    elif atr_ratio >= 0.01:
        volatility = "medium"
    else:
        volatility = "low"
    
    market_phase = "ranging"
    if trend == "up":
        market_phase = "uptrend"
    elif trend == "down":
        market_phase = "downtrend"
    
    return {
        "volatility": volatility,
        "atr_ratio": atr_ratio,
        "market_phase": market_phase
    }


def build_tf_technicals(snapshot: dict, klines: List[dict], tf_name: str) -> dict:
    """构建单周期技术分析"""
    if not snapshot:
        return {"available": False}
    
    structure = snapshot.get("structure", {})
    trend = structure.get("trend", "range")
    atr_ratio = snapshot.get("atr_ratio")
    atr = snapshot.get("atr")
    close = snapshot.get("close")
    range_pos = snapshot.get("range_pos")
    last_break = structure.get("last_break", "none")
    
    # 计算ADX/RSI（需要K线数据）
    adx, di_plus, di_minus, rsi = None, None, None, None
    ema_slope = "unknown"
    
    if klines and len(klines) >= 20:
        highs = np.array([float(k["High"]) for k in klines])
        lows = np.array([float(k["Low"]) for k in klines])
        closes = np.array([float(k["Close"]) for k in klines])
        
        try:
            adx_arr = talib.ADX(highs, lows, closes, timeperiod=14)
            di_plus_arr = talib.PLUS_DI(highs, lows, closes, timeperiod=14)
            di_minus_arr = talib.MINUS_DI(highs, lows, closes, timeperiod=14)
            rsi_arr = talib.RSI(closes, timeperiod=14)
            ema_arr = talib.EMA(closes, timeperiod=20)
            
            adx = float(adx_arr[-1]) if np.isfinite(adx_arr[-1]) else None
            di_plus = float(di_plus_arr[-1]) if np.isfinite(di_plus_arr[-1]) else None
            di_minus = float(di_minus_arr[-1]) if np.isfinite(di_minus_arr[-1]) else None
            rsi = float(rsi_arr[-1]) if np.isfinite(rsi_arr[-1]) else None
            ema_slope = calc_ema_slope(ema_arr)
        except:
            pass
    
    # 4H 特有字段
    if tf_name == "4h":
        return {
            "available": True,
            "trend_direction": trend,
            "trend_strength": calc_trend_strength(adx),
            "trend_quality": calc_trend_quality(adx, di_plus, di_minus),
            "continuation_prob": calc_continuation_prob(trend, adx, di_plus, di_minus),
            "exhaustion_signal": calc_exhaustion_signal(rsi, adx, trend),
            "momentum_state": calc_momentum_state(rsi),
            "di_direction": calc_di_direction(di_plus, di_minus),
            "ema_slope": ema_slope
        }
    
    # 1H 特有字段
    if tf_name == "1h":
        range_high = structure.get("range_high")
        range_low = structure.get("range_low")
        
        return {
            "available": True,
            "volatility_state": calc_volatility_state(atr_ratio),
            "price_location": calc_price_location(close, range_high, range_low) if close else "unknown",
            "structure_state": calc_structure_state(trend, last_break, range_pos),
            "trade_space": calc_trade_space(atr, close),
            "consolidation": trend == "range",
            "breakout_status": "none"
        }
    
    # 15M 特有字段
    if tf_name == "15m":
        # 关键位检测
        levels_to_check = {}
        tf4h = get_tf_snapshot(snapshot.get("symbol", ""), "4h")
        tf1h = get_tf_snapshot(snapshot.get("symbol", ""), "1h")
        
        if tf1h and tf1h.get("structure"):
            levels_to_check["1h_swing_high"] = tf1h["structure"].get("swing_high")
            levels_to_check["1h_swing_low"] = tf1h["structure"].get("swing_low")
        
        levels_to_check["15m_swing_high"] = structure.get("swing_high")
        levels_to_check["15m_swing_low"] = structure.get("swing_low")
        
        key_status, key_type = calc_key_level_status(close, levels_to_check) if close else ("none", None)
        
        # Order flow
        order_flow = calc_order_flow(klines)
        vol_confirm = calc_volume_confirmation(order_flow, trend)
        obv_dir = calc_obv_direction(klines)
        micro = calc_micro_structure(klines)
        rej_strength, rej_dir = calc_rejection_strength(klines)
        
        return {
            "available": True,
            "key_level_status": key_status,
            "key_level_type": key_type,
            "volume_confirmation": vol_confirm,
            "obv_direction": obv_dir,
            "micro_structure": micro,
            "rejection_strength": rej_strength,
            "rejection_direction": rej_dir
        }
    
    return {"available": False}


def build_ai_enhancement(symbol: str) -> Optional[dict]:
    """
    构建完整的 AI 增强数据
    对标投喂数据中的 ai_enhancement 结构
    """
    # 获取各周期快照
    tf4h = get_tf_snapshot(symbol, "4h")
    tf1h = get_tf_snapshot(symbol, "1h")
    tf15m = get_tf_snapshot(symbol, "15m")
    
    if not tf15m:
        return None
    
    # 获取K线数据
    klines_4h = get_klines_from_redis(symbol, "4h", 50)
    klines_1h = get_klines_from_redis(symbol, "1h", 50)
    klines_15m = get_klines_from_redis(symbol, "15m", 50)
    
    # 构建各周期技术分析
    tech_4h = build_tf_technicals(tf4h, klines_4h, "4h")
    tech_1h = build_tf_technicals(tf1h, klines_1h, "1h")
    tech_15m = build_tf_technicals(tf15m, klines_15m, "15m")
    
    # 添加额外信息用于 overall_bias 计算
    if tf4h:
        tech_4h["trend"] = tf4h.get("structure", {}).get("trend")
    if tf1h:
        tech_1h["trend"] = tf1h.get("structure", {}).get("trend")
        tech_1h["price_location"] = tech_1h.get("price_location", "unknown")
    if tf15m:
        tech_15m["micro_structure"] = tech_15m.get("micro_structure", "unclear")
    
    # 综合偏向
    overall_bias = calc_overall_bias(tech_4h, tech_1h, tech_15m)
    
    # 关键位
    current_price = tf15m.get("close") if tf15m else None
    key_levels = calc_key_levels(symbol, current_price, tf4h, tf1h, tf15m)
    
    # Order Flow
    order_flow = calc_order_flow(klines_15m)
    
    # 信号分析
    signal_analysis = calc_signal_analysis(tf15m, tf4h)
    
    # 潜在交易设置
    atr_15m = tf15m.get("atr") if tf15m else None
    potential_setups = calc_potential_setups(current_price, key_levels, atr_15m)
    
    # 市场上下文
    atr_ratio = tf15m.get("atr_ratio") if tf15m else None
    trend_15m = tf15m.get("structure", {}).get("trend", "range") if tf15m else "range"
    market_context = calc_market_context(atr_ratio, trend_15m)
    
    return {
        "technicals": {
            "tf4h": tech_4h,
            "tf1h": tech_1h,
            "tf15m": tech_15m
        },
        "overall_bias": overall_bias,
        "key_levels": key_levels,
        "order_flow": order_flow,
        "signal_analysis": signal_analysis,
        "potential_setups": potential_setups,
        "market_context": market_context
    }


def build_structure_summary(snapshot: dict) -> Optional[dict]:
    """
    构建结构摘要（扁平化）
    对标投喂数据中的 structure_summary
    """
    if not snapshot:
        return None
    
    structure = snapshot.get("structure", {})
    if not structure.get("valid"):
        return None
    
    return {
        "trend": structure.get("trend"),
        "bias": structure.get("bias"),
        "range_high": structure.get("range_high"),
        "range_low": structure.get("range_low"),
        "swing_high": structure.get("swing_high"),
        "swing_low": structure.get("swing_low"),
        "last_break": structure.get("last_break"),
        "range_location": snapshot.get("range_location"),
        "range_pos": snapshot.get("range_pos")
    }
