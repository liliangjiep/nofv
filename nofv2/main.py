import threading
import asyncio
from pathlib import Path
from logger import logger, log_info, log_error, LOG_FILE
from notifier import message_worker
from database import clear_redis
from kline_fetcher import fetch_all
from indicators import calculate_signal
from config import monitor_symbols, timeframes
from scheduler import schedule_loop_async_with_monitor
from api_history import run_api_server
from ai500 import update_oi_symbols
from deepseek_batch_pusher import init_http_session, close_http_session


def clear_log_file():
    """启动时清空日志文件"""
    try:
        if LOG_FILE.exists():
            LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass

async def main_async():
    await init_http_session()

    try:
        await schedule_loop_async_with_monitor()
    finally:
        await close_http_session()

def main():
    clear_log_file()
    
    log_info("🚀 NOFv2 启动")

    clear_redis()
    log_info("🗑️ Redis 已清空")

    threading.Thread(target=message_worker, daemon=True).start()
    log_info("📨 消息推送线程已启动")

    update_oi_symbols()
    log_info("📊 AI500 定时任务已启动")

    log_info("⏳ 启动异步调度循环")

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log_info("👋 程序已退出")

if __name__ == "__main__":
    main()
