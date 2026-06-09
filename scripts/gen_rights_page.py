#!/usr/bin/env python3
"""Generate rights_analysis.html — v3: 跟聰明錢邏輯"""
import json, re

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Pre-compute per-stock stats for pattern detection
stock_events = {}
for p in data:
    code = p['code']
    if code not in stock_events:
        stock_events[code] = []
    stock_events[code].append(p)

# ====== V3: 跟聰明錢 + 財技模式 ======
def trade_signal(p, all_data=data, stocks=stock_events):
    """
    核心理念: 有人用真金白銀接貨 → 跟佢
    折讓愈窄 = 信心愈強
    08120 教訓: 窄折讓配售 = 爆升前兆
    """
    cat = p['category']
    purpose = p['purpose']
    pct = p['pct_num']
    price_num = p['price_num']
    market_price = p.get('market_price', 0)
    method = p['method']
    
    discount = None
    if market_price > 0 and price_num > 0:
        discount = (price_num / market_price - 1) * 100
    
    conviction = 0  # 0-3 stars
    thesis = []
    risks = []
    
    # ===== STEP 1: 折讓 → 信心度 =====
    if discount is not None:
        if discount <= -50:
            conviction = -1
            thesis.append(f'超大折讓{abs(discount):.0f}%=可能財困')
            risks.append('折讓太大=散貨格')
        elif discount <= -25:
            conviction = 0
            thesis.append(f'大折讓{abs(discount):.0f}%')
        elif discount <= -15:
            conviction = 1
            thesis.append(f'折讓{abs(discount):.0f}%')
        elif discount <= -5:
            conviction = 2
            thesis.append(f'窄折讓{abs(discount):.0f}%=高信心接貨')
        elif discount <= 0:
            conviction = 3
            thesis.append(f'極窄折讓{abs(discount):.0f}%❗=超高信心')
        elif discount <= 10:
            conviction = 0
            thesis.append(f'輕微溢價+{discount:.0f}%')
        else:
            conviction = -2
            thesis.append(f'大幅溢價+{discount:.0f}%=假大空')
            risks.append('溢價發行=冇人會接')
    else:
        conviction = 1  # default neutral
    
    # ===== STEP 2: 交易類別加成 =====
    if cat == '先舊後新':
        conviction += 1
        thesis.insert(0, '🔄 先舊後新套利格局')
    elif cat == '供股':
        if discount and discount < -30:
            conviction += 2
            thesis.insert(0, '📋 大折讓供股=大股東供完要炒上')
            risks.append('供股價極低=散戶被迫供')
        elif '非包銷' in method:
            conviction -= 1
            risks.append('冇包銷商=供股隨時失敗')
        else:
            conviction += 1
            thesis.insert(0, '📋 供股=大股東會托價')
    elif cat == '配售':
        # 配售 is neutral — conviction already captured by discount
        if '償還債務' in purpose:
            thesis.append('💰 清債=拆彈')
        if '業務發展' in purpose:
            thesis.append('📈 資金擴張')
    elif cat == '代價發行':
        if '收購' in method:
            conviction += 1
            thesis.insert(0, '🤝 發股收購')
        else:
            conviction -= 1
            thesis.insert(0, '📄 代價發行')
    
    # ===== STEP 3: 風險扣分 =====
    if pct > 50:
        conviction -= 2
        risks.append(f'攤薄>{pct}%=貨源太多')
    elif pct > 30:
        conviction -= 1
        risks.append(f'攤薄{pct}%')
    
    if '貸款資本化' in method:
        conviction -= 2
        risks.append('💀 債轉股=債主準備走佬')
    
    if '換股' in p['type'] or '債券' in p['type']:
        thesis.append('🔮 CB=日後換股有托價誘因')
        risks.append('CB換股時有新貨源')
    
    # ===== 財技模式檢測 =====
    code = p['code']
    events = stocks.get(code, [])
    event_count = len(events)
    
    # Pattern A: 多輪發股洗名冊 (≥3 events in dataset = active issuer)
    if event_count >= 3:
        conviction += 1
        thesis.append(f'🔄 模式A: {event_count}輪發股洗名冊')
        # Check time span
        dates = sorted([e['date_parsed'] for e in events])
        if len(dates) >= 2:
            from datetime import datetime
            d1 = datetime.strptime(dates[0], '%Y-%m-%d')
            d2 = datetime.strptime(dates[-1], '%Y-%m-%d')
            months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
            if months <= 6:
                conviction += 1
                thesis.append(f'{months}個月內密集發股=準備炒上')
    
    # Pattern B: 供股+配股組合拳 (same stock has both types)
    has_rights = any(e['category'] == '供股' for e in events)
    has_placing = any(e['category'] == '配售' for e in events)
    if has_rights and has_placing and event_count >= 2:
        # Check if 供股 has deep discount
        rights_events = [e for e in events if e['category'] == '供股']
        for re_ev in rights_events:
            rd = re_ev.get('discount_pct')
            if rd is not None and rd < -20:
                conviction += 2
                thesis.append('🎯 模式B: 大折讓供股+配股組合拳')
                risks.append('組合拳=莊家佈局信號')
                break
    
    # ===== FINAL VERDICT =====
    if conviction >= 3:
        signal = '🟢 跟!'
        sig_class = 'trade-buy'
        verdict_text = '強烈跟進'
    elif conviction >= 2:
        signal = '🟢 跟'
        sig_class = 'trade-buy'
        verdict_text = '可以跟'
    elif conviction >= 0:
        signal = '🟡 等'
        sig_class = 'trade-wait'
        verdict_text = '睇定D'
    elif conviction >= -1:
        signal = '🔴 避'
        sig_class = 'trade-avoid'
        verdict_text = '避開'
    else:
        signal = '💀 走'
        sig_class = 'trade-avoid'
        verdict_text = '快走'
    
    return {
        'conviction': conviction,
        'signal': signal,
        'sig_class': sig_class,
        'verdict_text': verdict_text,
        'thesis': ' | '.join(thesis),
        'risks': risks[:3],
    }

for p in data:
    p['trade'] = trade_signal(p)

signals = {}
for p in data:
    s = p['trade']['signal']
    signals[s] = signals.get(s, 0) + 1

print("V3 Signals:")
for s, c in sorted(signals.items()):
    print(f"  {s}: {c}")

# ====== GENERATE HTML ======
data_json = json.dumps(data, ensure_ascii=False)
total_amount = sum(d['amount_num'] for d in data)

cats = {}
for d in data:
    c = d['category']
    if c not in cats: cats[c] = {'count': 0, 'amount': 0}
    cats[c]['count'] += 1
    cats[c]['amount'] += d['amount_num']

# Count signals for display
g_count = signals.get('🟢 跟!', 0) + signals.get('🟢 跟', 0)
y_count = signals.get('🟡 等', 0)
r_count = signals.get('🔴 避', 0) + signals.get('💀 走', 0)

html = f'''<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=0.3, maximum-scale=1.0, user-scalable=yes">
<title>供配股跟蹤器 — 跟聰明錢</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 12px; }}
.nav {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 8px 12px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; position: sticky; top: 0; z-index: 100; }}
.nav a {{ color: #8b949e; text-decoration: none; padding: 4px 10px; border-radius: 4px; font-size: 11px; white-space: nowrap; }}
.nav a:hover, .nav a.active {{ color: #58a6ff; background: #1f2937; }}
.summary {{ display: flex; gap: 10px; padding: 10px 12px; flex-wrap: wrap; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; min-width: 90px; text-align: center; }}
.card .label {{ font-size: 10px; color: #8b949e; }}
.card .value {{ font-size: 20px; font-weight: bold; margin-top: 2px; }}
.card.buy {{ border-color: #3fb950; }}
.card.buy .value {{ color: #3fb950; }}
.card.wait {{ border-color: #d2991d; }}
.card.wait .value {{ color: #d2991d; }}
.card.avoid {{ border-color: #f85149; }}
.card.avoid .value {{ color: #f85149; }}
.tabs {{ display: flex; gap: 4px; padding: 0 12px 8px; flex-wrap: wrap; }}
.tab {{ padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 11px; background: #21262d; color: #8b949e; border: 1px solid #30363d; }}
.tab:hover, .tab.active {{ background: #1f6feb; color: #fff; border-color: #1f6feb; }}
.tab .count {{ font-size: 10px; opacity: 0.7; margin-left: 3px; }}
.search-box {{ padding: 0 12px 6px; }}
.search-box input {{ background: #161b22; color: #c9d1d9; border: 1px solid #30363d; border-radius: 4px; padding: 5px 10px; font-size: 11px; width: 200px; outline: none; }}
.search-box input:focus {{ border-color: #58a6ff; }}
.table-wrap {{ overflow-x: auto; padding: 0 12px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 950px; }}
th {{ background: #161b22; padding: 6px 8px; text-align: left; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; white-space: nowrap; cursor: pointer; }}
th:hover {{ color: #58a6ff; }}
td {{ padding: 4px 8px; border-bottom: 1px solid #21262d; white-space: nowrap; }}
tr:hover td {{ background: #161b22; }}
.badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }}
.badge-供股 {{ background: #da3633; color: #fff; }}
.badge-配售 {{ background: #1f6feb; color: #fff; }}
.badge-代價發行 {{ background: #3fb950; color: #000; }}
.badge-先舊後新 {{ background: #d2991d; color: #000; }}
.signal {{ font-weight: 700; font-size: 12px; padding: 3px 8px; border-radius: 4px; text-align: center; display: inline-block; min-width: 55px; }}
.trade-buy {{ background: #1a3a1a; color: #3fb950; border: 1px solid #3fb950; }}
.trade-wait {{ background: #3a2e0a; color: #d2991d; border: 1px solid #d2991d; }}
.trade-avoid {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.conviction {{ display: inline-flex; gap: 2px; }}
.conviction span {{ font-size: 14px; }}
.thesis {{ max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: #8b949e; font-size: 10px; white-space: normal; }}
.risk {{ color: #f85149; font-size: 10px; }}
.money {{ color: #d2991d; }}
.footer {{ padding: 12px; text-align: center; color: #484f58; font-size: 10px; border-top: 1px solid #21262d; margin-top: 10px; }}
@media (max-width: 720px) {{
  body {{ font-size: 10px; }}
  .summary {{ gap: 6px; padding: 6px; }}
  .card {{ min-width: 55px; padding: 6px 8px; }}
  .card .value {{ font-size: 14px; }}
  th, td {{ padding: 3px 4px; font-size: 10px; }}
  table {{ min-width: 800px; }}
}}
</style>
</head>
<body>

<div class="nav">
  <a href="index.html">🇭🇰 港股版</a>
  <a href="watchlist.html">⭐ 自選</a>
  <a href="history.html">🕐 歷史</a>
  <a href="gap_fvg.html">⤴ Gap/FVG</a>
  <a href="fundflow.html">💰 資金</a>
  <a href="rights_analysis.html" class="active">📋 供配股</a>
  <a href="guide.html">📖 說明書</a>
</div>

<div class="summary">
  <div class="card buy"><div class="label">🟢 跟!</div><div class="value">{g_count}</div></div>
  <div class="card wait"><div class="label">🟡 等</div><div class="value">{y_count}</div></div>
  <div class="card avoid"><div class="label">🔴 避</div><div class="value">{r_count}</div></div>
  <div class="card"><div class="label">💡 核心理念</div><div class="value" style="font-size:11px;color:#58a6ff">折讓窄=信心強=跟!</div></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="filter('all')">全部<span class="count">{len(data)}</span></div>
  <div class="tab" onclick="filter('🟢')">🟢 跟<span class="count">{g_count}</span></div>
  <div class="tab" onclick="filter('🟡')">🟡 等<span class="count">{y_count}</span></div>
  <div class="tab" onclick="filter('🔴')">🔴 避<span class="count">{r_count}</span></div>
  <div class="tab" onclick="filter('供股')">供股<span class="count">{cats.get('供股',{}).get('count',0)}</span></div>
  <div class="tab" onclick="filter('先舊後新')">先舊後新<span class="count">{cats.get('先舊後新',{}).get('count',0)}</span></div>
</div>

<div class="search-box">
  <input type="text" placeholder="🔍 股票代碼或名稱..." oninput="doSearch(this)">
</div>

<div class="table-wrap">
<table id="mainTable">
<thead>
<tr>
  <th onclick="sortTable(0)">日期</th>
  <th onclick="sortTable(1)">代碼</th>
  <th onclick="sortTable(2)">名稱</th>
  <th onclick="sortTable(3)">類別</th>
  <th onclick="sortTable(4)">配售價</th>
  <th onclick="sortTable(5)">市價</th>
  <th onclick="sortTable(6)">折讓</th>
  <th onclick="sortTable(7)">攤薄</th>
  <th onclick="sortTable(8)">信心度</th>
  <th onclick="sortTable(9)">訊號</th>
  <th>邏輯</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>

<div class="footer">
  💡 折讓愈窄=接貨者愈有信心=愈值得跟 | 08120 案例: 折讓12%配售後一個月爆升318% | 數據: etnet + westock-data
</div>

<script>
const DATA = {data_json};

function fmtAmt(n) {{
  if (n >= 1e8) return (n/1e8).toFixed(1)+'億';
  if (n >= 1e7) return (n/1e7).toFixed(0)+'千萬';
  return n ? String(n) : '-';
}}

function render(rows) {{
  document.getElementById('tableBody').innerHTML = rows.map(d => {{
    let t = d.trade || {{}};
    let mp = d.market_price > 0 ? d.market_price.toFixed(2) : '-';
    let disc = d.discount_pct != null ? (d.discount_pct <= 0 ? d.discount_pct+'%' : '+'+d.discount_pct+'%') : '-';
    let discStyle = '';
    if (d.discount_pct != null) {{
      if (d.discount_pct <= -15) discStyle = 'color:#3fb950;font-weight:bold';  // tight = green
      else if (d.discount_pct <= 0) discStyle = 'color:#3fb950';
      else discStyle = 'color:#f85149';
    }}
    
    // Conviction stars
    let c = t.conviction || 0;
    let stars = '';
    if (c >= 3) stars = '⭐⭐⭐';
    else if (c >= 2) stars = '⭐⭐';
    else if (c >= 1) stars = '⭐';
    else if (c >= 0) stars = '—';
    else if (c >= -1) stars = '⚠';
    else stars = '💀';
    
    let risks = (t.risks||[]).map(r => '<div class="risk">'+r+'</div>').join('');
    
    return `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name}}</td>
      <td><span class="badge badge-${{d.category}}">${{d.category}}</span></td>
      <td>${{d.price}}</td>
      <td>${{mp}}</td>
      <td style="${{discStyle}}">${{disc}}</td>
      <td>${{d.pct_num > 0 ? d.pct_num.toFixed(1)+'%' : '-'}}</td>
      <td><span class="conviction">${{stars}}</span></td>
      <td><span class="signal ${{t.sig_class||''}}">${{t.signal||'➖'}}</span></td>
      <td>
        <div class="thesis">${{t.thesis||''}}</div>
        ${{risks}}
      </td>
    </tr>`;
  }}).join('');
}}

let searchTerm = '';
let currentFilter = 'all';

function getFilteredRows() {{
  let rows = DATA;
  if (currentFilter !== 'all') {{
    if (currentFilter === '🟢')
      rows = rows.filter(d => (d.trade||{{}}).signal.startsWith('🟢'));
    else if (currentFilter === '🟡')
      rows = rows.filter(d => (d.trade||{{}}).signal.startsWith('🟡'));
    else if (currentFilter === '🔴')
      rows = rows.filter(d => (d.trade||{{}}).signal.startsWith('🔴') || (d.trade||{{}}).signal.startsWith('💀'));
    else
      rows = rows.filter(d => d.category === currentFilter);
  }}
  if (searchTerm) {{
    let s = searchTerm.toLowerCase();
    rows = rows.filter(d => d.code.includes(s) || d.name.toLowerCase().includes(s));
  }}
  return rows;
}}

function doSearch(el) {{ searchTerm = el.value.trim(); render(getFilteredRows()); }}

function filter(cat) {{
  currentFilter = cat;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  render(getFilteredRows());
}}

let sortCol = 8; let sortAsc = false;
function sortTable(col) {{
  sortAsc = sortCol === col ? !sortAsc : (col === 8 ? false : false);
  sortCol = col;
  let rows = getFilteredRows();
  const keys = ['date_parsed','code','name','category','price_num','market_price','discount_pct','pct_num'];
  rows.sort((a,b) => {{
    let va, vb;
    if (col === 8) {{ va = (a.trade||{{}}).conviction||0; vb = (b.trade||{{}}).conviction||0; }}
    else if (col === 6) {{ va = a.discount_pct != null ? a.discount_pct : 999; vb = b.discount_pct != null ? b.discount_pct : 999; }}
    else if (col === 5) {{ va = a.market_price||0; vb = b.market_price||0; }}
    else {{ va = a[keys[col]]||''; vb = b[keys[col]]||''; }}
    if (typeof va === 'number') return sortAsc ? va - vb : vb - va;
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  }});
  render(rows);
}}

render(DATA);
</script>
</body>
</html>'''

with open('rights_analysis.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\nGenerated rights_analysis.html ({len(html)} bytes)")
