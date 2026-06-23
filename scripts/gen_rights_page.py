#!/usr/bin/env python3
"""Generate rights_analysis.html — v4: 8120 pattern. Rating = jump status, not discount."""
import json, re, os, glob

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'raw')

from issuer_score import issuer_pressure_score

with open(os.path.join(DATA_DIR, 'placements_enriched.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)

# ====== Load raw/ price history ======
def load_raw_prices():
    hist = {}
    raw_path = RAW_DIR
    if not os.path.isdir(raw_path):
        return hist
    for fp in sorted(glob.glob(os.path.join(raw_path, 'prices_*.json'))):
        m = re.search(r'prices_(\d{4})(\d{2})(\d{2})', os.path.basename(fp))
        if not m:
            continue
        d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        try:
            day = json.load(open(fp))
            for code, val in day.items():
                code5 = str(code).zfill(5)
                px = val.get('close', val) if isinstance(val, dict) else val
                if px and float(px) > 0.0001:
                    hist.setdefault(code5, {})[d] = float(px)
        except Exception:
            continue
    return hist

PRICE_HIST = load_raw_prices()
print(f"Loaded raw/ prices for {len(PRICE_HIST)} stocks")

def compute_jump(code, ann_date_str):
    """(jump_pct, status): jumped|waiting|no_jump|no_data"""
    from datetime import datetime
    pxs = PRICE_HIST.get(str(code).zfill(5))
    if not pxs:
        return None, 'no_data'
    dates = sorted(pxs.keys())
    base_day = None
    for d in dates:
        if d >= ann_date_str:
            base_day = d
            break
    if base_day is None:
        return None, 'no_data'
    # GUARD: base_day must be within 4 calendar days of announcement
    # Otherwise raw/ doesn't cover this placement (old → random window)
    gap = (datetime.strptime(base_day, '%Y-%m-%d') -
           datetime.strptime(ann_date_str, '%Y-%m-%d')).days
    if gap > 1:
        return None, 'no_data'
    base = pxs[base_day]
    fwd = [d for d in dates if d > base_day][:5]
    if not fwd:
        return None, 'waiting'
    best = max(pxs[d] / base - 1 for d in fwd)
    best_px = max(pxs[d] for d in fwd)
    pct = round(best * 100, 1)
    
    # Price floor: sub-$0.05 stocks need ≥3 tick move (not just % noise)
    if best >= 0.08 and base < 0.05:
        abs_move = best_px - base
        min_tick = 0.001 if base < 0.25 else 0.005  # HKEX tick rules
        if abs_move < min_tick * 3:
            # <3 ticks = noise, not a real jump. Downgrade to no_jump if window passed.
            return (pct, 'no_jump') if len(fwd) >= 5 else (pct, 'waiting')
    
    if best >= 0.08:
        return pct, 'jumped'
    return (pct, 'no_jump') if len(fwd) >= 5 else (pct, 'waiting')

# ====== V4: 8120 pattern rating ======
def trade_signal(p):
    """Rating = jump status. Discount is NOT used for rating (no evidence)."""
    jump_pct, jump_status = compute_jump(p.get('code', ''), p.get('date_parsed', ''))
    
    pct = p['pct_num']
    thesis = []
    risks = []
    
    # Jump-based rating
    if jump_status == 'jumped':
        conviction = 3
        signal = '🟢 跟!'
        sig_class = 'trade-buy'
        verdict_text = '跳升確認'
        thesis.append(f'🚀 T+5內跳升+{jump_pct}%→跟!')
    elif jump_status == 'waiting':
        conviction = 1
        signal = '🟡 等'
        sig_class = 'trade-wait'
        verdict_text = '等跳升'
        if jump_pct is not None:
            thesis.append(f'⏳ T+5窗口: best +{jump_pct}% (<8%)')
        else:
            thesis.append('⏳ 等緊T+5數據')
    elif jump_status == 'no_jump':
        conviction = -1
        signal = '🔴 避'
        sig_class = 'trade-avoid'
        verdict_text = '冇跳升'
        thesis.append(f'✗ 5日最高+{jump_pct}% (<8%門檻)=避')
    else:
        # no_data: old placements before raw/ history — honest gap
        conviction = 0
        signal = '—'
        sig_class = 'trade-wait'
        verdict_text = '數據不足'
        thesis.append('📜 歷史記錄 (raw/未覆蓋)')
    
    # Risk factors (still valid regardless of jump)
    if pct > 50:
        conviction -= 1
        risks.append(f'攤薄{pct}%')
    elif pct > 30:
        risks.append(f'攤薄{pct}%')
    
    if '貸款資本化' in p.get('method', ''):
        conviction -= 1
        risks.append('債轉股')
    
    return {
        'conviction': conviction,
        'signal': signal,
        'sig_class': sig_class,
        'verdict_text': verdict_text,
        'thesis': ' | '.join(thesis),
        'risks': risks[:3],
        'jump_8d_pct': jump_pct,
        'jump_status': jump_status,
    }

for p in data:
    p['trade'] = trade_signal(p)
    p['jump_8d_pct'] = p['trade'].get('jump_8d_pct')
    p['issuer'] = issuer_pressure_score(p)

signals = {}
for p in data:
    s = p['trade']['signal']
    signals[s] = signals.get(s, 0) + 1

print("V4 Signals:")
for s, c in sorted(signals.items()):
    print(f"  {s}: {c}")

# ====== Agent resolve (unchanged) ======
KNOWN_AGENTS = [
    'Guotai Junan', 'KGI Asia', 'Haitong', 'CLSA', 'UBS', 'Citigroup',
    'Goldman Sachs', 'Morgan Stanley', 'Macquarie', 'Futu', 'Tiger Brokers',
    'Zhongtai', 'CMBI', 'CCB International', 'BOC International',
    'Huatai', 'Essence', 'China Merchants', 'Soochow', 'Guosen',
    'Orient Securities', 'Ping An', 'Southwest Securities',
    'CITIC Securities', 'Shenwan Hongyuan', 'Deutsche Bank', 'Nomura',
    'DBS', 'OCBC', 'CGS International', 'Phillip Securities',
    '國泰君安', '海通', '中泰', '建銀', '中銀', '華泰', '國信', '平安',
    '中信証券', '中信里昂', '申萬宏源', '招銀', '光大',
]

def parse_agent_from_text(text):
    if not text: return None
    for agent in KNOWN_AGENTS:
        if agent.lower() in text.lower():
            return agent
    m = re.search(
        r'([A-Z][A-Za-z\s&]+(?:Limited|Ltd|Inc|Securities|Capital|International|Asia|Hong\s*Kong))'
        r'\s+(?:as\s+)?(?:placing\s+agent|sole\s+agent|bookrunner|underwriter)',
        text, re.IGNORECASE
    )
    if m: return m.group(1).strip()
    return None

def resolve_agent(row):
    return (
        row.get('placing_agent')
        or row.get('agent')
        or row.get('vendor')
        or parse_agent_from_text(row.get('method', ''))
        or parse_agent_from_text(row.get('purpose', ''))
    )

filled = 0
for d in data:
    if not d.get('placing_agent'):
        agent = resolve_agent(d)
        if agent:
            d['placing_agent'] = agent
            filled += 1
print(f"Agent resolve: filled {filled} previously null agents")

# ====== GENERATE HTML ======
data_json = json.dumps(data, ensure_ascii=False)

cats = {}
for d in data:
    c = d['category']
    if c not in cats: cats[c] = {'count': 0}
    cats[c]['count'] += 1

g_count = signals.get('🟢 跟!', 0) + signals.get('🟢 跟', 0)
y_count = signals.get('🟡 等', 0)
r_count = signals.get('🔴 避', 0) + signals.get('💀 走', 0)
rights_count = cats.get('供股', {}).get('count', 0)
topup_count = cats.get('先舊後新', {}).get('count', 0)

html = f'''<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta name="robots" content="noindex, nofollow">
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=0.3, maximum-scale=1.0, user-scalable=yes">
<title>供配股跟蹤器 — 8120 Pattern</title>
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
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1200px; }}
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
.issuer-badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; }}
.issuer-high {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.issuer-neutral {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
.issuer-low {{ background: #1a3a1a; color: #3fb950; border: 1px solid #3fb950; }}
.issuer-stack {{ display:flex; flex-direction:column; gap:3px; }}
.issuer-react-up {{ background: #122b18; color: #3fb950; border: 1px solid #3fb950; }}
.issuer-react-neutral {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
.issuer-react-down {{ background: #3a1111; color: #f85149; border: 1px solid #f85149; }}
.thesis {{ max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: #8b949e; font-size: 10px; white-space: normal; }}
.risk {{ color: #f85149; font-size: 10px; }}
.jump-green {{ color: #3fb950; font-weight: bold; }}
.jump-gray {{ color: #484f58; }}
.jump-wait {{ color: #d2991d; }}
.footer {{ padding: 12px; text-align: center; color: #484f58; font-size: 10px; border-top: 1px solid #21262d; margin-top: 10px; line-height: 1.6; }}
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
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</div>

<div class="summary" id="rightsSummary">
  <div class="card buy"><div class="label">🟢 跟</div><div class="value">{g_count}</div></div>
  <div class="card wait"><div class="label">🟡 等</div><div class="value">{y_count}</div></div>
  <div class="card avoid"><div class="label">🔴 避</div><div class="value">{r_count}</div></div>
  <div class="card"><div class="label">💡 核心理念</div><div class="value" style="font-size:10px;color:#58a6ff;line-height:1.5">配售本體 -EV (median -11.8%, 62%輸錢)<br>唯一實證: 配售後5日內收市升穿+8%=跳升確認<br>跳升組 16% 60日內翻倍, 係冇跳組 2.4x</div></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="filter('all')">全部<span class="count">{len(data)}</span></div>
  <div class="tab" onclick="filter('🟢')">🟢 跟<span class="count">{g_count}</span></div>
  <div class="tab" onclick="filter('🟡')">🟡 等<span class="count">{y_count}</span></div>
  <div class="tab" onclick="filter('🔴')">🔴 避<span class="count">{r_count}</span></div>
  <div class="tab" onclick="filter('供股')">供股<span class="count">{rights_count}</span></div>
  <div class="tab" onclick="filter('先舊後新')">先舊後新<span class="count">{topup_count}</span></div>
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
  <th onclick="sortTable(7)">🚀跳升</th>
  <th onclick="sortTable(8)">攤薄</th>
  <th onclick="sortTable(9)">訊號</th>
  <th onclick="sortTable(10)">公告拆解</th>
  <th onclick="sortTable(11)">事後%</th>
  <th>邏輯</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>

<div class="footer">
  📊 402條配售真實統計: median 事後% -11.8% · 62% 輸錢 · 6.5% 升超過100%<br>跳升確認後: &gt;100% 比率 16%（vs 冇跳升 7%）｜ 數據: 自家 track_outcomes 每日回填<br>⚠️ 08120 (+318%) 係 6.5% 嘅倖存者，唔係常態
</div>

<script>
const DATA = {data_json};

function fmtAmt(n) {{
  if (n >= 1e8) return (n/1e8).toFixed(1)+'億';
  if (n >= 1e7) return (n/1e7).toFixed(0)+'千萬';
  return n ? String(n) : '-';
}}

const AGENT_KEYWORDS = ['Guotai','KGI','Haitong','CLSA','UBS','Citi',
  'Goldman','Morgan','Macquarie','Futu','Tiger','CMBI','CCB','BOC',
  'Huatai','Essence','Ping An','CITIC','Shenwan','Hongyuan','Deutsche',
  'Nomura','DBS','OCBC','Soochow','Guosen','國泰','海通','中銀','建銀','華泰','平安',
  '中信','申萬','宏源','興證','招銀','光大'];

function extractAgentFromName(text) {{
  if (!text) return null;
  for (const kw of AGENT_KEYWORDS) {{
    if (text.toLowerCase().includes(kw.toLowerCase())) return kw;
  }}
  return null;
}}

function updateRightsSummary(rows) {{
  let follow = 0, wait = 0, avoid = 0;
  rows.forEach(r => {{
    const sig = ((r.trade||{{}}).signal || '').toString();
    if (sig.includes('跟')) follow++;
    else if (sig.includes('避') || sig.includes('💀')) avoid++;
    else wait++;
  }});
  const el = document.getElementById('rightsSummary');
  if (el) {{
    el.innerHTML =
      '<span class="tag green">🟢 跟 ' + follow + '</span>' +
      '<span class="tag yellow">🟡 等 ' + wait + '</span>' +
      '<span class="tag red">🔴 避 ' + avoid + '</span>' +
      '<span class="tag gray">全部 ' + rows.length + '</span>';
  }}
}}

function render(rows) {{
  document.getElementById('tableBody').innerHTML = rows.map(d => {{
    let t = d.trade || {{}};
    let mp = d.market_price > 0 ? d.market_price.toFixed(2) : '-';
    let disc = d.discount_pct != null ? (d.discount_pct <= 0 ? d.discount_pct+'%' : '+'+d.discount_pct+'%') : '-';
    let discStyle = '';
    if (d.discount_pct != null) {{
      if (d.discount_pct <= -15) discStyle = 'color:#d2991d';
      else if (d.discount_pct <= 0) discStyle = 'color:#8b949e';
      else discStyle = 'color:#f85149';
    }}
    
    // Jump column
    let jumpHtml = '';
    let jp = d.jump_8d_pct;
    let js = t.jump_status || 'no_data';
    if (js === 'jumped') jumpHtml = '<span class="jump-green">🚀 +' + jp.toFixed(1) + '%</span>';
    else if (js === 'waiting') jumpHtml = '<span class="jump-wait">⏳ ' + (jp != null ? '+' + jp.toFixed(1) + '%' : '—') + '</span>';
    else if (js === 'no_jump') jumpHtml = '<span class="jump-gray">✗ +' + (jp != null ? jp.toFixed(1) : '0') + '%</span>';
    else jumpHtml = '<span class="jump-gray">—</span>';
    const issuer = d.issuer || {{score: 50, label: '中性', cls: 'issuer-neutral', shareholder_pressure: {{score: 50, label: '中性', cls: 'issuer-neutral'}}, reaction: {{pct: null, label: '未足夠數據', cls: 'issuer-react-neutral'}}}};
    const shareholder = issuer.shareholder_pressure || {{score: issuer.score || 50, label: issuer.label || '中性', cls: issuer.cls || 'issuer-neutral'}};
    const reaction = issuer.reaction || {{pct: null, label: '未足夠數據', cls: 'issuer-react-neutral'}};
    const reactionPct = reaction.pct != null ? (reaction.pct >= 0 ? '+' : '') + reaction.pct.toFixed(1) + '%' : '—';
    
    // Return
    let ret = d.manual_return_pct != null ? d.manual_return_pct : (d.current_return_pct != null ? d.current_return_pct : null);
    
    let risks = (t.risks||[]).map(r => '<div class="risk">'+r+'</div>').join('');
    
    return `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name}}</td>
      <td><span class="badge badge-${{d.category}}">${{d.category}}</span></td>
      <td>${{d.price}}</td>
      <td>${{mp}}</td>
      <td style="${{discStyle}}">${{disc}}</td>
      <td>${{jumpHtml}}</td>
      <td>${{d.pct_num > 0 ? d.pct_num.toFixed(1)+'%' : '-'}}</td>
      <td><span class="signal ${{t.sig_class||''}}">${{t.signal||'➖'}}</span></td>
      <td>
        <div class="issuer-stack" title="公告條款代理分數，唔係內部意圖；高分＝對發行方更有利／對股東短期壓力更大；公告後價格反應＝歷史 price reaction">
          <span class="issuer-badge ${{issuer.cls}}">發行方有利度 ${{issuer.label}} ${{issuer.score}}</span>
          <span class="issuer-badge ${{shareholder.cls}}">股東短期壓力 ${{shareholder.label}} ${{shareholder.score}}</span>
          <span class="issuer-badge ${{reaction.cls}}">公告後價格反應 ${{reactionPct}} ${{reaction.label}}</span>
        </div>
      </td>
      <td style="color:${{(ret||0) >= 0 ? '#3fb950' : '#f85149'}};font-weight:${{Math.abs(ret||0) > 20 ? 'bold' : 'normal'}}">${{ret != null ? (ret >= 0 ? '+' : '') + ret.toFixed(1) + '%' : '-'}}</td>
      <td>
        <div class="thesis">${{t.thesis||''}}</div>
        ${{risks}}
      </td>
    </tr>`;
  }}).join('');
  updateRightsSummary(rows);
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

let sortCol = 7; let sortAsc = false;
function sortTable(col) {{
  sortAsc = sortCol === col ? !sortAsc : false;
  sortCol = col;
  let rows = getFilteredRows();
  const keys = ['date_parsed','code','name','category','price_num','market_price','discount_pct','jump_8d_pct','pct_num'];
  rows.sort((a,b) => {{
    let va, vb;
    if (col === 7) {{ va = a.jump_8d_pct != null ? a.jump_8d_pct : (a.trade||{{}}).jump_status==='waiting' ? 999 : -999; vb = b.jump_8d_pct != null ? b.jump_8d_pct : (b.trade||{{}}).jump_status==='waiting' ? 999 : -999; }}
    else if (col === 6) {{ va = a.discount_pct != null ? a.discount_pct : 999; vb = b.discount_pct != null ? b.discount_pct : 999; }}
    else if (col === 10) {{ va = (a.issuer || {{score: 50}}).score; vb = (b.issuer || {{score: 50}}).score; }}
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

with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rights_analysis.html'), 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Generated rights_analysis.html ({len(html)} bytes)")
