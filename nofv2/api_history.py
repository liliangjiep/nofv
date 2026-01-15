import os
import json
import time
import asyncio
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from typing import Optional
from contextlib import asynccontextmanager
from database import redis_client
from fastapi.staticfiles import StaticFiles
from account_positions import account_snapshot, tp_sl_cache, get_account_status

KEY_REQ = "deepseek_analysis_request_history"
KEY_RES = "deepseek_analysis_response_history"
KEY_TRADES = "trading_records"
KEY_COMPLETED = "completed_trades"

# 后台任务：定期刷新账户数据
async def refresh_account_loop():
    while True:
        try:
            get_account_status()
        except Exception as e:
            print(f"刷新账户数据失败: {e}")
        await asyncio.sleep(5)  # 每5秒刷新一次

@asynccontextmanager
async def lifespan(app):
    # 启动时立即刷新一次
    try:
        get_account_status()
    except Exception:
        pass
    # 启动后台刷新任务
    task = asyncio.create_task(refresh_account_loop())
    yield
    task.cancel()

app = FastAPI(title="AIBTC.VIP Trading Dashboard", lifespan=lifespan)

# 禁止缓存中间件
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

def _read_list(key: str, limit: int):
    items = redis_client.lrange(key, -limit, -1)
    result = []
    items = list(reversed(items))
    for item in items:
        try:
            obj = json.loads(item)
        except Exception:
            continue
        if isinstance(obj, list):
            result.extend(obj)
        else:
            result.append(obj)
    return result

@app.get("/latest")
async def get_latest_pair(limit: int = Query(1, ge=1, le=300)):
    reqs = redis_client.lrange(KEY_REQ, -limit, -1)
    ress = redis_client.lrange(KEY_RES, -limit, -1)
    reqs = list(reversed(reqs))
    ress = list(reversed(ress))

    def safe(x):
        if not x:
            return None
        try:
            return json.loads(x)
        except:
            return {"raw": x}

    return {
        "request": [safe(r) for r in reqs],
        "response": [safe(r) for r in ress]
    }

# 获取当前文件所在目录，用于静态文件路径
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_CURRENT_DIR, "static")

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ----------------- HTML 页面 -----------------
html_page = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>AIBTC.VIP</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #0a0c10;
    color: #e8e8e8;
    font-family: "Inter", "Segoe UI", sans-serif;
    min-height: 100vh;
}
a { color: #5ab2ff; text-decoration: none; }
a:hover { text-decoration: underline; }

/* 顶部导航 */
.navbar {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 12px 24px;
    background: #0d0f14;
    border-bottom: 1px solid #1a1d26;
}
.navbar .logo { font-size: 18px; font-weight: 700; color: #5ab2ff; margin-right: 40px; }
.navbar .nav-links { display: flex; gap: 40px; }
.navbar .nav-links a { color: #888; font-size: 14px; transition: color 0.2s; }
.navbar .nav-links a:hover, .navbar .nav-links a.active { color: #5ab2ff; text-decoration: none; }

/* 主容器 */
.container { padding: 20px 24px; max-width: 1600px; margin: 0 auto; }
.page-title { font-size: 24px; font-weight: 700; color: #5ab2ff; margin-bottom: 6px; }
.page-subtitle { font-size: 13px; color: #666; margin-bottom: 20px; }

/* 页面切换 */
.page { display: none; }
.page.active { display: block; }

/* 统计卡片 */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 20px;
}
.stat-card {
    background: #111319;
    border: 1px solid #1a1d26;
    border-radius: 8px;
    padding: 16px;
}
.stat-card .label { font-size: 12px; color: #666; margin-bottom: 8px; }
.stat-card .value { font-size: 24px; font-weight: 700; }
.stat-card .sub { font-size: 12px; color: #666; margin-top: 4px; }
.stat-card .value.green { color: #00c853; }
.stat-card .value.red { color: #ff5252; }
.stat-card .value.blue { color: #5ab2ff; }
.stat-card .value.yellow { color: #ffc107; }
.pct { font-size: 14px; margin-left: 4px; }

/* 图表区 */
.chart-section {
    background: #111319;
    border: 1px solid #1a1d26;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 20px;
}
.chart-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}
.chart-title { font-size: 14px; font-weight: 600; color: #fff; }
.chart-legend { font-size: 12px; color: #666; }
#profit_chart { height: 300px; }

/* Tab 切换 */
.tabs {
    display: flex;
    gap: 0;
    margin-bottom: 16px;
}
.tab-btn {
    flex: 1;
    padding: 12px 20px;
    background: #111319;
    border: 1px solid #1a1d26;
    color: #888;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
}
.tab-btn:first-child { border-radius: 8px 0 0 8px; }
.tab-btn:last-child { border-radius: 0 8px 8px 0; }
.tab-btn.active { background: #1a5fd9; color: #fff; border-color: #1a5fd9; }
.tab-btn:hover:not(.active) { background: #1a1d26; }

/* 表格 */
.table-wrap {
    background: #111319;
    border: 1px solid #1a1d26;
    border-radius: 8px;
    overflow: hidden;
}
.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.data-table th {
    background: #0d0f14;
    color: #666;
    font-weight: 500;
    padding: 12px 10px;
    text-align: left;
    border-bottom: 1px solid #1a1d26;
}
.data-table td {
    padding: 12px 10px;
    border-bottom: 1px solid #1a1d26;
}
.data-table tr:hover { background: #151820; }
.badge { padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge.long { background: rgba(0,200,83,0.15); color: #00c853; }
.badge.short { background: rgba(255,82,82,0.15); color: #ff5252; }
.badge.wait, .badge.hold { background: rgba(102,102,102,0.2); color: #888; }
.badge.buy { background: rgba(0,200,83,0.15); color: #00c853; }
.badge.sell { background: rgba(255,82,82,0.15); color: #ff5252; }

/* AI决策页面 */
.ai-controls {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
}
.ai-controls label { color: #888; font-size: 13px; }
.ai-controls select {
    background: #111319;
    color: #fff;
    border: 1px solid #1a1d26;
    border-radius: 6px;
    padding: 8px 12px;
}
.ai-controls button {
    background: #ff5252;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    cursor: pointer;
    font-weight: 600;
}
.ai-controls button:hover { background: #d32f2f; }
.ai-summary { font-size: 13px; color: #666; margin-bottom: 16px; }

.ai-layout {
    display: grid;
    grid-template-columns: 350px 1fr;
    gap: 16px;
}
.decision-list {
    background: #111319;
    border: 1px solid #1a1d26;
    border-radius: 8px;
    max-height: 700px;
    overflow-y: auto;
}
.decision-item {
    padding: 14px 16px;
    border-bottom: 1px solid #1a1d26;
    cursor: pointer;
    transition: background 0.2s;
}
.decision-item:hover, .decision-item.active { background: #1a1d26; }
.decision-item .round { font-weight: 600; color: #ffc107; font-size: 15px; }
.decision-item .status { font-size: 12px; color: #666; margin-top: 2px; }
.decision-item .meta { font-size: 12px; color: #888; margin-top: 6px; }
.decision-item .meta span { margin-right: 10px; }
.decision-item .meta .signal { color: #ff5252; }
.decision-item .meta .wait { color: #00c853; }

.decision-detail {
    background: #111319;
    border: 1px solid #1a1d26;
    border-radius: 8px;
    padding: 16px;
}
.detail-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #1a1d26;
}
.detail-title { font-size: 16px; font-weight: 600; color: #ffc107; }
.detail-meta { font-size: 12px; color: #888; }
.detail-meta span { margin-left: 12px; }

.signal-table { margin-bottom: 16px; }

.collapsible {
    background: #0d0f14;
    border: 1px solid #1a1d26;
    border-radius: 6px;
    margin-bottom: 10px;
}
.collapsible-section {
    background: #0d0f14;
    border: 1px solid #1a1d26;
    border-radius: 6px;
    margin-top: 12px;
}
.collapsible-header {
    padding: 12px 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #888;
}
.collapsible-header:hover { background: #151820; }
.collapsible-header .arrow { font-size: 10px; color: #666; }
.collapsible-body {
    display: none;
    padding: 14px;
    border-top: 1px solid #1a1d26;
    font-size: 12px;
    color: #aaa;
    white-space: pre-wrap;
    max-height: 400px;
    overflow-y: auto;
}
.collapsible-body.open { display: block; }
.code-block {
    background: #0a0c10;
    padding: 12px;
    border-radius: 4px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 11px;
    line-height: 1.5;
    color: #ccc;
    word-break: break-all;
}

/* 响应式 */
@media (max-width: 1200px) {
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .ai-layout { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
    .stats-grid { grid-template-columns: 1fr; }
    .navbar .nav-links { gap: 12px; }
}

/* 滚动条 */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0a0c10; }
::-webkit-scrollbar-thumb { background: #2a3143; border-radius: 3px; }
</style>
</head>
<body>

<!-- 导航栏 -->
<nav class="navbar">
    <div class="logo">AIBTC.VIP</div>
    <div class="nav-links">
        <a href="javascript:void(0)" onclick="showPage('ai')" id="nav-ai">AI决策</a>
        <a href="javascript:void(0)" onclick="showPage('dashboard')" id="nav-dashboard" class="active">交易仪表盘</a>
    </div>
</nav>

<!-- 交易仪表盘页面 -->
<div id="page-dashboard" class="page active">
    <div class="container">
        <div class="page-title">AIBTC.VIP 交易统计仪表盘</div>
        <div class="page-subtitle" id="dashboard-subtitle">当前统计:全部 | 基准资金 -- USDT</div>
        
        <!-- 第一行统计卡片 -->
        <div class="stats-grid" id="stats-row1"></div>
        
        <!-- 第二行统计卡片 -->
        <div class="stats-grid" id="stats-row2"></div>
        
        <!-- 权益曲线 -->
        <div class="chart-section">
            <div class="chart-header">
                <div class="chart-title">权益曲线</div>
                <div class="chart-legend" id="chart-legend"></div>
            </div>
            <div id="profit_chart"></div>
        </div>
        
        <!-- Tab 切换 -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('positions')">当前持仓 (<span id="pos-count">0</span>)</button>
            <button class="tab-btn" onclick="switchTab('trades')">已完成交易 (<span id="trade-count">0</span>)</button>
        </div>
        
        <!-- 持仓表格 -->
        <div id="tab-positions" class="table-wrap"></div>
        
        <!-- 交易记录表格 -->
        <div id="tab-trades" class="table-wrap" style="display:none;"></div>
    </div>
</div>

<!-- AI决策页面 -->
<div id="page-ai" class="page">
    <div class="container">
        <div class="page-title">AI交易决策仪表盘</div>
        
        <div class="ai-controls">
            <label>最近</label>
            <select id="ai-limit">
                <option value="8">8</option>
                <option value="20">20</option>
                <option value="50">50</option>
                <option value="100">100</option>
            </select>
            <button onclick="loadAIDecisions()">刷新</button>
        </div>
        
        <div class="ai-summary" id="ai-summary"></div>
        
        <div class="ai-layout">
            <div class="decision-list" id="decision-list"></div>
            <div class="decision-detail" id="decision-detail">
                <div style="color:#666;text-align:center;padding:40px;">选择左侧决策轮次查看详情</div>
            </div>
        </div>
    </div>
</div>

<script src="/static/history.js?v=20260109_14"></script>
</body>
</html>
"""

@app.get("/stats")
async def get_stats():
    try:
        total_decisions = redis_client.llen(KEY_RES)
    except Exception:
        total_decisions = 0
    
    try:
        trades_raw = redis_client.lrange(KEY_TRADES, 0, -1)
        trades = [json.loads(t) for t in trades_raw if t]
        total_trades = len(trades)
        open_trades = [t for t in trades if t.get("action", "").startswith("open_")]
        close_trades = [t for t in trades if t.get("action", "").startswith("close_")]
    except Exception:
        total_trades = 0
        open_trades = []
        close_trades = []

    return {
        "total_decisions": total_decisions,
        "total_trades": total_trades,
        "open_count": len(open_trades),
        "close_count": len(close_trades)
    }


@app.get("/positions")
async def get_positions():
    positions = account_snapshot.get("positions", [])
    balance = account_snapshot.get("balance", 0)
    available = account_snapshot.get("available", 0)
    total_unrealized = account_snapshot.get("total_unrealized", 0)
    
    enriched_positions = []
    for p in positions:
        symbol = p.get("symbol", "")
        size = float(p.get("size", 0))
        side = "LONG" if size > 0 else "SHORT"
        
        tp_sl_orders = tp_sl_cache.get(symbol, {}).get(side, [])
        tp_price = None
        sl_price = None
        
        for o in tp_sl_orders:
            if o.get("type") in ["TAKE_PROFIT", "TAKE_PROFIT_MARKET"]:
                tp_price = o.get("stopPrice")
            elif o.get("type") in ["STOP", "STOP_MARKET"]:
                sl_price = o.get("stopPrice")
        
        enriched_positions.append({
            **p,
            "side": side,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "position_value": abs(size) * float(p.get("mark_price", 0))
        })
    
    return {
        "balance": balance,
        "available": available,
        "total_unrealized": total_unrealized,
        "positions": enriched_positions
    }


@app.get("/trades")
async def get_trades(limit: int = Query(50, ge=1, le=500)):
    """获取简单交易记录（保持兼容）"""
    try:
        trades_raw = redis_client.lrange(KEY_TRADES, 0, limit - 1)
        trades = [json.loads(t) for t in trades_raw if t]
        return {"trades": trades, "count": len(trades)}
    except Exception as e:
        return {"trades": [], "count": 0, "error": str(e)}


@app.get("/completed_trades")
async def get_completed_trades(limit: int = Query(100, ge=1, le=500), page: int = Query(1, ge=1)):
    """获取完整的已完成交易记录（带开平仓配对信息）"""
    try:
        # 获取所有记录
        all_trades_raw = redis_client.lrange(KEY_COMPLETED, 0, -1)
        all_trades = []
        for t in all_trades_raw:
            if t:
                try:
                    all_trades.append(json.loads(t))
                except:
                    pass
        
        # 按平仓时间倒序排列（最新的在前面）
        all_trades.sort(key=lambda x: x.get("exit_time", 0) or 0, reverse=True)
        
        total = len(all_trades)
        
        # 分页
        start = (page - 1) * limit
        end = start + limit
        trades = all_trades[start:end]
        
        return {
            "trades": trades,
            "count": len(trades),
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1
        }
    except Exception as e:
        return {"trades": [], "count": 0, "total": 0, "error": str(e)}


@app.get("/decisions")
async def get_decisions(limit: int = Query(20, ge=1, le=100)):
    reqs = redis_client.lrange(KEY_REQ, -limit, -1)
    ress = redis_client.lrange(KEY_RES, -limit, -1)
    reqs = list(reversed(reqs))
    ress = list(reversed(ress))
    
    decisions = []
    for i in range(min(len(reqs), len(ress))):
        try:
            req = json.loads(reqs[i]) if reqs[i] else {}
            res = json.loads(ress[i]) if ress[i] else {}
            
            signals = res.get("signals", [])
            signal_count = len([s for s in signals if s.get("action") not in ["wait", "hold"]])
            wait_count = len([s for s in signals if s.get("action") in ["wait", "hold"]])
            
            decisions.append({
                "round": len(ress) - i,
                "timestamp": res.get("timestamp"),
                "http_status": res.get("http_status", 200),
                "symbols_count": len(signals),
                "signal_count": signal_count,
                "wait_count": wait_count,
                "signals": signals,
                "reasoning": res.get("reasoning"),
                "request": req.get("request") if isinstance(req, dict) else req,
                "response_raw": res
            })
        except Exception:
            continue
    
    return {"decisions": decisions, "total": redis_client.llen(KEY_RES)}


@app.get("/dashboard_stats")
async def get_dashboard_stats():
    """获取仪表盘统计数据"""
    try:
        # 获取收益曲线
        raw_curve = redis_client.hget("profit:ultra_simple", "curve")
        raw_initial = redis_client.hget("profit:ultra_simple", "initial_equity")
        
        curve = json.loads(raw_curve) if raw_curve else []
        initial_equity = float(raw_initial) if raw_initial else 0
        
        # 计算统计
        current_equity = initial_equity
        total_profit = 0
        profit_pct = 0
        max_dd = 0
        
        if curve and initial_equity > 0:
            last = curve[-1]
            # 兼容两种格式: [ts, equity] 或 {ts, equity, profit}
            if isinstance(last, list):
                current_equity = float(last[1])
            else:
                current_equity = float(last.get("equity", initial_equity))
            
            total_profit = current_equity - initial_equity
            profit_pct = (total_profit / initial_equity) * 100
            
            # 最大回撤
            peak = initial_equity
            for p in curve:
                if isinstance(p, list):
                    eq = float(p[1])
                else:
                    eq = float(p.get("equity", 0))
                if eq > peak:
                    peak = eq
                dd = ((peak - eq) / peak) * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
        
        # 获取完整交易记录统计
        completed_raw = redis_client.lrange(KEY_COMPLETED, 0, -1)
        completed_trades = []
        for t in completed_raw:
            if t:
                try:
                    completed_trades.append(json.loads(t))
                except:
                    pass
        
        # 统计胜率 - 基于完整交易记录的 net_pnl
        win_count = 0
        lose_count = 0
        total_fee = 0
        
        for t in completed_trades:
            pnl = t.get("net_pnl")
            if pnl is not None:
                if float(pnl) > 0:
                    win_count += 1
                elif float(pnl) < 0:
                    lose_count += 1
            total_fee += float(t.get("total_fee", 0))
        
        total_closed = win_count + lose_count
        win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0
        
        # 持仓实时盈亏
        positions = account_snapshot.get("positions", [])
        unrealized_pnl = sum(float(p.get("pnl", 0)) for p in positions)
        
        # 平均持仓时长
        hold_times = [t.get("hold_minutes", 0) for t in completed_trades if t.get("hold_minutes") is not None]
        avg_hold_minutes = sum(hold_times) / len(hold_times) if hold_times else 0
        
        return {
            "initial_equity": initial_equity,
            "current_equity": current_equity,
            "total_profit": total_profit,
            "profit_pct": profit_pct,
            "unrealized_pnl": unrealized_pnl,
            "win_rate": win_rate,
            "win_count": win_count,
            "lose_count": lose_count,
            "total_trades": len(completed_trades),
            "total_closed": total_closed,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd,
            "total_fee": total_fee,
            "avg_hold_minutes": avg_hold_minutes,
            "position_count": len(positions),
            "calmar": round(profit_pct / max_dd, 2) if max_dd > 0 else 0
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


@app.get("/", response_class=HTMLResponse)
async def history_page():
    from fastapi.responses import Response
    return Response(
        content=html_page,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.get("/profit_curve")
async def get_profit_curve():
    raw_curve = redis_client.hget("profit:ultra_simple", "curve")
    raw_initial = redis_client.hget("profit:ultra_simple", "initial_equity")

    if not raw_curve:
        return {"count": 0, "initial_equity": None, "data": []}

    try:
        curve = json.loads(raw_curve)
    except Exception:
        curve = []

    try:
        initial_equity = float(raw_initial) if raw_initial else None
    except Exception:
        initial_equity = None

    return {"count": len(curve), "initial_equity": initial_equity, "data": curve}


if __name__ == "__main__":
    filename = os.path.basename(__file__).replace(".py", "")
    uvicorn.run(f"{filename}:app", host="0.0.0.0", port=8600, reload=True)


def run_api_server():
    uvicorn.run(
        "api_history:app",
        host="0.0.0.0",
        port=8600,
        reload=False,
        access_log=False,
        log_level="warning"
    )
