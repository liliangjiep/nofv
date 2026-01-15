from market_structure import MarketStructure

# 实盘 API
BINANCE_API_KEY_LIVE = "SB4qrqmH9PPlTAdCRqnYr4fOhS0u1JEtr6QmccNR8ZboXZQclU4wA8NUA9kJhxA1"
BINANCE_API_SECRET_LIVE = "9l186bg2bVMeFYKQllxyBOsI5VstaLH0Q2XQRDehLweWXQHTdvNgezVTBzS2bE27"

# 测试网 API (去 https://testnet.binancefuture.com 申请)
BINANCE_API_KEY_TEST = "i40fOhMXnr4J1x77o0hHJLIZkfoed6zKSjHK0o6ApSl5GBUrlpmJgnOWDKaOwfH7"  # 填入测试网 API Key
BINANCE_API_SECRET_TEST = "R2LxTA7INQRstaFrM6Ur2SYL2YoGJqxm6OJ9FCHA6hcmUNy3QBsIuewSesmeV9wm"  # 填入测试网 API Secret

# 环境切换: False=实盘, True=测试网
BINANCE_ENVIRONMENT = True

# 根据环境自动选择 Key
if BINANCE_ENVIRONMENT:
    BINANCE_API_KEY = BINANCE_API_KEY_TEST
    BINANCE_API_SECRET = BINANCE_API_SECRET_TEST
else:
    BINANCE_API_KEY = BINANCE_API_KEY_LIVE
    BINANCE_API_SECRET = BINANCE_API_SECRET_LIVE

# 代理配置（如果不需要代理，设为 None）
PROXY = "http://127.0.0.1:7890"  # 改成你的代理地址和端口

# 请求参数配置
requests_params = {
    'timeout': 10
}

TELEGRAM_BOT_TOKEN = "" #tg token
TELEGRAM_CHAT_ID = "-" #tg 频道
TG_ENABLED = False  # TG 推送开关：True=发送，False=不发送

# AIBTC.VIP大模型配置 (官方新增)
CLAUDE_API_KEY = ""  #对应模型的 key
CLAUDE_MODEL = ""  #对应模型的名称
CLAUDE_URL = ""


# DeepSeek 配置 (你的原有配置)
DEEPSEEK_API_KEY = "sk-2689093f27d1443881cb2e5a72c0e4b7"  # deepseek key
DEEPSEEK_MODEL = "deepseek-reasoner"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Gemini 配置 (你的原有配置)
GEMINI_API_KEY = "AIzaSyAiZXSacSBpPrdTuQ1XJSHI-HczE5CLqE4"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_PROJECT = ""  # Gemini API 不需要项目ID

# 小米 MiMo 配置
MIMO_API_KEY = "sk-c7rusd30ccp6y0lmiityesv1jtlwd5f1kdithuq7pcz5cq76"  # 小米 MiMo API Key
MIMO_MODEL = "mimo-v2-flash"
MIMO_URL = "https://api.xiaomimimo.com/v1/chat/completions"

# 投喂选择
AI_PROVIDER = "deepseek"  # 可选: "claude" / "deepseek" / "gemini" / "mimo"

# ===== 固定币种监控池 =====
monitor_symbols = ['ETHUSDT', 'SOLUSDT']

# ===== 仓位管理 =====
MAX_POSITIONS = 10  # 最大同时持仓数量
MIN_TRADE_AMOUNT = 50  # 最小交易金额，提高门槛降低交易频率
MAX_POSITION_SIZE_USD = 500  # 最大持仓金额，控制风险

# ===== AI调用优化 =====
AI_REQUEST_INTERVAL = 60  # AI请求最小间隔（秒），避免过于频繁调用
MIN_CONFIDENCE_SCORE = 0.3  # 最小置信度分数，只执行高置信度信号

# ===== 调度时间间隔（分钟） =====
SCAN_INTERVAL = 15   # 全量扫描间隔（扫描所有监控币种）
# MANAGE_INTERVAL = 5  # 持仓管理间隔（只管理已有持仓）

# ===== 价格监控间隔（秒） =====
PRICE_MONITOR_INTERVAL = 10  # 价格监控间隔，用于更新峰值和检查移动止盈

# ===== 动态回撤止盈配置 =====
TRAILING_STOP_ENABLED = True  # 是否启用动态回撤止盈

# 激活条件：盈利超过此百分比才启用移动止盈
TRAILING_STOP_ACTIVATE_PCT = 2.0  # 盈利 2% 后激活

# 百分比回撤阈值（ATR不可用时的备用）
TRAILING_STOP_TIERS = [
    {"min_profit": 2.0,  "max_profit": 4.0,  "drawdown_pct": 50},  # 盈利2-4%，允许回撤50%
    {"min_profit": 4.0,  "max_profit": 6.0,  "drawdown_pct": 40},  # 盈利4-6%，允许回撤40%
    {"min_profit": 6.0,  "max_profit": 10.0, "drawdown_pct": 35},  # 盈利6-10%，允许回撤35%
    {"min_profit": 10.0, "max_profit": 20.0, "drawdown_pct": 30},  # 盈利10-20%，允许回撤30%
    {"min_profit": 20.0, "max_profit": 999,  "drawdown_pct": 25},  # 盈利>20%，允许回撤25%
]

# ===== 自适应 ATR 动态止盈配置 =====
ATR_TRAILING_STOP_ENABLED = True  # 启用 ATR 动态止盈

# 自适应ATR倍数：盈利越高，ATR倍数越小（止盈越紧）
ATR_TRAILING_TIERS = [
    {"min_profit": 1.0,  "max_profit": 2.0,  "atr_mult": 1.5},   # 小盈利，宽松点
    {"min_profit": 2.0,  "max_profit": 4.0,  "atr_mult": 1.2},   # 中等盈利
    {"min_profit": 4.0,  "max_profit": 6.0,  "atr_mult": 1.0},   # 较好盈利
    {"min_profit": 6.0,  "max_profit": 10.0, "atr_mult": 0.8},   # 高盈利，收紧
    {"min_profit": 10.0, "max_profit": 999,  "atr_mult": 0.6},   # 暴利，锁定利润
]

# 最大允许回撤百分比（防止ATR太大）
ATR_MAX_DRAWDOWN_PCT = 2.0  # 无论ATR多大，最多允许回撤2%（放宽，减少过早止盈）

# ===== 限价单管理配置 =====
LIMIT_ORDER_TIMEOUT_MINUTES = 5  # 限价单超时时间（分钟），超时未成交自动撤销
LIMIT_ORDER_CHECK_ENABLED = True  # 是否启用限价单超时检查

OI_BASE_URL = "https://fapi.binance.com"

# ===== 多周期 =====
timeframes = ["4h", "1h", "15m"]

# ===== Redis =====
REDIS_HOST = "43.153.230.38"
REDIS_PORT = 6379
REDIS_DB = 10
REDIS_PASSWORD = "085799."  # 如果Redis没有密码，请设为 None
REDIS_USERNAME = "default"  # Redis ACL用户名，如不需要则设为 None

#定义「周期 → EMA 参数映射」
EMA_CONFIG = {
    "15m": [20, 50],
    "1h":  [50],
}

#定义「周期 → K线数量」(官方新增)
KLINE_LIMITS = {
    "15m": 301,
    "1h": 501,
    "4h": 801,
}

#结构计算 (官方新增)
STRUCTURE_PARAMS = {
    "15m": {"swing_size": 4, "keep_pivots": 10, "trend_vote_lookback": 3, "range_pivot_k": 3},
    "1h":  {"swing_size": 6, "keep_pivots": 12, "trend_vote_lookback": 3, "range_pivot_k": 3},
    "4h":  {"swing_size": 10, "keep_pivots": 14, "trend_vote_lookback": 3, "range_pivot_k": 3},
}

# 每个话题在 TG 群里的 message_thread_id (官方新增)
TOPIC_MAP = {
    "Trading-signals": 58069,      # 交易信号
    "On-chain-monitoring": 58071,  # 链上监控
    "Abnormal-signal": 58065,      # 交易话题
}

DEFAULT_TOPIC = None   # None = 主聊天
