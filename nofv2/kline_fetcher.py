import time
import json
import logging
import requests
from concurrent.futures import ThreadPoolExecutor
from config import monitor_symbols, timeframes, KLINE_LIMITS, PROXY
from database import redis_client

proxies = {"http": PROXY, "https": PROXY} if PROXY else None

def fetch_historical(symbol, interval, limit):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    rkey = f"historical_data:{symbol}:{interval}"

    try:
        data = requests.get(url, timeout=5, proxies=proxies).json()
        now = int(time.time() * 1000)

        with redis_client.pipeline() as pipe:
            for k in data:
                ts, close_ts = k[0], k[6]
                
                # 已收盘的K线正常存储
                if close_ts <= now:
                    entry = json.dumps({
                        "Open": float(k[1]),
                        "High": float(k[2]),
                        "Low": float(k[3]),
                        "Close": float(k[4]),
                        "Volume": float(k[5]),
                        "TakerBuyVolume": float(k[9]),
                        "TakerSellVolume": float(k[5]) - float(k[9]),
                        "is_closed": True
                    })
                    pipe.hset(rkey, ts, entry)
                else:
                    # 当前未收盘K线 - 单独存储为 current_candle
                    current_candle = {
                        "timestamp": ts,
                        "close_time": close_ts,
                        "Open": float(k[1]),
                        "High": float(k[2]),
                        "Low": float(k[3]),
                        "Close": float(k[4]),  # 当前价格
                        "Volume": float(k[5]),
                        "TakerBuyVolume": float(k[9]),
                        "TakerSellVolume": float(k[5]) - float(k[9]),
                        "is_closed": False,
                        "seconds_to_close": int((close_ts - now) / 1000)
                    }
                    pipe.set(f"current_candle:{symbol}:{interval}", json.dumps(current_candle), ex=120)
            
            pipe.execute()

    except Exception as e:
        logging.warning(f"{symbol} {interval} 历史获取失败: {e}")


def fetch_realtime_price(symbol):
    """获取实时价格"""
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        data = requests.get(url, timeout=3, proxies=proxies).json()
        price = float(data.get("price", 0))
        redis_client.set(f"realtime_price:{symbol}", price, ex=30)
        return price
    except Exception as e:
        logging.warning(f"{symbol} 实时价格获取失败: {e}")
        return None


def fetch_all():
    total_requests = len(monitor_symbols) * len(timeframes)
    print(f"⏳ 初始化下载中... 预计请求数: {total_requests}")

    start_time = time.time()

    time.sleep(2)
    with ThreadPoolExecutor(max_workers=8) as exe:
        for s in monitor_symbols:
            # 获取实时价格
            exe.submit(fetch_realtime_price, s)
            # 获取K线数据
            for tf in timeframes:
                limit = KLINE_LIMITS.get(tf, 301)
                exe.submit(fetch_historical, s, tf, limit)

    elapsed = time.time() - start_time
    avg = elapsed / total_requests if total_requests > 0 else 0

    print(f"📌 历史数据初始化完成 ✓")
    print(f"⏱ 总耗时: {elapsed:.2f} 秒 (平均单请求: {avg:.3f} 秒)")
