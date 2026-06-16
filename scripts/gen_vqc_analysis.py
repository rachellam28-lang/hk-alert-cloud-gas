#!/usr/bin/env python3
"""Generate vqc_analysis.html from data/vqc_backtest.json."""

from __future__ import annotations

import json
import os
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
DATA_JSON = json.dumps(DATA, ensure_ascii=False)

html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>VQC 轉勢日回測</title>
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
  .grid-2, .rule-grid, .mini-grid {{ grid-template-columns: 1fr; }}
  .bar-row {{ grid-template-columns: 92px 1fr 58px; }}
}}
</style>
</head>
<body>
<nav class="site-nav">
  <a href="index.html">🇭🇰 港股版</a>
  <a href="watchlist.html">⭐ 自選</a>
  <a href="history.html">🕐 歷史</a>
  <a href="gap_fvg.html">⤴ Gap/FVG</a>
  <a href="fundflow.html">💰 資金</a>
  <a href="rights_analysis.html">📋 供配股</a>
  <a class="active" href="vqc_analysis.html">📈 VQC</a>
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</nav>

<div class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">VQC TURN DATE</div>
      <div class="title">VQC 轉勢日回測</div>
      <div class="subtitle">
        條件：現月收市向上穿越最近 <b>{DATA.get("lookback_months", 24)}</b> 個完成月中，成交量最大那個月的開市價。
        回測以 TradingView 日線重組月K，確認點為月收市。頁面會持續跟住 `data/vqc_backtest.json` 更新。
      </div>
    </div>
    <div class="hero-meta">
      更新：<b id="updatedAt">{DATA.get("updated", "")}</b><br>
      樣本模式：<b id="sampleMode"></b><br>
      取數：<b id="sampleBars"></b> bars / stock
    </div>
  </section>

  <section class="cards" id="summaryCards"></section>

  <section class="panel">
    <div class="panel-title">策略定義</div>
    <div class="rule-grid">
      <div class="rule-list">
        1. 用日線重組月K。<br>
        2. 喺每個完成月，搵最近 <b>{DATA.get("lookback_months", 24)}</b> 個完成月中成交量最大嗰個月。<br>
        3. 用嗰個月嘅 <b>Open</b> 做轉勢線。<br>
        4. 當現月收市 <b>升穿</b> 轉勢線，視作 VQC 轉勢日。<br>
        5. 回測入場價 = 該月最後交易日收市，並計 5D / 20D / 60D forward return。
      </div>
      <div class="rule-list">
        - 參考樣本：<b id="universeInfo"></b><br>
        - 20D baseline：所有月收市 forward 20D 中位數<br>
        - Edge：VQC 中位數 vs baseline 中位數<br>
        - 強度分層：以高成交月 volume ratio 分 high / mid / low
      </div>
    </div>
  </section>

  <div class="grid-2">
    <section class="panel">
      <div class="panel-title">市場基準 / Edge</div>
      <div class="mini-grid" id="edgeGrid"></div>
    </section>
    <section class="panel">
      <div class="panel-title">強度分層</div>
      <div class="bars" id="strengthBars"></div>
    </section>
  </div>

  <section class="panel">
    <div class="panel-title">市值分層</div>
    <div class="bars" id="mcBars"></div>
  </section>

  <section class="panel">
    <div class="panel-title">VQC 訊號表</div>
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
            <th>突破%</th>
            <th>5D</th>
            <th>20D</th>
            <th>60D</th>
            <th>MaxG20D</th>
            <th>MaxDD20D</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </section>

  <div class="foot">
    資料源：TradingView 日線 · 回測邏輯：月K + 高成交月 Open 突破 · 此頁會跟 `data/vqc_backtest.json` 同步更新。<br>
    若你想將 universe 擴展到全市場，只需要重跑 `scripts/build_vqc_backtest.py --bucket-limit 0`。
  </div>
</div>

<script>
const DATA = {DATA_JSON};
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
    ['5日命中率', s.signal_win_5d == null ? '—' : s.signal_win_5d.toFixed(1)+'%', `baseline ${{s.baseline_median_5d == null ? '—' : s.baseline_median_5d.toFixed(2)+'%'}}`],
    ['20日命中率', s.signal_win_20d == null ? '—' : s.signal_win_20d.toFixed(1)+'%', `edge ${{edge.edge_win_20d == null ? '—' : (edge.edge_win_20d>=0?'+':'')+edge.edge_win_20d.toFixed(1)+'pt'}}`],
    ['平均20日', s.signal_median_20d == null ? '—' : s.signal_median_20d.toFixed(2)+'%', `baseline ${{s.baseline_median_20d == null ? '—' : s.baseline_median_20d.toFixed(2)+'%'}}`],
    ['Edge vs baseline', edge.edge_20d == null ? '—' : (edge.edge_20d >= 0 ? '+' : '') + edge.edge_20d.toFixed(2)+'%', '20D median 差距'],
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

function renderEdge() {{
  const s = DATA.summary || {{}};
  const edge = DATA.edge || {{}};
  const vals = [
    ['VQC 20D 中位數', s.signal_median_20d],
    ['Baseline 20D 中位數', s.baseline_median_20d],
    ['Edge 20D', edge.edge_20d],
    ['Baseline 20D Win', s.baseline_win_20d == null ? null : s.baseline_win_20d.toFixed(1)+'%'],
    ['VQC 20D Win', s.signal_win_20d == null ? null : s.signal_win_20d.toFixed(1)+'%'],
    ['5D 中位數', s.signal_median_5d],
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
    const pct = s.fwd20_win_rate ?? 0;
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
    const av = a.fwd_20d == null ? -9999 : a.fwd_20d;
    const bv = b.fwd_20d == null ? -9999 : b.fwd_20d;
    return bv - av;
  }});
  document.getElementById('tableBody').innerHTML = rows.slice(0, 300).map(r => `
    <tr>
      <td>${{r.code}}</td>
      <td>${{r.name}}</td>
      <td><span class="pill ${{r.mc_bucket}}">${{r.mc_bucket || '—'}}</span></td>
      <td>${{r.signal_date}}</td>
      <td>${{r.ref_month}}</td>
      <td><span class="pill ${{r.strength_bucket || ''}}">${{r.volume_ratio == null ? '—' : r.volume_ratio.toFixed(2)+'x'}}</span></td>
      <td style="color:${{r.break_pct >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.break_pct)}}</td>
      <td style="color:${{(r.fwd_5d ?? 0) >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.fwd_5d == null ? null : r.fwd_5d*100)}}</td>
      <td style="color:${{(r.fwd_20d ?? 0) >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.fwd_20d == null ? null : r.fwd_20d*100)}}</td>
      <td style="color:${{(r.fwd_60d ?? 0) >= 0 ? '#6fe3a4' : '#ff9a98'}}">${{fmtPct(r.fwd_60d == null ? null : r.fwd_60d*100)}}</td>
      <td>${{fmtPct(r.max_gain_20d == null ? null : r.max_gain_20d*100)}}</td>
      <td>${{fmtPct(r.max_drawdown_20d == null ? null : r.max_drawdown_20d*100)}}</td>
    </tr>`).join('');
}}

function setFilter(next) {{
  currentFilter = next;
  document.querySelectorAll('.btn[data-filter]').forEach(btn => btn.classList.toggle('active', btn.dataset.filter === next));
  renderTable();
}}

renderCards();
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
