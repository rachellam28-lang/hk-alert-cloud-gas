#!/usr/bin/env python3
"""Generate rights_analysis.html — TRADING FOCUS: 炒唔炒?"""
import json, re

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# ====== TRADING SCORING ======
def trade_signal(p):
    """Return: signal (🟢/🟡/🔴), score, thesis, entry, risk"""
    cat = p['category']
    purpose = p['purpose']
    pct = p['pct_num']
    discount = p.get('discount_pct')
    price_num = p['price_num']
    market_price = p.get('market_price', 0)
    method = p['method']
    
    score = 0
    reasons = []
    risks = []
    thesis_parts = []
    
    # === 1. 大股東動機 (有冇誘因推高股價?) ===
    if cat == '先舊後新':
        score += 25
        thesis_parts.append('先舊後新: 大股東先沽後配')
        reasons.append('大股東沽貨套現=股價短期有壓')
        if market_price > 0 and price_num > 0:
            if price_num < market_price * 0.9:
                score += 10
                thesis_parts.append(f'配股價{price_num}低過市價{market_price:.2f}=新買家有著數')
            else:
                risks.append(f'配股價接近市價=新買家冇肉食')
    
    elif cat == '供股':
        if market_price > 0 and price_num > 0:
            discount_pct = (price_num / market_price - 1) * 100
            if discount_pct < -30:
                score += 30
                thesis_parts.append(f'供股價{price_num}大折讓{abs(discount_pct):.0f}% vs 市價{market_price:.2f}')
                reasons.append('大股東供股後有強烈動機炒高股價')
            elif discount_pct < -10:
                score += 20
                thesis_parts.append(f'供股價{price_num}折讓{abs(discount_pct):.0f}%')
            else:
                score += 5
                risks.append(f'供股價接近市價=散戶唔會供')
        else:
            score += 20
            thesis_parts.append('供股=大股東按比例認購')
            reasons.append('供股價一般大折讓=供完會炒上')
        
        if '非包銷' in method:
            risks.append('冇包銷商=散戶要自己啃')
        if pct > 50:
            score -= 10
            risks.append(f'攤薄{pct}%=貨源大增')
    
    elif cat == '配售':
        if market_price > 0 and price_num > 0:
            disc = (price_num / market_price - 1) * 100
            if disc < -30:
                score += 15
                thesis_parts.append(f'大折讓{abs(disc):.0f}%配售=接貨者要炒上先賺')
            elif disc < -15:
                score += 20
                thesis_parts.append(f'折讓{abs(disc):.0f}%配售=新資金有信心')
            elif disc <= 0:
                # Narrow discount (0-15%): STRONG conviction signal for small caps
                score += 30
                thesis_parts.append(f'窄折讓只得{abs(disc):.0f}%=接貨者極度看好')
                reasons.append('有人肯以接近市價接貨=強烈看好信號')
            elif disc <= 10:
                score += 5
            else:
                score -= 15
                risks.append(f'溢價配售=冇人會接')
        else:
            score += 10
            thesis_parts.append('配售新股=有資金發展')
        
        # Debt repayment: NEUTRAL (can be positive — cleans up balance sheet)
        if '償還債務' in purpose:
            score += 3
            thesis_parts.append('配股清債=移除財困炸彈')
        if '業務發展' in purpose:
            score += 5
            thesis_parts.append('資金用於業務發展')
    
    elif cat == '代價發行':
        if '收購' in method:
            score += 15
            thesis_parts.append('發股收購=可能注入資產')
            reasons.append('收購成功後基本因素改善')
        else:
            score += 5
        
        if market_price > 0 and price_num > 0:
            if price_num > market_price * 2:
                score -= 20
                risks.append(f'發行價{price_num}遠高於市價{market_price:.2f}=假大空')
    
    # === 2. 攤薄影響 ===
    if pct > 50:
        score -= 20
        risks.append(f'攤薄>{pct}%=貨源暴增,炒上極難')
    elif pct > 20:
        score -= 8
        risks.append(f'攤薄{pct}%=沽壓大')
    elif pct > 10:
        score -= 3
    
    # === 3. 貸款資本化信號 ===
    if '貸款資本化' in method:
        score -= 15
        risks.append('貸款變股票=債主走佬')
    
    # === 4. CB convertible bonds ===
    if '換股' in p['type'] or '債券' in p['type']:
        score += 5
        thesis_parts.append('CB日後換股=有托價誘因')
        risks.append('CB換股時會有攤薄')
    
    # === FINAL VERDICT ===
    score = max(-50, min(100, score + 40))  # rebase
    
    if score >= 58:
        signal = '🟢 炒'
        sig_class = 'trade-buy'
        action = '炒得過'
    elif score >= 35:
        signal = '🟡 等'
        sig_class = 'trade-wait'
        action = '睇定D'
    else:
        signal = '🔴 避'
        sig_class = 'trade-avoid'
        action = '咪搞'
    
    thesis = '；'.join(thesis_parts) if thesis_parts else f'{cat}=需更多數據判斷'
    
    return {
        'score': score,
        'signal': signal,
        'sig_class': sig_class,
        'action': action,
        'thesis': thesis,
        'reasons': reasons[:2],
        'risks': risks[:2],
    }

for p in data:
    p['trade'] = trade_signal(p)

# Stats
signals = {}
for p in data:
    s = p['trade']['signal']
    signals[s] = signals.get(s, 0) + 1

print("Trading signals:")
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

html = f'''<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=0.3, maximum-scale=1.0, user-scalable=yes">
<title>供配股炒作訊號 — CCASS</title>
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
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1000px; }}
th {{ background: #161b22; padding: 6px 8px; text-align: left; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; white-space: nowrap; cursor: pointer; }}
th:hover {{ color: #58a6ff; }}
td {{ padding: 4px 8px; border-bottom: 1px solid #21262d; white-space: nowrap; }}
tr:hover td {{ background: #161b22; }}
.badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }}
.badge-供股 {{ background: #da3633; color: #fff; }}
.badge-配售 {{ background: #1f6feb; color: #fff; }}
.badge-代價發行 {{ background: #3fb950; color: #000; }}
.badge-先舊後新 {{ background: #d2991d; color: #000; }}
.signal {{ font-weight: 700; font-size: 12px; padding: 2px 6px; border-radius: 3px; }}
.trade-buy {{ background: #1a3a1a; color: #3fb950; }}
.trade-wait {{ background: #3a2e0a; color: #d2991d; }}
.trade-avoid {{ background: #3a1111; color: #f85149; }}
.thesis {{ max-width: 250px; overflow: hidden; text-overflow: ellipsis; color: #8b949e; font-size: 10px; }}
.reason {{ color: #3fb950; font-size: 10px; }}
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
  <div class="card buy"><div class="label">🟢 炒得過</div><div class="value">{signals.get('🟢 炒',0)}</div></div>
  <div class="card wait"><div class="label">🟡 睇定D</div><div class="value">{signals.get('🟡 等',0)}</div></div>
  <div class="card avoid"><div class="label">🔴 咪搞</div><div class="value">{signals.get('🔴 避',0)}</div></div>
  <div class="card"><div class="label">📊 總事件</div><div class="value">{len(data)}</div></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="filter('all')">全部<span class="count">{len(data)}</span></div>
  <div class="tab" onclick="filter('🟢 炒')">🟢 炒得過<span class="count">{signals.get('🟢 炒',0)}</span></div>
  <div class="tab" onclick="filter('🟡 等')">🟡 睇定D<span class="count">{signals.get('🟡 等',0)}</span></div>
  <div class="tab" onclick="filter('🔴 避')">🔴 咪搞<span class="count">{signals.get('🔴 避',0)}</span></div>
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
  <th onclick="sortTable(0)" style="width:75px">日期</th>
  <th onclick="sortTable(1)" style="width:55px">代碼</th>
  <th onclick="sortTable(2)" style="width:80px">名稱</th>
  <th onclick="sortTable(3)" style="width:60px">類別</th>
  <th onclick="sortTable(4)" style="width:65px">配售價</th>
  <th onclick="sortTable(5)" style="width:55px">市價</th>
  <th onclick="sortTable(6)" style="width:55px">折讓</th>
  <th onclick="sortTable(7)" style="width:60px">集資</th>
  <th onclick="sortTable(8)" style="width:55px">攤薄</th>
  <th onclick="sortTable(9)" style="width:70px">評級</th>
  <th>炒作邏輯</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>

<div class="footer">
  🟢=大股東有動機炒高 | 🟡=有機會但要等信號 | 🔴=大股東走佬/財困勿掂 | 數據: etnet + westock-data
</div>

<script>
const DATA = {data_json};

function fmtAmt(n) {{
  if (n >= 1e8) return (n/1e8).toFixed(1)+'億';
  if (n >= 1e7) return (n/1e7).toFixed(0)+'千萬';
  if (n >= 1e6) return (n/1e6).toFixed(0)+'百萬';
  return n ? String(n) : '-';
}}

function render(rows) {{
  document.getElementById('tableBody').innerHTML = rows.map(d => {{
    let t = d.trade || {{}};
    let mp = d.market_price > 0 ? d.market_price.toFixed(2) : '-';
    let disc = d.discount_pct != null ? (d.discount_pct <= 0 ? d.discount_pct+'%' : '+'+d.discount_pct+'%') : '-';
    let discStyle = d.discount_pct != null ? (d.discount_pct <= -20 ? 'color:#3fb950;font-weight:bold' : d.discount_pct <= 0 ? 'color:#3fb950' : 'color:#f85149') : '';
    let reasons = (t.reasons||[]).map(r => '<div class="reason">👍 '+r+'</div>').join('');
    let risks = (t.risks||[]).map(r => '<div class="risk">⚠ '+r+'</div>').join('');
    
    return `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name}}</td>
      <td><span class="badge badge-${{d.category}}">${{d.category}}</span></td>
      <td>${{d.price}}</td>
      <td>${{mp}}</td>
      <td style="${{discStyle}}">${{disc}}</td>
      <td class="money">${{fmtAmt(d.amount_num)}}</td>
      <td>${{d.pct_num > 0 ? d.pct_num.toFixed(1)+'%' : '-'}}</td>
      <td><span class="signal ${{t.sig_class||''}}">${{t.signal||'➖'}}</span></td>
      <td>
        <div class="thesis" title="${{t.thesis||''}}">${{t.thesis||'待分析'}}</div>
        ${{reasons}}${{risks}}
      </td>
    </tr>`;
  }}).join('');
}}

let searchTerm = '';
let currentFilter = 'all';

function getFilteredRows() {{
  let rows = DATA;
  if (currentFilter !== 'all') {{
    if (['🟢 炒','🟡 等','🔴 避'].includes(currentFilter))
      rows = rows.filter(d => (d.trade||{{}}).signal === currentFilter);
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

let sortCol = 0; let sortAsc = false;
function sortTable(col) {{
  sortAsc = sortCol === col ? !sortAsc : false;
  sortCol = col;
  let rows = getFilteredRows();
  const keys = ['date_parsed','code','name','category','price_num','market_price','discount_pct','amount_num','pct_num'];
  rows.sort((a,b) => {{
    let va, vb;
    if (col === 9) {{ va = (a.trade||{{}}).score||0; vb = (b.trade||{{}}).score||0; }}
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
