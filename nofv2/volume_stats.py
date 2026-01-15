import time
import requests
from config import OI_BASE_URL as BASE, PROXY

proxies = {"http": PROXY, "https": PROXY} if PROXY else None

# =========================
# 🔗 URL mapping
# =========================
URLS = {
    "OPEN_INTEREST": BASE + "/fapi/v1/openInterest?symbol={symbol}",
    "FUNDING_RATE": BASE + "/fapi/v1/premiumIndex?symbol={symbol}",
    "TICKER_24HR": BASE + "/fapi/v1/ticker/24hr?symbol={symbol}",
    "TICKER_24HR_ALL": BASE + "/fapi/v1/ticker/24hr",  # 获取所有币种
}

# =========================
# 🔐 Simple in-memory cache
# =========================
_cached = {
    "oi": {},
    "funding": {},
    "24hr": {},
    "all_tickers": None,  # 全量涨跌幅缓存
}

def _cache_get(group, key, ttl):
    item = _cached[group].get(key)
    if not item:
        return None
    if time.time() - item["ts"] > ttl:
        return None
    return item["value"]

def _cache_set(group, key, value):
    _cached[group][key] = {
        "value": value,
        "ts": time.time()
    }

# =========================
# 📌 API wrappers
# =========================
def get_open_interest(symbol):
    cached = _cache_get("oi", symbol, ttl=60)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            URLS["OPEN_INTEREST"].format(symbol=symbol),
            timeout=5,
            proxies=proxies
        ).json()
        value = float(r.get("openInterest"))
    except Exception:
        value = None

    _cache_set("oi", symbol, value)
    return value

def get_funding_rate(symbol):
    cached = _cache_get("funding", symbol, ttl=60)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            URLS["FUNDING_RATE"].format(symbol=symbol),
            timeout=5,
            proxies=proxies
        ).json()
        value = float(r.get("lastFundingRate"))
    except Exception:
        value = None

    _cache_set("funding", symbol, value)
    return value

def get_24hr_change(symbol):
    cached = _cache_get("24hr", symbol, ttl=60)
    if cached is not None:
        return cached

    try:
        j = requests.get(
            URLS["TICKER_24HR"].format(symbol=symbol),
            timeout=5,
            proxies=proxies
        ).json()
        result = {
            "priceChange": float(j.get("priceChange", 0)),
            "priceChangePercent": float(j.get("priceChangePercent", 0)),
            "lastPrice": float(j.get("lastPrice", 0)),
            "highPrice": float(j.get("highPrice", 0)),
            "lowPrice": float(j.get("lowPrice", 0)),
            "volume": float(j.get("volume", 0)),
            "quoteVolume": float(j.get("quoteVolume", 0)),
        }
    except Exception:
        result = None

    _cache_set("24hr", symbol, result)
    return result


# =========================
# 📊 涨跌幅排行榜
# =========================
def get_all_tickers(ttl=30):
    """
    获取所有合约的24h行情数据
    ttl: 缓存时间（秒）
    """
    cached = _cached.get("all_tickers")
    if cached and time.time() - cached["ts"] < ttl:
        return cached["value"]
    
    try:
        r = requests.get(
            URLS["TICKER_24HR_ALL"],
            timeout=10,
            proxies=proxies
        ).json()
        
        # 只保留 USDT 永续合约
        tickers = [
            {
                "symbol": t["symbol"],
                "lastPrice": float(t.get("lastPrice", 0)),
                "priceChangePercent": float(t.get("priceChangePercent", 0)),
                "volume": float(t.get("volume", 0)),
                "quoteVolume": float(t.get("quoteVolume", 0)),
                "highPrice": float(t.get("highPrice", 0)),
                "lowPrice": float(t.get("lowPrice", 0)),
            }
            for t in r
            if t["symbol"].endswith("USDT") and "_" not in t["symbol"]  # 排除交割合约
        ]
        
        _cached["all_tickers"] = {"value": tickers, "ts": time.time()}
        return tickers
    except Exception as e:
        print(f"❌ 获取全量行情失败: {e}")
        return []


def get_top_gainers(n=10, min_volume=10_000_000):
    """
    获取涨幅榜前N名
    min_volume: 最小24h成交额（USDT），过滤小币种
    """
    tickers = get_all_tickers()
    if not tickers:
        return []
    
    # 过滤成交额 + 排序
    filtered = [t for t in tickers if t["quoteVolume"] >= min_volume]
    sorted_list = sorted(filtered, key=lambda x: x["priceChangePercent"], reverse=True)
    
    return sorted_list[:n]


def get_top_losers(n=10, min_volume=10_000_000):
    """
    获取跌幅榜前N名
    min_volume: 最小24h成交额（USDT），过滤小币种
    """
    tickers = get_all_tickers()
    if not tickers:
        return []
    
    # 过滤成交额 + 排序
    filtered = [t for t in tickers if t["quoteVolume"] >= min_volume]
    sorted_list = sorted(filtered, key=lambda x: x["priceChangePercent"])
    
    return sorted_list[:n]


def get_hot_symbols(top_n=5, min_volume=10_000_000):
    """
    获取热门币种（涨幅榜 + 跌幅榜）
    返回去重后的币种列表
    """
    gainers = get_top_gainers(top_n, min_volume)
    losers = get_top_losers(top_n, min_volume)
    
    symbols = set()
    for t in gainers + losers:
        symbols.add(t["symbol"])
    
    return list(symbols)
