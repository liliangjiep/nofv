/* AIBTC.VIP Trading Dashboard */
var currentDecisions = [];
var selectedDecisionIndex = 0;
console.log('history.js loaded v8');

function showPage(page) {
    var pages = document.querySelectorAll('.page');
    for (var i = 0; i < pages.length; i++) pages[i].classList.remove('active');
    var navLinks = document.querySelectorAll('.nav-links a');
    for (var i = 0; i < navLinks.length; i++) navLinks[i].classList.remove('active');
    document.getElementById('page-' + page).classList.add('active');
    document.getElementById('nav-' + page).classList.add('active');
    if (page === 'dashboard') loadDashboard();
    if (page === 'ai') loadAIDecisions();
}

function switchTab(tab) {
    var btns = document.querySelectorAll('.tab-btn');
    for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
    if (tab === 'positions') btns[0].classList.add('active');
    else btns[1].classList.add('active');
    document.getElementById('tab-positions').style.display = tab === 'positions' ? 'block' : 'none';
    document.getElementById('tab-trades').style.display = tab === 'trades' ? 'block' : 'none';
}

function loadDashboard() {
    console.log('loadDashboard...');
    Promise.all([
        fetch('/dashboard_stats').then(function(r) { return r.json(); }),
        fetch('/profit_curve').then(function(r) { return r.json(); }),
        fetch('/positions').then(function(r) { return r.json(); }),
        fetch('/completed_trades?limit=10&page=1').then(function(r) { return r.json(); })
    ]).then(function(results) {
        var stats = results[0], profit = results[1], positions = results[2], trades = results[3];
        console.log('Data:', stats, profit);
        renderDashboardStats(stats, profit);
        renderProfitChart(profit);
        renderPositionsTable(positions);
        renderTradesTable(trades);
        document.getElementById('pos-count').textContent = (positions.positions && positions.positions.length) || 0;
        document.getElementById('trade-count').textContent = trades.total || 0;
        var initial = profit.initial_equity || 0;
        document.getElementById('dashboard-subtitle').textContent = 'Stats | Base: ' + initial.toFixed(2) + ' USDT';
    }).catch(function(err) { console.error('loadDashboard error:', err); });
}

function renderDashboardStats(stats, profit) {
    var initial = profit.initial_equity || 0;
    var totalProfit = stats.total_profit || 0;
    var profitPct = stats.profit_pct || 0;
    var unrealized = stats.unrealized_pnl || 0;
    var winRate = stats.win_rate || 0;
    var winCount = stats.win_count || 0;
    var loseCount = stats.lose_count || 0;
    var totalTrades = stats.total_trades || 0;
    var posCount = stats.position_count || 0;
    var currentEquity = stats.current_equity || initial;
    var totalFee = stats.total_fee || 0;
    var maxDD = stats.max_drawdown || 0;
    var calmar = stats.calmar || 0;
    
    var row1 = '<div class="stat-card"><div class="label">总净收益</div><div class="value ' + (totalProfit >= 0 ? 'green' : 'red') + '">' + (totalProfit >= 0 ? '+' : '') + totalProfit.toFixed(2) + ' USDT</div><div class="sub">' + (profitPct >= 0 ? '+' : '') + profitPct.toFixed(2) + '%</div></div>';
    row1 += '<div class="stat-card"><div class="label">持仓实时净收益</div><div class="value ' + (unrealized >= 0 ? 'green' : 'red') + '">' + (unrealized >= 0 ? '+' : '') + unrealized.toFixed(2) + '</div></div>';
    row1 += '<div class="stat-card"><div class="label">胜率</div><div class="value yellow">' + winRate.toFixed(1) + '%</div><div class="sub">胜:' + winCount + ' 负:' + loseCount + '</div></div>';
    row1 += '<div class="stat-card"><div class="label">交易次数</div><div class="value blue">' + totalTrades + '</div><div class="sub">持仓: ' + posCount + '</div></div>';
    document.getElementById('stats-row1').innerHTML = row1;
    
    var row2 = '<div class="stat-card"><div class="label">当前账户余额</div><div class="value blue">' + currentEquity.toFixed(2) + ' USDT</div><div class="sub">初始: ' + initial.toFixed(2) + '</div></div>';
    row2 += '<div class="stat-card"><div class="label">累计交易成本</div><div class="value red">- ' + totalFee.toFixed(2) + ' USDT</div></div>';
    row2 += '<div class="stat-card"><div class="label">收益/回撤</div><div class="value green">+' + profitPct.toFixed(2) + '% / -' + maxDD.toFixed(2) + '%</div><div class="sub">Calmar: ' + calmar.toFixed(2) + '</div></div>';
    row2 += '<div class="stat-card"><div class="label">最大回撤</div><div class="value red">-' + (maxDD * initial / 100).toFixed(2) + ' USDT (-' + maxDD.toFixed(2) + '%)</div></div>';
    document.getElementById('stats-row2').innerHTML = row2;
}

function renderProfitChart(data) {
    var el = document.getElementById('profit_chart');
    if (!el) return;
    var list = (data && data.data) || [];
    var initial = (data && data.initial_equity) || 0;
    if (list.length === 0) { el.innerHTML = '<div style="padding:40px;color:#666;text-align:center;">暂无数据</div>'; return; }
    var chart = echarts.init(el);
    var xData = [], yData = [], baseLine = [];
    for (var i = 0; i < list.length; i++) {
        var item = list[i];
        var ts = Array.isArray(item) ? item[0] : item.ts;
        xData.push(new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }));
        yData.push(Array.isArray(item) ? Number(item[1]) : Number(item.equity));
        baseLine.push(initial);
    }
    document.getElementById('chart-legend').innerHTML = '权益(USDT) | 基准 ' + initial.toFixed(2) + ' USDT';
    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', backgroundColor: '#1a1d26', textStyle: { color: '#fff' } },
        grid: { left: 50, right: 20, top: 20, bottom: 40 },
        xAxis: { type: 'category', data: xData, axisLabel: { color: '#666', fontSize: 10 } },
        yAxis: { type: 'value', axisLabel: { color: '#666' }, splitLine: { lineStyle: { color: '#1a1d26' } } },
        series: [
            { name: '权益', type: 'line', data: yData, smooth: false, symbol: 'circle', symbolSize: 3, lineStyle: { width: 2, color: '#5ab2ff' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(90,178,255,0.2)' }, { offset: 1, color: 'rgba(90,178,255,0)' }] } } },
            { name: '基准', type: 'line', data: baseLine, symbol: 'none', lineStyle: { type: 'dashed', width: 1, color: '#444' } }
        ]
    });
    window.addEventListener('resize', function() { chart.resize(); });
}

function renderPositionsTable(data) {
    var wrap = document.getElementById('tab-positions');
    var positions = (data && data.positions) || [];
    if (positions.length === 0) { wrap.innerHTML = '<div style="padding:40px;color:#666;text-align:center;">暂无持仓</div>'; return; }
    var html = '<table class="data-table"><thead><tr><th>交易对</th><th>方向</th><th>数量</th><th>入场价格</th><th>杠杆</th><th>标记价</th><th>未实现盈亏</th><th>止盈/止损</th></tr></thead><tbody>';
    for (var i = 0; i < positions.length; i++) {
        var p = positions[i];
        var side = p.side || 'LONG';
        var pnl = Number(p.pnl || 0);
        var leverage = p.leverage || 1;
        var tpStr = p.tp_price ? Number(p.tp_price).toFixed(4) : '-';
        var slStr = p.sl_price ? Number(p.sl_price).toFixed(4) : '-';
        html += '<tr><td><b>' + p.symbol + '</b></td><td><span class="badge ' + side.toLowerCase() + '">' + side + '</span></td><td>' + Math.abs(Number(p.size || 0)).toFixed(4) + '</td><td>' + Number(p.entry || 0).toFixed(6) + '</td><td>' + leverage + 'x</td><td>' + Number(p.mark_price || 0).toFixed(6) + '</td><td style="color:' + (pnl >= 0 ? '#00c853' : '#ff5252') + '">' + (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + ' USDT</td><td>TP:' + tpStr + ' / SL:' + slStr + '</td></tr>';
    }
    html += '</tbody></table>';
    wrap.innerHTML = html;
}

function renderTradesTable(data) {
    var wrap = document.getElementById('tab-trades');
    var trades = (data && data.trades) || [];
    var total = data.total || trades.length;
    var page = data.page || 1;
    var pages = data.pages || 1;
    
    if (trades.length === 0) { 
        wrap.innerHTML = '<div style="padding:40px;color:#666;text-align:center;">暂无交易记录</div>'; 
        return; 
    }
    
    var html = '<div style="padding:10px 16px;color:#888;font-size:12px;">当前页' + page + '(每页 10 条) | 总 ' + total + ' 条';
    html += '<span style="float:right;"><button onclick="loadTradesPage(' + (page-1) + ')" ' + (page <= 1 ? 'disabled style="opacity:0.5"' : '') + '>上一页</button> ';
    html += '<button onclick="loadTradesPage(' + (page+1) + ')" ' + (page >= pages ? 'disabled style="opacity:0.5"' : '') + '>下一页</button></span></div>';
    
    html += '<table class="data-table"><thead><tr><th>交易对</th><th>方向</th><th>开仓方式</th><th>开仓价</th><th>平仓价</th><th>平仓方式</th><th>数量</th><th>净收益</th><th>峰值收益</th><th>最大回撤</th><th>手续费</th><th>持仓时长</th><th>开平时间</th></tr></thead><tbody>';
    
    for (var i = 0; i < trades.length; i++) {
        var t = trades[i];
        var side = t.side || 'LONG';
        var netPnl = t.net_pnl != null ? Number(t.net_pnl) : null;
        var peakPnl = t.peak_pnl != null ? Number(t.peak_pnl) : null;
        var maxDd = t.max_drawdown != null ? Number(t.max_drawdown) : null;
        var totalFee = t.total_fee != null ? Number(t.total_fee) : 0;
        var holdMin = t.hold_minutes != null ? t.hold_minutes : null;
        var pnlPct = t.pnl_pct != null ? Number(t.pnl_pct) : null;
        
        var entryTime = t.entry_time ? new Date(t.entry_time * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '-';
        var exitTime = t.exit_time ? new Date(t.exit_time * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '-';
        
        var holdStr = holdMin != null ? (holdMin >= 60 ? Math.floor(holdMin/60) + '小时' + (holdMin%60) + '分钟' : holdMin + '分钟') : '-';
        var entryType = (t.entry_type && t.entry_type.toLowerCase().indexOf('limit') >= 0) ? '限价单' : '市价单';
        var exitType = (t.exit_type && t.exit_type.toLowerCase().indexOf('limit') >= 0) ? '限价单' : '市价单';
        
        html += '<tr>';
        html += '<td><b>' + t.symbol + '</b></td>';
        html += '<td><span class="badge ' + side.toLowerCase() + '">' + side + '</span></td>';
        html += '<td>' + entryType + '</td>';
        html += '<td>' + (t.entry_price != null ? Number(t.entry_price).toFixed(6) : '-') + '</td>';
        html += '<td>' + (t.exit_price != null ? Number(t.exit_price).toFixed(6) : '-') + '</td>';
        html += '<td>' + exitType + '</td>';
        html += '<td>' + (t.quantity != null ? Number(t.quantity).toFixed(4) : '-') + '</td>';
        html += '<td style="color:' + (netPnl != null && netPnl >= 0 ? '#00c853' : '#ff5252') + '">' + (netPnl != null ? (netPnl >= 0 ? '+' : '') + netPnl.toFixed(2) : '-') + (pnlPct != null ? '<br><small>' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%</small>' : '') + '</td>';
        html += '<td style="color:#00c853">' + (peakPnl != null ? '+' + peakPnl.toFixed(2) : '-') + '</td>';
        html += '<td style="color:#ff5252">' + (maxDd != null ? '-' + maxDd.toFixed(2) : '-') + '</td>';
        html += '<td>' + totalFee.toFixed(2) + '</td>';
        html += '<td>' + holdStr + '</td>';
        html += '<td><small>开: ' + entryTime + '<br>平: ' + exitTime + '</small></td>';
        html += '</tr>';
    }
    html += '</tbody></table>';
    wrap.innerHTML = html;
}

var currentTradesPage = 1;
function loadTradesPage(page) {
    if (page < 1) return;
    currentTradesPage = page;
    fetch('/completed_trades?limit=10&page=' + page).then(function(r) { return r.json(); }).then(function(data) {
        renderTradesTable(data);
        document.getElementById('trade-count').textContent = data.total || 0;
    });
}

function loadAIDecisions() {
    var limitEl = document.getElementById('ai-limit');
    var limit = limitEl ? limitEl.value : 8;
    fetch('/decisions?limit=' + limit).then(function(r) { return r.json(); }).then(function(data) {
        var allDecisions = data.decisions || [];
        // 过滤掉 symbols_count 为 0 的空轮次
        currentDecisions = allDecisions.filter(function(d) {
            return (d.symbols_count || 0) > 0;
        });
        var total = data.total || 0;
        document.getElementById('ai-summary').textContent = '共 ' + total + ' 条 · 已执行 ' + total + ' 轮决策';
        renderDecisionList();
        if (currentDecisions.length > 0) selectDecision(0);
    }).catch(function(err) { console.error('loadAIDecisions error:', err); });
}

function renderDecisionList() {
    var wrap = document.getElementById('decision-list');
    if (currentDecisions.length === 0) { wrap.innerHTML = '<div style="padding:40px;color:#666;text-align:center;">暂无决策</div>'; return; }
    var html = '';
    for (var i = 0; i < currentDecisions.length; i++) {
        var d = currentDecisions[i];
        var httpStatus = d.http_status || 200;
        var statusColor = httpStatus === 200 ? '#00c853' : '#ff5252';
        var timeStr = d.timestamp ? new Date(d.timestamp * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
        html += '<div class="decision-item ' + (i === selectedDecisionIndex ? 'active' : '') + '" onclick="selectDecision(' + i + ')">';
        html += '<div class="round">第 ' + d.round + ' 轮决策</div>';
        html += '<div class="status" style="color:' + statusColor + '">· HTTP ' + httpStatus + '</div>';
        if (timeStr) html += '<div style="font-size:11px;color:#666;margin-top:2px;">' + timeStr + '</div>';
        html += '<div class="meta">symbols <b>' + (d.symbols_count || 0) + '</b>  Signal <span class="signal">' + (d.signal_count || 0) + '</span>  wait <span class="wait">' + (d.wait_count || 0) + '</span></div>';
        html += '</div>';
    }
    wrap.innerHTML = html;
}

function selectDecision(index) {
    selectedDecisionIndex = index;
    renderDecisionList();
    renderDecisionDetail(currentDecisions[index]);
}

function renderDecisionDetail(d) {
    var wrap = document.getElementById('decision-detail');
    if (!d) { wrap.innerHTML = '<div style="color:#666;text-align:center;padding:40px;">选择左侧决策</div>'; return; }
    var signals = d.signals || [];
    // 排序：有动作的排前面，wait/hold 排后面
    signals.sort(function(a, b) {
        var aIsWait = (a.action === 'wait' || a.action === 'hold') ? 1 : 0;
        var bIsWait = (b.action === 'wait' || b.action === 'hold') ? 1 : 0;
        return aIsWait - bIsWait;
    });
    var rows = '';
    for (var i = 0; i < signals.length; i++) {
        var s = signals[i];
        var action = s.action || 'wait';
        var cls = (action === 'wait' || action === 'hold') ? 'wait' : (action.indexOf('long') >= 0 ? 'buy' : 'sell');
        var sizeVal = s.position_size || s.quantity || s.order_value || s.amount || '-';
        rows += '<tr><td><b>' + (s.symbol || '-') + '</b></td><td><span class="badge ' + cls + '">' + action + '</span></td><td>' + (s.entry || '-') + '</td><td>' + sizeVal + '</td><td>' + (s.stop_loss || '-') + '</td><td>' + (s.take_profit || '-') + '</td></tr>';
    }
    
    // 每个币种的 reason + AI审核
    var reasonHtml = '';
    for (var j = 0; j < signals.length; j++) {
        var sig = signals[j];
        var actionCls = (sig.action === 'wait' || sig.action === 'hold') ? 'wait' : (sig.action && sig.action.indexOf('long') >= 0 ? 'buy' : 'sell');
        reasonHtml += '<div style="margin-bottom:12px;padding:10px;background:#0a0c10;border-radius:4px;">';
        reasonHtml += '<div style="margin-bottom:6px;"><b style="color:#5ab2ff;">' + (sig.symbol || '-') + '</b> <span class="badge ' + actionCls + '" style="margin-left:8px;">' + (sig.action || 'wait') + '</span>';
        
        // AI审核结果
        if (sig.ai_decision && sig.ai_decision !== '-') {
            var aiColor = sig.ai_decision === 'APPROVE' ? '#00c853' : (sig.ai_decision === 'CLOSE' ? '#ffc107' : '#ff5252');
            reasonHtml += ' <span style="margin-left:10px;padding:2px 8px;border-radius:3px;font-size:11px;background:' + aiColor + '22;color:' + aiColor + ';">AI: ' + sig.ai_decision + '</span>';
        }
        reasonHtml += '</div>';
        
        // 量化信号理由
        if (sig.reason) {
            reasonHtml += '<div style="color:#aaa;font-size:12px;line-height:1.6;margin-bottom:6px;"><b>量化:</b> ' + escapeHtml(sig.reason) + '</div>';
        }
        
        // AI审核理由
        if (sig.ai_reason && sig.ai_reason !== '-') {
            reasonHtml += '<div style="color:#5ab2ff;font-size:12px;line-height:1.6;"><b>AI审核:</b> ' + escapeHtml(sig.ai_reason) + '</div>';
        }
        
        if (sig.invalidations && sig.invalidations.length > 0) {
            reasonHtml += '<div style="margin-top:6px;color:#ff5252;font-size:11px;">失效条件: ' + sig.invalidations.join(', ') + '</div>';
        }
        reasonHtml += '</div>';
    }
    if (!reasonHtml) reasonHtml = '<div style="color:#666;padding:20px;text-align:center;">无 reason 数据</div>';
    
    // 原始 content
    var contentRaw = '';
    if (d.response_raw) {
        contentRaw = d.response_raw.content || '';
    }
    
    var requestContent = d.request || '';
    if (typeof requestContent === 'object') requestContent = JSON.stringify(requestContent, null, 2);
    
    var responseContent = d.response_raw || '';
    if (typeof responseContent === 'object') responseContent = JSON.stringify(responseContent, null, 2);
    
    var html = '<div class="detail-header"><div class="detail-title">第 ' + d.round + ' 轮决策 <span style="color:#888;font-weight:normal;">(' + (d.symbols_count || 0) + ' 个币种)</span></div><div class="detail-meta">Signal <span style="color:#ff5252;">' + (d.signal_count || 0) + '</span> · wait <span style="color:#00c853;">' + (d.wait_count || 0) + '</span> · HTTP ' + (d.http_status || 200) + '</div></div>';
    
    html += '<div class="table-wrap signal-table"><table class="data-table"><thead><tr><th>Symbol</th><th>Action</th><th>Entry</th><th>Size</th><th>SL</th><th>TP</th></tr></thead><tbody>' + (rows || '<tr><td colspan="6" style="text-align:center;color:#666;">本次推理无 signals / decision 数据</td></tr>') + '</tbody></table></div>';
    
    html += '<div class="collapsible-section"><div class="collapsible-header" onclick="toggleCollapsible(this)"><span class="arrow">▶</span> 查看每个币种的 reason</div><div class="collapsible-body">' + reasonHtml + '</div></div>';
    
    html += '<div class="collapsible-section"><div class="collapsible-header" onclick="toggleCollapsible(this)"><span class="arrow">▶</span> 查看原始 decision 输出(Response.content)</div><div class="collapsible-body"><pre class="code-block" style="white-space:pre-wrap;word-break:break-all;">' + escapeHtml(contentRaw || '无数据') + '</pre></div></div>';
    
    html += '<div class="collapsible-section"><div class="collapsible-header" onclick="toggleCollapsible(this)"><span class="arrow">▶</span> 投喂内容(Request)</div><div class="collapsible-body"><pre class="code-block" style="white-space:pre-wrap;word-break:break-all;">' + escapeHtml(requestContent || '无数据') + '</pre></div></div>';
    
    html += '<div class="collapsible-section"><div class="collapsible-header" onclick="toggleCollapsible(this)"><span class="arrow">▶</span> 原始输出(Response JSON)</div><div class="collapsible-body"><pre class="code-block" style="white-space:pre-wrap;word-break:break-all;">' + escapeHtml(responseContent || '无数据') + '</pre></div></div>';
    
    wrap.innerHTML = html;
}

function toggleCollapsible(header) {
    var body = header.nextElementSibling;
    var arrow = header.querySelector('.arrow');
    if (body.classList.contains('open')) {
        body.classList.remove('open');
        if (arrow) arrow.textContent = '▶';
    } else {
        body.classList.add('open');
        if (arrow) arrow.textContent = '▼';
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM ready, init...');
    loadDashboard();
    loadAIDecisions();
});
