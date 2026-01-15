# logger.py
import logging
import sys
from pathlib import Path

# 日志文件路径
LOG_FILE = Path(__file__).parent / "nofv2.log"

# 创建 logger
logger = logging.getLogger("nofv2")
logger.setLevel(logging.DEBUG)

# 防止重复添加 handler
if not logger.handlers:
    # 格式
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 文件处理器（立即刷新）
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# 便捷函数（带 flush）
def log_info(msg):
    logger.info(msg)
    for h in logger.handlers:
        h.flush()

def log_error(msg):
    logger.error(msg)
    for h in logger.handlers:
        h.flush()

def log_warning(msg):
    logger.warning(msg)
    for h in logger.handlers:
        h.flush()

def log_debug(msg):
    logger.debug(msg)
    for h in logger.handlers:
        h.flush()

def log_trade(symbol, action, detail=""):
    """交易专用日志"""
    logger.info(f"🔔 TRADE | {symbol} | {action} | {detail}")
    for h in logger.handlers:
        h.flush()
