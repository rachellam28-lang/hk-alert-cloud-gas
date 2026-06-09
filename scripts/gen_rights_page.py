#!/usr/bin/env python3
"""Analyze rights issues/placements for major shareholder benefit + generate HTML"""
import json, re
from datetime import datetime

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# ====== SCORING ENGINE ======
def analyze_benefit(p):
    """Score how much this action benefits major shareholders (0-100)"""
    score = 50  # start neutral
    reasons = []
    warnings = []
    
    cat = p['category']
    method = p['method']
    purpose = p['purpose']
    pct = p['pct_num']
    discount = p.get('discount_pct')  # may be None
    
    # ---- 1. DISCOUNT ANALYSIS (40% weight) ----
    if discount is not None:
        if discount <= -50:
            score += 35; reasons.append(f'超大折讓{discount}%')
        elif discount <= -30:
            score += 25; reasons.append(f'大折讓{discount}%')
        elif discount <= -10:
            score += 15; reasons.append(f'折讓{discount}%')
        elif discount <= 0:
            score += 5; reasons.append(f'輕微折讓{discount}%')
        elif discount <= 10:
            score -= 10; warnings.append(f'溢價+{discount}%')
        else:
            score -= 20; warnings.append(f'大幅溢價+{discount}%')
    else:
        # Estimate based on type
        if cat == '供股':
            score += 20; reasons.append('供股通常折讓發行')
        elif cat == '先舊後新':
            score += 10
    
    # ---- 2. TRANSACTION TYPE (35% weight) ----
    if cat == '先舊後新':
        score += 30; reasons.append('先舊後新=大股東套現機制')
        warnings.append('大股東減持信號')
    elif cat == '供股':
        if '非包銷' in method or '非悉數包銷' in method:
            score += 15; reasons.append('供股(非包銷)')
            warnings.append('無包銷商=散戶風險')
        else:
            score += 20; reasons.append('供股=大股東可按比例認購')
        
        # Check ratio
        ratio = p.get('ratio', '')
        if '一供' in ratio or '1供' in ratio:
            score += 5; reasons.append(f'比例{ratio}=低負擔')
        elif '二供一' in ratio or '2供1' in ratio:
            score += 3
        elif '二供三' in ratio:
            score -= 5; warnings.append(f'{ratio}=高比例供股')
    elif cat == '配售':
        # Check if likely to insiders
        if '擴大資本基礎' in purpose and '償還債務' in purpose:
            score += 5
        else:
            score += 3
    elif cat == '代價發行':
        if '收購' in method:
            score += 20; reasons.append('代價發行收購=可能關連交易')
            warnings.append('需查收購標的係咪大股東資產')
        else:
            score += 10
    
    # CB analysis
    if '換股' in p['type'] or '債券' in p['type']:
        score += 15; reasons.append('CB=低價換股權')
    
    # ---- 3. DILUTION (15% weight) ----
    if pct > 50:
        score -= 15; warnings.append(f'攤薄{pct}%=控制權風險')
    elif pct > 20:
        score -= 5; warnings.append(f'攤薄{pct}%')
    elif pct > 10:
        score += 5
    elif pct > 0:
        score += 8; reasons.append(f'低攤薄{pct}%')
    
    # ---- 4. PURPOSE (10% weight) ----
    if '償還債務' in purpose:
        score -= 5; warnings.append('目的含還債=財困信號')
    if '業務發展' in purpose:
        score += 5
    if '收購項目' in purpose:
        score += 8; reasons.append('用於收購=增長信號')
    
    # ---- CLAMP ----
    score = max(0, min(100, score))
    
    # ---- VERDICT ----
    if score >= 65:
        verdict = '🔥 大股東著數'
        emoji = '🔥'
    elif score >= 45:
        verdict = '⚡ 有機會'
        emoji = '⚡'
    elif score >= 25:
        verdict = '➖ 中性'
        emoji = '➖'
    else:
        verdict = '❄️ 不利'
        emoji = '❄️'
    
    return {
        'score': score,
        'verdict': verdict,
        'emoji': emoji,
        'reasons': reasons[:3],
        'warnings': warnings[:3]
    }

# Run analysis
for p in data:
    p['analysis'] = analyze_benefit(p)

# Stats
verdicts = {}
for p in data:
    v = p['analysis']['verdict']
    verdicts[v] = verdicts.get(v, 0) + 1

print(f"Analysis complete:")
for v, c in sorted(verdicts.items()):
    print(f"  {v}: {c}")

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
<title>供股配股大股東著數分析 — CCASS</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 12px; }}
.nav {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 8px 12px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; position: sticky; top: 0; z-index: 100; }}
.nav a {{ color: #8b949e; text-decoration: none; padding: 4px 10px; border-radius: 4px; font-size: 11px; white-space: nowrap; }}
.nav a:hover, .nav a.active {{ color: #58a6ff; background: #1f2937; }}
.summary {{ display: flex; gap: 10px; padding: 10px 12px; flex-wrap: wrap; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; min-width: 100px; text-align: center; }}
.card .label {{ font-size: 10px; color: #8b949e; }}
.card .value {{ font-size: 18px; font-weight: bold; margin-top: 2px; }}
.card.fire .value {{ color: #f85149; }}
.card.lightning .value {{ color: #d2991d; }}
.card.neutral .value {{ color: #8b949e; }}
.card.ice .value {{ color: #58a6ff; }}
.tabs {{ display: flex; gap: 4px; padding: 0 12px 8px; flex-wrap: wrap; }}
.tab {{ padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 11px; background: #21262d; color: #8b949e; border: 1px solid #30363d; }}
.tab:hover, .tab.active {{ background: #1f6feb; color: #fff; border-color: #1f6feb; }}
.tab .count {{ font-size: 10px; opacity: 0.7; margin-left: 3px; }}
.table-wrap {{ overflow-x: auto; padding: 0 12px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1100px; }}
th {{ background: #161b22; padding: 6px 8px; text-align: left; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; white-space: nowrap; cursor: pointer; }}
th:hover {{ color: #58a6ff; }}
td {{ padding: 4px 8px; border-bottom: 1px solid #21262d; white-space: nowrap; }}
tr:hover td {{ background: #161b22; }}
.badge {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }}
.badge-供股 {{ background: #da3633; color: #fff; }}
.badge-配售 {{ background: #1f6feb; color: #fff; }}
.badge-代價發行 {{ background: #3fb950; color: #000; }}
.badge-先舊後新 {{ background: #d2991d; color: #000; }}
.score-bar {{ display: inline-block; height: 14px; border-radius: 3px; min-width: 2px; vertical-align: middle; margin-right: 4px; }}
.score-high {{ background: #3fb950; }}
.score-mid {{ background: #d2991d; }}
.score-low {{ background: #f85149; }}
.verdict {{ font-weight: 600; font-size: 11px; }}
.verdict-fire {{ color: #f85149; }}
.verdict-lightning {{ color: #d2991d; }}
.verdict-neutral {{ color: #8b949e; }}
.verdict-ice {{ color: #58a6ff; }}
.tooltip {{ cursor: help; border-bottom: 1px dotted #8b949e; }}
.footer {{ padding: 12px; text-align: center; color: #484f58; font-size: 10px; border-top: 1px solid #21262d; margin-top: 10px; }}
@media (max-width: 720px) {{
  body {{ font-size: 10px; }}
  .summary {{ gap: 6px; padding: 6px; }}
  .card {{ min-width: 60px; padding: 6px 8px; }}
  .card .value {{ font-size: 13px; }}
  th, td {{ padding: 3px 4px; font-size: 10px; }}
  table {{ min-width: 900px; }}
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
  <div class="card fire"><div class="label">🔥 大股東著數</div><div class="value">{verdicts.get('🔥 大股東著數',0)}</div></div>
  <div class="card lightning"><div class="label">⚡ 有機會</div><div class="value">{verdicts.get('⚡ 有機會',0)}</div></div>
  <div class="card neutral"><div class="label">➖ 中性</div><div class="value">{verdicts.get('➖ 中性',0)}</div></div>
  <div class="card ice"><div class="label">❄️ 不利</div><div class="value">{verdicts.get('❄️ 不利',0)}</div></div>
  <div class="card"><div class="label">💰 總集資</div><div class="value" style="color:#d2991d">{total_amount/1e8:.0f}億</div></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="filter('all')">全部<span class="count">{len(data)}</span></div>
  <div class="tab" onclick="filter('🔥 大股東著數')">🔥 著數<span class="count">{verdicts.get('🔥 大股東著數',0)}</span></div>
  <div class="tab" onclick="filter('⚡ 有機會')">⚡ 有機會<span class="count">{verdicts.get('⚡ 有機會',0)}</span></div>
  <div class="tab" onclick="filter('供股')">供股<span class="count">{cats.get('供股',{}).get('count',0)}</span></div>
  <div class="tab" onclick="filter('配售')">配售<span class="count">{cats.get('配售',{}).get('count',0)}</span></div>
  <div class="tab" onclick="filter('先舊後新')">先舊後新<span class="count">{cats.get('先舊後新',{}).get('count',0)}</span></div>
</div>

<div style="padding:0 12px 6px">
  <input type="text" placeholder="🔍 搜股票代碼或名稱..." oninput="doSearch(this)"
   style="background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:5px 10px;font-size:11px;width:200px;outline:none"
   onfocus="this.style.borderColor='#58a6ff'" onblur="this.style.borderColor='#30363d'">
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
  <th onclick="sortTable(6)">折讓%</th>
  <th onclick="sortTable(7)">集資額</th>
  <th onclick="sortTable(8)">攤薄%</th>
  <th onclick="sortTable(9)">著數分</th>
  <th>分析</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>

<div class="footer">
  🤖 AI 分析僅供參考，不構成投資建議 | 數據: etnet 經濟通 + westock-data | {len(data)}項 | score≥65=🔥 40-64=⚡ 25-39=➖ <25=❄️
</div>

<script>
const DATA = {data_json};

function fmtAmt(n) {{
  if (n >= 1e8) return (n/1e8).toFixed(1)+'億';
  if (n >= 1e7) return (n/1e7).toFixed(0)+'千萬';
  if (n >= 1e6) return (n/1e6).toFixed(0)+'百萬';
  return String(n);
}}

function render(rows) {{
  document.getElementById('tableBody').innerHTML = rows.map(d => {{
    let a = d.analysis || {{}};
    let score = a.score || 0;
    let barColor = score >= 65 ? 'score-high' : score >= 40 ? 'score-mid' : 'score-low';
    let vClass = score >= 65 ? 'verdict-fire' : score >= 40 ? 'verdict-lightning' : score >= 25 ? 'verdict-neutral' : 'verdict-ice';
    let mp = d.market_price > 0 ? d.market_price.toFixed(2) : '-';
    let disc = d.discount_pct != null ? (d.discount_pct <= 0 ? d.discount_pct+'%' : '+'+d.discount_pct+'%') : '-';
    let discColor = d.discount_pct != null ? (d.discount_pct <= -30 ? 'color:#3fb950;font-weight:bold' : d.discount_pct <= 0 ? 'color:#3fb950' : 'color:#f85149') : '';
    let reasons = (a.reasons||[]).join('；');
    let warnings = (a.warnings||[]).join('；');
    let tooltip = (reasons ? '👍 '+reasons : '') + (warnings ? ' ⚠ '+warnings : '');
    
    return `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name}}</td>
      <td><span class="badge badge-${{d.category}}">${{d.category}}</span></td>
      <td>${{d.price}}</td>
      <td>${{mp}}</td>
      <td style="${{discColor}}">${{disc}}</td>
      <td>${{fmtAmt(d.amount_num)}}</td>
      <td>${{d.pct_num > 0 ? d.pct_num.toFixed(1)+'%' : '-'}}</td>
      <td><span class="score-bar ${{barColor}}" style="width:${{Math.min(score,100)}}px"></span><b>${{score}}</b></td>
      <td class="tooltip" title="${{tooltip}}"><span class="verdict ${{vClass}}">${{a.emoji||'➖'}} ${{a.verdict||'待分析'}}</span></td>
    </tr>`;
  }}).join('');
}}

let searchTerm = '';
let currentFilter = 'all';

function getFilteredRows() {{
  let rows = DATA;
  if (currentFilter !== 'all') {{
    if (['🔥 大股東著數','⚡ 有機會','➖ 中性','❄️ 不利'].includes(currentFilter))
      rows = rows.filter(d => (d.analysis||{{}}).verdict === currentFilter);
    else
      rows = rows.filter(d => d.category === currentFilter);
  }}
  if (searchTerm) {{
    let s = searchTerm.toLowerCase();
    rows = rows.filter(d => d.code.includes(s) || d.name.toLowerCase().includes(s));
  }}
  return rows;
}}

function applyFilters() {{
  render(getFilteredRows());
}}

function doSearch(el) {{
  searchTerm = el.value.trim();
  applyFilters();
}}

function filter(cat) {{
  currentFilter = cat;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  applyFilters();
}}

let sortCol = 9; let sortAsc = true; // default: sort by score desc
function sortTable(col) {{
  sortAsc = sortCol === col ? !sortAsc : (col === 9 ? true : false);
  sortCol = col;
  let rows = getFilteredRows();
  const keys = ['date_parsed','code','name','category','price_num','market_price','discount_pct','amount_num','pct_num','analysis_score'];
  
  rows.sort((a,b) => {{
    let va, vb;
    if (col === 9) {{ va = (a.analysis||{{}}).score||0; vb = (b.analysis||{{}}).score||0; }}
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
print("Columns: 日期 | 代碼 | 名稱 | 類別 | 配售價 | 市價 | 折讓% | 集資額 | 攤薄% | 著數分 | 分析")
