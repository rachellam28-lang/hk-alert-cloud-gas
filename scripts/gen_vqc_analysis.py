#!/usr/bin/env python3
"""Generate 成交轉勢日 analysis page from data/vqc_backtest.json."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / "data" / "vqc_backtest.json"
OUT_PATH = BASE / "vqc_analysis.html"


def load_data() -> dict:
    if DATA_PATH.exists():
        return json.load(open(DATA_PATH, encoding="utf-8"))
    return {
        "updated": "",
        "universe_total": 0,
        "sample_total": 0,
        "events_total": 0,
        "summary": {},
        "edge": {},
        "strength_stats": {},
        "mc_stats": {},
        "top_winners": [],
        "top_losers": [],
        "events": [],
        "lookback_months": 24,
        "bucket_limit": 0,
        "bars": 0,
        "workers": 0,
    }


DATA = load_data()
PAGE_DATA = {k: DATA.get(k) for k in (
    "updated", "universe_total", "sample_total", "events_total", "summary", "edge",
    "strength_stats", "mc_stats", "reference_examples", "lookback_months", "bucket_limit", "bars",
)}
PAGE_DATA["events"] = sorted(
    DATA.get("events") or [],
    key=lambda row: str(row.get("signal_date") or ""),
    reverse=True,
)
DATA_JSON = json.dumps(PAGE_DATA, ensure_ascii=False)
PAGE_UPDATED = datetime.now().strftime("%Y-%m-%d %H:%M")
SAMPLE_UPDATED = str(DATA.get("updated", "")).replace("T", " ")[:16] or "—"

html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>成交轉勢日回測</title>
<style>
:root {{
  --bg: #0b1220;
  --panel: #111a2c;
  --panel-2: #0f1727;
  --line: #27314a;
  --text: #e5edf8;
  --muted: #8ea0bf;
  --green: #2ec27e;
  --red: #ef5350;
  --amber: #d8a327;
  --blue: #57a6ff;
  --violet: #b18cff;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: radial-gradient(circle at top, #101a30 0%, #0b1220 44%, #09101b 100%); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
a {{ color: inherit; text-decoration: none; }}
.site-nav {{ display:flex; gap: 6px 12px; flex-wrap: wrap; padding: 8px 12px; background:#0f172a; border-bottom:1px solid #1e293b; font-size:13px; position: sticky; top: 0; z-index: 40; }}
.site-nav a {{ color:#94a3b8; white-space: nowrap; }}
.site-nav a.active {{ color:#38bdf8; font-weight:600; }}
.wrap {{ width: min(1280px, calc(100vw - 24px)); margin: 0 auto; padding: 14px 0 28px; }}
.hero {{ display:flex; justify-content:space-between; gap: 14px; align-items:flex-end; padding: 18px 16px; background: linear-gradient(180deg, rgba(17,26,44,.95), rgba(11,18,32,.95)); border:1px solid var(--line); border-radius: 18px; box-shadow: 0 20px 55px rgba(0,0,0,.24); }}
.eyebrow {{ color: var(--blue); font-size: 12px; letter-spacing: .18em; text-transform: uppercase; font-weight: 800; }}
.title {{ font-size: 32px; font-weight: 900; margin-top: 4px; line-height: 1.08; }}
.subtitle {{ color: var(--muted); margin-top: 8px; line-height: 1.5; max-width: 880px; font-size: 13px; }}
.hero-meta {{ text-align:right; color: var(--muted); font-size: 12px; min-width: 180px; }}
.cards {{ display:grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }}
.card {{ background: linear-gradient(180deg, rgba(17,26,44,.97), rgba(12,19,33,.97)); border:1px solid var(--line); border-radius: 16px; padding: 12px 14px; box-shadow: 0 14px 32px rgba(0,0,0,.14); min-height: 88px; }}
.card .k {{ color: var(--muted); font-size: 11px; letter-spacing: .04em; }}
.card .v {{ font-size: 28px; font-weight: 900; margin-top: 4px; line-height: 1.0; }}
.card .s {{ color: var(--muted); font-size: 11px; margin-top: 6px; line-height: 1.35; }}
.green {{ color: var(--green); }}
.red {{ color: var(--red); }}
.amber {{ color: var(--amber); }}
.blue {{ color: var(--blue); }}
.violet {{ color: var(--violet); }}
.panel {{ background: rgba(15,23,42,.85); border:1px solid var(--line); border-radius: 18px; padding: 14px 16px; box-shadow: 0 18px 35px rgba(0,0,0,.14); margin-top: 12px; }}
.panel-title {{ font-size: 14px; font-weight: 800; margin-bottom: 10px; }}
.backtest-hide {{ display:none !important; }}
.rule-grid {{ display:grid; grid-template-columns: 1.25fr .75fr; gap: 10px; }}
.rule-list {{ color: var(--muted); font-size: 13px; line-height: 1.65; }}
.bars {{ display:grid; gap: 10px; }}
.bar-row {{ display:grid; grid-template-columns: 110px 1fr 74px; gap: 10px; align-items:center; }}
.bar-label {{ font-weight: 700; }}
.bar-track {{ height: 14px; background: #18233a; border-radius: 999px; overflow: hidden; border: 1px solid #24304a; display:flex; }}
.bar-fill-green {{ background: linear-gradient(90deg, #26a269, #3bd17f); }}
.bar-fill-amber {{ background: linear-gradient(90deg, #a77e14, #e4b83a); }}
.bar-fill-red {{ background: linear-gradient(90deg, #c63a36, #ff706d); }}
.bar-num {{ text-align:right; color: var(--muted); font-size: 12px; }}
.grid-2 {{ display:grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.mini-grid {{ display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
.mini {{ background: #10192b; border:1px solid #24304a; border-radius: 14px; padding: 12px; }}
.mini .lab {{ color: var(--muted); font-size: 11px; }}
.mini .val {{ font-size: 24px; font-weight: 900; margin-top: 5px; }}
.ref-grid {{ display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px; margin-top:12px; }}
.ref-card {{ background:#10192b; border:1px solid #24304a; border-radius:14px; padding:12px; }}
.ref-title {{ font-size:13px; font-weight:900; margin-bottom:8px; }}
.ref-stats {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:8px; }}
.ref-stat .lab {{ color:var(--muted); font-size:10px; }}
.ref-stat .val {{ font-size:20px; font-weight:900; margin-top:3px; }}
.compare-grid {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:10px; }}
.compare-card {{ background:#10192b; border:1px solid #24304a; border-radius:14px; padding:12px; }}
.compare-card .name {{ font-size:13px; font-weight:900; margin-bottom:9px; }}
.compare-row {{ display:flex; justify-content:space-between; gap:10px; padding:5px 0; border-top:1px solid #1f2a40; font-size:12px; }}
.compare-row:first-of-type {{ border-top:0; }}
.compare-k {{ color:var(--muted); }}
.compare-v {{ font-weight:900; }}
.delta {{ font-size:11px; color:var(--muted); margin-left:4px; }}
.table-wrap {{ overflow-x:auto; margin-top: 8px; }}
table {{ width: 100%; border-collapse: collapse; min-width: 1100px; }}
th, td {{ text-align:left; padding: 8px 10px; border-bottom: 1px solid #1f2a40; font-size: 12px; white-space: nowrap; }}
th {{ color: var(--muted); font-weight: 700; position: sticky; top: 0; background: rgba(15,23,42,.96); cursor: pointer; }}
tr:hover td {{ background: rgba(39,49,74,.22); }}
.pill {{ display:inline-block; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; }}
.pill.small {{ background: rgba(46,194,126,.12); color: #6fe3a4; }}
.pill.mid {{ background: rgba(216,163,39,.12); color: #edcb63; }}
.pill.large {{ background: rgba(87,166,255,.12); color: #8ec1ff; }}
.pill.high {{ background: rgba(46,194,126,.12); color: #6fe3a4; }}
.pill.mid2 {{ background: rgba(216,163,39,.12); color: #edcb63; }}
.pill.low {{ background: rgba(239,83,80,.12); color: #ff9a98; }}
.search-row {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
.search-row input {{ background: #0e1627; color: var(--text); border:1px solid #24304a; border-radius: 12px; padding: 10px 12px; min-width: 220px; }}
.btn {{ border:1px solid #24304a; background:#10192b; color: var(--text); border-radius: 999px; padding: 8px 12px; font-size: 12px; cursor:pointer; }}
.btn.active {{ background: #17315a; border-color: #3d6fb2; color: #dcecff; }}
.foot {{ color: var(--muted); font-size: 11px; margin-top: 12px; line-height: 1.5; }}
@media (max-width: 900px) {{
  .wrap {{ width: auto; padding: 12px; }}
  .hero {{ flex-direction: column; align-items:flex-start; }}
  .hero-meta {{ text-align:left; min-width: 0; }}
  .cards {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
  .grid-2, .rule-grid, .mini-grid, .ref-grid, .compare-grid {{ grid-template-columns: 1fr; }}
  .bar-row {{ grid-template-columns: 92px 1fr 58px; }}
}}
</style>
</head>
<body>
<nav class="site-nav">
  <a href="index.html">🇭🇰 港股版</a>
  <a href="watchlist.html">⭐ 自選</a>
  <a href="history.html">🕐 歷史</a>
  <a href="fundflow.html">💰 資金</a>
  <a href="rights_analysis.html">📋 供配股</a>
  <a href="trading_desk.html">交易台</a>
  <a href="timing_analysis.html">⏱ 時間窗口</a>
  <a class="active" href="vqc_analysis.html">📈 成交轉勢日</a>
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</nav>

<div class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">VOLUME TURN DATE</div>
      <div class="title">成交轉勢日回測</div>
      <div class="subtitle">
        成交轉勢日唔係估升跌，而係搵高成交參考位被重新升穿後的時間窗口。先看成交線，再看價格反應，最後才部署策略。
        回測會分開統計：成交轉勢日前一個交易日下跌後，之後 2 個交易日內有否反彈；前一日上升後，之後 2 個交易日內有否回落。
      </div>
    </div>
    <div class="hero-meta">
      頁面更新：<b>{PAGE_UPDATED}</b><br>
      樣本更新：<b id="updatedAt">{SAMPLE_UPDATED}</b><br>
      樣本模式：<b id="sampleMode"></b><br>
      取數：<b id="sampleBars"></b> bars / stock
    </div>
  </section>

  <section class="cards backtest-hide" id="summaryCards"></section>

  <section class="panel backtest-hide">
    <div class="panel-title">圖片例子 vs 全港股抽樣</div>
    <div class="compare-grid" id="imageComparison"></div>
  </section>

  <section class="panel backtest-hide">
    <div class="panel-title">指定標的示例</div>
    <div class="ref-grid" id="referenceExamples"></div>
  </section>

  <section class="panel backtest-hide">
    <div class="panel-title">策略定義</div>
    <div class="rule-grid">
      <div class="rule-list">
        1. 用日線重組月K。<br>
        2. 喺每個完成月，搵最近 <b>{DATA.get("lookback_months", 24)}</b> 個完成月中成交量最大嗰個月。<br>
        3. 用嗰個月嘅 <b>Open</b> 做轉勢線。<br>
        4. 當現月收市 <b>升穿</b> 成交轉勢線，視作成交轉勢日。<br>
        5. 再看成交轉勢日前一個交易日方向，統計之後 2 個交易日內有否出現反向機會。
      </div>
      <div class="rule-list">
        - 參考樣本：<b id="universeInfo"></b><br>
        - 2D baseline：所有月收市的同一套前日升跌 / 後兩日反向統計<br>
        - Edge：成交轉勢日 2D 反向窗口命中率 vs baseline<br>
        - 強度分層：以高成交月 volume ratio 分 high / mid / low
      </div>
    </div>
  </section>

  <div class="grid-2 backtest-hide">
    <section class="panel">
      <div class="panel-title">市場基準 / Edge</div>
      <div class="mini-grid" id="edgeGrid"></div>
    </section>
    <section class="panel">
      <div class="panel-title">強度分層</div>
      <div class="bars" id="strengthBars"></div>
    </section>
  </div>

  <section class="panel backtest-hide">
    <div class="panel-title">市值分層</div>
    <div class="bars" id="mcBars"></div>
  </section>

  <section class="panel">
    <div class="panel-title">成交轉勢日訊號表</div>
    <div class="search-row">
      <input id="search" type="text" placeholder="搜尋代號 / 名稱…" oninput="renderTable()" />
      <button class="btn active" data-filter="all" onclick="setFilter('all')">全部</button>
      <button class="btn" data-filter="small" onclick="setFilter('small')">小市值</button>
      <button class="btn" data-filter="mid" onclick="setFilter('mid')">中市值</button>
      <button class="btn" data-filter="large" onclick="setFilter('large')">大市值</button>
      <button class="btn" data-filter="high" onclick="setFilter('high')">高強度</button>
      <button class="btn" data-filter="mid2" onclick="setFilter('mid2')">中強度</button>
      <button class="btn" data-filter="low" onclick="setFilter('low')">低強度</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>代號</th>
            <th>名稱</th>
            <th>市值</th>
            <th>信號日</th>
            <th>Ref 月</th>
            <th>量比</th>
            <th>前日</th>
            <th>2D窗口</th>
            <th>2D幅度</th>
            <th>突破%</th>
            <th>2D</th>
            <th>20D</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </section>

  <div class="foot">
    資料源：TradingView 日線 · 回測邏輯：月K + 高成交月 Open 觸發成交轉勢日時間窗口 · 此頁會跟 `data/vqc_backtest.json` 同步更新。<br>
    若你想將 universe 擴展到全市場，只需要重跑 `scripts/build_vqc_backtest.py --bucket-limit 0`。
  </div>
</div>

<script>
const DATA = {DATA_JSON};
const IMAGE_EXAMPLES = [
  {{ name: '2800.HK 圖片例子', overall: null, down: 90.9, up: 80.6, note: '你提供的兩年回測數字' }},
];
let currentFilter = 'all';
let searchTerm = '';

function fmtPct(v) {{
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}}
function fmtNum(v) {{
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toFixed(2);
}}
function fmtInt(v) {{
  if (v == null || Number.isNaN(v)) return '—';
  return Math.round(v).toLocaleString();
}}
function renderCards() {{
  const s = DATA.summary || {{}};
  const edge = DATA.edge || {{}};
  const cards = [
    ['樣本股數', DATA.sample_total ?? 0, `Universe ${{DATA.universe_total ?? 0}}`],
    ['訊號數', s.signal_count ?? 0, `訊號 / 月點`],
    ['前日跌 -> 2D反彈', s.down_rebound_rate_2d == null ? '—' : s.down_rebound_rate_2d.toFixed(1)+'%', `n=${{s.down_n ?? 0}}`],
    ['前日升 -> 2D回落', s.up_pullback_rate_2d == null ? '—' : s.up_pullback_rate_2d.toFixed(1)+'%', `n=${{s.up_n ?? 0}}`],
    ['整體2D窗口', s.overall_rate_2d == null ? '—' : s.overall_rate_2d.toFixed(1)+'%', `baseline ${{s.baseline_overall_rate_2d == null ? '—' : s.baseline_overall_rate_2d.toFixed(1)+'%'}}`],
    ['Edge vs baseline', edge.edge_turn_2d == null ? '—' : (edge.edge_turn_2d >= 0 ? '+' : '') + edge.edge_turn_2d.toFixed(1)+'pt', '2D window 差距'],
  ];
  document.getElementById('summaryCards').innerHTML = cards.map(([k,v,s2]) => `
    <div class="card">
      <div class="k">${{k}}</div>
      <div class="v">${{v}}</div>
      <div class="s">${{s2}}</div>
    </div>`).join('');
  document.getElementById('sampleMode').textContent = `stratified / bucket-limit ${{DATA.bucket_limit ?? 0}}`;
  document.getElementById('sampleBars').textContent = DATA.bars ?? 0;
  document.getElementById('universeInfo').textContent = `${{DATA.sample_total ?? 0}} / ${{DATA.universe_total ?? 0}}`;
}}

function renderReferences() {{
  const refs = DATA.reference_examples || [];
  document.getElementById('referenceExamples').innerHTML = refs.map(r => {{
    if (r.error) {{
      return `<div class="ref-card"><div class="ref-title">${{r.code}} ${{r.name}}</div><div class="foot">${{r.error}}</div></div>`;
    }}
    return `<div class="ref-card">
      <div class="ref-title">${{r.code}} ${{r.name}} <span class="pill large">${{r.exchange || ''}}</span></div>
      <div class="ref-stats">
        <div class="ref-stat"><div class="lab">整體2D</div><div class="val">${{r.overall_rate_2d == null ? '—' : r.overall_rate_2d.toFixed(1)+'%'}}</div></div>
        <div class="ref-stat"><div class="lab">前日跌反彈</div><div class="val green">${{r.down_rebound_rate_2d == null ? '—' : r.down_rebound_rate_2d.toFixed(1)+'%'}}</div></div>
        <div class="ref-stat"><div class="lab">前日升回落</div><div class="val red">${{r.up_pullback_rate_2d == null ? '—' : r.up_pullback_rate_2d.toFixed(1)+'%'}}</div></div>
      </div>
      <div class="foot">events=${{r.events_total ?? 0}} · n=${{r.overall_n ?? 0}}</div>
    </div>`;
  }}).join('');
}}

function renderImageComparison() {{
  const s = DATA.summary || {{}};
  const hk = {{
    name: '全港股抽樣',
    overall: s.overall_rate_2d,
    down: s.down_rebound_rate_2d,
    up: s.up_pullback_rate_2d,
    note: `events=${{DATA.events_total ?? 0}} · n=${{s.overall_n ?? 0}}`
  }};
  const rows = [hk, ...IMAGE_EXAMPLES];

  function pct(v) {{
    return v == null ? '—' : v.toFixed(1) + '%';
  }}
  function delta(v, base) {{
    if (v == null || base == null) return '';
    const d = v - base;
    return `<span class="delta">${{d >= 0 ? '+' : ''}}${{d.toFixed(1)}}pt</span>`;
  }}

  document.getElementById('imageComparison').innerHTML = rows.map((r, idx) => `
    <div class="compare-card">
      <div class="name">${{r.name}}</div>
      <div class="compare-row"><span class="compare-k">整體2D窗口</span><span class="compare-v">${{pct(r.overall)}}${{idx ? delta(r.overall, hk.overall) : ''}}</span></div>
      <div class="compare-row"><span class="compare-k">前日跌反彈</span><span class="compare-v green">${{pct(r.down)}}${{idx ? delta(r.down, hk.down) : ''}}</span></div>
      <div class="compare-row"><span class="compare-k">前日升回落</span><span class="compare-v red">${{pct(r.up)}}${{idx ? delta(r.up, hk.up) : ''}}</span></div>
      <div class="foot">${{r.note}}</div>
    </div>`).join('');
}}

function renderEdge() {{
  const s = DATA.summary || {{}};
  const edge = DATA.edge || {{}};
  const vals = [
    ['成交轉勢日2D', s.overall_rate_2d == null ? null : s.overall_rate_2d.toFixed(1)+'%'],
    ['Baseline 2D 整體', s.baseline_overall_rate_2d == null ? null : s.baseline_overall_rate_2d.toFixed(1)+'%'],
    ['Edge 2D', edge.edge_turn_2d == null ? null : (edge.edge_turn_2d >= 0 ? '+' : '') + edge.edge_turn_2d.toFixed(1)+'pt'],
    ['前日跌反彈', s.down_rebound_rate_2d == null ? null : s.down_rebound_rate_2d.toFixed(1)+'%'],
    ['前日升回落', s.up_pullback_rate_2d == null ? null : s.up_pullback_rate_2d.toFixed(1)+'%'],
    ['2D 中位數', s.signal_median_2d],
  ];
  document.getElementById('edgeGrid').innerHTML = vals.map(([k,v]) => `
    <div class="mini">
      <div class="lab">${{k}}</div>
      <div class="val">${{v == null ? '—' : (typeof v === 'string' ? v : v.toFixed ? v.toFixed(2)+'%' : String(v))}}</div>
    </div>`).join('');
}}

function renderBars(containerId, stats, order, colors) {{
  const rows = order.map(key => {{
    const s = stats[key] || {{}};
    const pct = s.turn_hit_rate_2d ?? s.fwd20_win_rate ?? 0;
    const width = Math.max(3, Math.min(100, pct));
    const label = key === 'high' ? '高強度' : key === 'mid' ? '中強度' : key === 'low' ? '低強度' : key === 'small' ? '小市值' : key === 'mid2' ? '中市值' : '大市值';
    const pill = key === 'small' || key === 'mid' || key === 'large' ? key : key;
    const color = colors[key] || 'bar-fill-green';
    return `<div class="bar-row">
      <div class="bar-label">${{label}} <span class="pill ${{pill}}">${{s.count ?? 0}}</span></div>
      <div class="bar-track"><div class="${{color}}" style="width:${{width}}%"></div></div>
      <div class="bar-num">${{pct ? pct.toFixed(1)+'%' : '—'}}</div>
    </div>`;
  }}).join('');
  document.getElementById(containerId).innerHTML = rows;
}}

function matchesFilter(row) {{
  if (currentFilter === 'all') return true;
  if (currentFilter === 'small' || currentFilter === 'mid' || currentFilter === 'large') return row.mc_bucket === currentFilter;
  if (currentFilter === 'high' || currentFilter === 'mid2' || currentFilter === 'low') return row.strength_bucket === currentFilter;
  return true;
}}

function renderTable() {{
  const q = (document.getElementById('search').value || '').trim().toLowerCase();
  const rows = (DATA.events || []).filter(r => {{
    if (!matchesFilter(r)) return false;
    if (!q) return true;
    return String(r.code || '').includes(q) || String(r.name || '').toLowerCase().includes(q);
  }});
  rows.sort((a,b) => {{
    const av = a.signal_date || '';
    const bv = b.signal_date || '';
    if (av !== bv) return bv.localeCompare(av);
    const ah = a.turn_hit_2d ? 1 : 0;
    const bh = b.turn_hit_2d ? 1 : 0;
    if (ah !== bh) return bh - ah;
    const am = a.turn_move_2d == null ? -9999 : a.turn_move_2d;
    const bm = b.turn_move_2d == null ? -9999 : b.turn_move_2d;
    return bm - am;
  }});
  document.getElementById('tableBody').innerHTML = rows.slice(0, 300).map(r => `
    <tr>
      <td>${{r.code}}</td>
      <td>${{r.name}}</td>
      <td><span class="pill ${{r.mc_bucket}}">${{r.mc_bucket || '—'}}</span></td>
      <td>${{r.signal_date}}</td>
      <td>${{r.ref_month}}</td>
      <td><span class="pill ${{r.strength_bucket || ''}}">${{r.volume_ratio == null ? '—' : r.volume_ratio.toFixed(2)+'x'}}</span></td>
      <td>${{r.prev_day_direction === 'down' ? '跌' : r.prev_day_direction === 'up' ? '升' : '—'}} ${{fmtPct(r.prev_day_return == null ? null : r.prev_day_return*100)}}</td>
      <td style="color:${{r.turn_hit_2d ? '#6fe3a4' : '#ff9a98'}}">${{r.turn_hit_2d ? '有' : '—'}}</td>
      <td>${{fmtPct(r.turn_move_2d == null ? null : r.turn_move_2d*100)}}</td>
      <td style="color:${{r.break_pct >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.break_pct)}}</td>
      <td style="color:${{(r.fwd_2d ?? 0) >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.fwd_2d == null ? null : r.fwd_2d*100)}}</td>
      <td style="color:${{(r.fwd_20d ?? 0) >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.fwd_20d == null ? null : r.fwd_20d*100)}}</td>
    </tr>`).join('');
}}

function setFilter(next) {{
  currentFilter = next;
  document.querySelectorAll('.btn[data-filter]').forEach(btn => btn.classList.toggle('active', btn.dataset.filter === next));
  renderTable();
}}

renderCards();
renderImageComparison();
renderReferences();
renderEdge();
renderBars('strengthBars', DATA.strength_stats || {{}}, ['high','mid','low'], {{
  high: 'bar-fill-green',
  mid: 'bar-fill-amber',
  low: 'bar-fill-red',
}});
renderBars('mcBars', DATA.mc_stats || {{}}, ['small','mid','large'], {{
  small: 'bar-fill-red',
  mid: 'bar-fill-amber',
  large: 'bar-fill-green',
}});
renderTable();
</script>
</body>
</html>"""

OUT_PATH.write_text(html, encoding="utf-8")
print(f"Generated {OUT_PATH} ({len(html)} bytes)")
