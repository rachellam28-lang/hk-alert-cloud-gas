#!/usr/bin/env python3
"""Generate rights_analysis.html from placements_enriched.json"""
import json

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Convert amounts for display
def fmt_amount(n):
    if n >= 1e8:
        return f'{n/1e8:.1f}億'
    elif n >= 1e7:
        return f'{n/1e7:.0f}千萬'
    elif n >= 1e6:
        return f'{n/1e6:.0f}百萬'
    elif n >= 1e4:
        return f'{n/1e4:.0f}萬'
    return str(int(n))

# Summary stats
total_amount = sum(d['amount_num'] for d in data)
cats = {}
for d in data:
    c = d['category']
    if c not in cats:
        cats[c] = {'count': 0, 'amount': 0}
    cats[c]['count'] += 1
    cats[c]['amount'] += d['amount_num']

data_json = json.dumps(data, ensure_ascii=False)

html = f'''<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=0.3, maximum-scale=1.0, user-scalable=yes">
<title>供股配股分析 — CCASS Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 12px; }}
.nav {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 8px 12px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; position: sticky; top: 0; z-index: 100; }}
.nav a {{ color: #8b949e; text-decoration: none; padding: 4px 10px; border-radius: 4px; font-size: 11px; white-space: nowrap; }}
.nav a:hover, .nav a.active {{ color: #58a6ff; background: #1f2937; }}
.summary {{ display: flex; gap: 10px; padding: 10px 12px; flex-wrap: wrap; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; min-width: 120px; }}
.card .label {{ font-size: 10px; color: #8b949e; }}
.card .value {{ font-size: 18px; font-weight: bold; margin-top: 2px; }}
.card.red .value {{ color: #f85149; }}
.card.green .value {{ color: #3fb950; }}
.card.yellow .value {{ color: #d2991d; }}
.card.blue .value {{ color: #58a6ff; }}
.tabs {{ display: flex; gap: 4px; padding: 0 12px 8px; flex-wrap: wrap; }}
.tab {{ padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 11px; background: #21262d; color: #8b949e; border: 1px solid #30363d; }}
.tab:hover, .tab.active {{ background: #1f6feb; color: #fff; border-color: #1f6feb; }}
.tab .count {{ font-size: 10px; opacity: 0.7; margin-left: 3px; }}
.table-wrap {{ overflow-x: auto; padding: 0 12px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1000px; }}
th {{ background: #161b22; padding: 6px 8px; text-align: left; border-bottom: 2px solid #30363d; color: #8b949e; font-weight: 600; white-space: nowrap; cursor: pointer; position: sticky; top: 0; }}
th:hover {{ color: #58a6ff; }}
td {{ padding: 4px 8px; border-bottom: 1px solid #21262d; white-space: nowrap; }}
tr:hover td {{ background: #161b22; }}
.badge {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }}
.badge-供股 {{ background: #da3633; color: #fff; }}
.badge-配售 {{ background: #1f6feb; color: #fff; }}
.badge-代價發行 {{ background: #3fb950; color: #000; }}
.badge-先舊後新 {{ background: #d2991d; color: #000; }}
.discount-up {{ color: #3fb950; }}
.discount-down {{ color: #f85149; }}
.signal-bull {{ color: #3fb950; }}
.signal-bear {{ color: #f85149; }}
.signal-neutral {{ color: #8b949e; }}
.footer {{ padding: 12px; text-align: center; color: #484f58; font-size: 10px; border-top: 1px solid #21262d; margin-top: 10px; }}
@media (max-width: 720px) {{
  body {{ font-size: 10px; }}
  .summary {{ gap: 6px; padding: 6px; }}
  .card {{ min-width: 70px; padding: 6px 8px; }}
  .card .value {{ font-size: 13px; }}
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
  <div class="card blue">
    <div class="label">📋 總事件 (6個月)</div>
    <div class="value">{len(data)}</div>
  </div>
  <div class="card yellow">
    <div class="label">💰 總集資額</div>
    <div class="value">{total_amount/1e8:.0f}億</div>
  </div>
  <div class="card red">
    <div class="label">🔄 供股</div>
    <div class="value">{cats.get('供股',{}).get('count',0)} 隻</div>
  </div>
  <div class="card blue">
    <div class="label">📊 配售</div>
    <div class="value">{cats.get('配售',{}).get('count',0)} 隻</div>
  </div>
  <div class="card green">
    <div class="label">🤝 代價發行</div>
    <div class="value">{cats.get('代價發行',{}).get('count',0)} 隻</div>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="filter('all')">全部 <span class="count">{len(data)}</span></div>
  <div class="tab" onclick="filter('供股')">供股 <span class="count">{cats.get('供股',{}).get('count',0)}</span></div>
  <div class="tab" onclick="filter('配售')">配售 <span class="count">{cats.get('配售',{}).get('count',0)}</span></div>
  <div class="tab" onclick="filter('代價發行')">代價發行 <span class="count">{cats.get('代價發行',{}).get('count',0)}</span></div>
  <div class="tab" onclick="filter('先舊後新')">先舊後新 <span class="count">{cats.get('先舊後新',{}).get('count',0)}</span></div>
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
  <th onclick="sortTable(5)">集資額</th>
  <th onclick="sortTable(6)">攤薄%</th>
  <th onclick="sortTable(7)">用途</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>

<div class="footer">
  數據來源: etnet 經濟通 配股集資 | {len(data)} 項事件 | CCASS Dashboard
</div>

<script>
const DATA = {data_json};

function render(rows) {{
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = rows.map(d => {{
    let catClass = 'badge-' + d.category;
    let amt = d.amount_num >= 1e8 ? (d.amount_num/1e8).toFixed(1)+'億' :
              d.amount_num >= 1e7 ? (d.amount_num/1e7).toFixed(0)+'千萬' :
              d.amount_num >= 1e6 ? (d.amount_num/1e6).toFixed(0)+'百萬' : d.amount;
    let pct = d.pct_num > 0 ? d.pct_num.toFixed(1)+'%' : '-';
    
    return `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name}}</td>
      <td><span class="badge ${{catClass}}">${{d.category}}</span></td>
      <td>${{d.price}}</td>
      <td>${{amt}}</td>
      <td>${{pct}}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis" title="${{d.purpose}}">${{d.purpose}}</td>
    </tr>`;
  }}).join('');
}}

let currentFilter = 'all';
function filter(cat) {{
  currentFilter = cat;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  let rows = cat === 'all' ? DATA : DATA.filter(d => d.category === cat);
  render(rows);
}}

let sortCol = 0;
let sortAsc = false;
function sortTable(col) {{
  sortAsc = sortCol === col ? !sortAsc : false;
  sortCol = col;
  let rows = currentFilter === 'all' ? [...DATA] : DATA.filter(d => d.category === currentFilter);
  const keys = ['date_parsed', 'code', 'name', 'category', 'amount_num', 'amount_num', 'pct_num', 'purpose'];
  
  rows.sort((a, b) => {{
    let va = a[keys[col]] || '';
    let vb = b[keys[col]] || '';
    if (typeof va === 'number') return sortAsc ? va - vb : vb - va;
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  }});
  render(rows);
}}

// Initial render
render(DATA);
</script>

</body>
</html>
'''

with open('rights_analysis.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Generated rights_analysis.html ({len(html)} bytes)")
print(f"Events: {len(data)}, Total raised: {total_amount/1e8:.0f}億 HKD")
