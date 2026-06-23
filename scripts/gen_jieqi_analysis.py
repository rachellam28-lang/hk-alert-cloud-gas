#!/usr/bin/env python3
"""Generate 節氣窗口 analysis page from data/jieqi_backtest.json."""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / "data" / "jieqi_backtest.json"
OUT_PATH = BASE / "jieqi_analysis.html"


def load_data() -> dict:
    if DATA_PATH.exists():
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "updated": "",
        "years": 0,
        "terms_total": 0,
        "sample_total": 0,
        "universe_total": 0,
        "events_total": 0,
        "summary": {},
        "window": {},
        "offset_stats": [],
        "term_stats": [],
        "top_terms": [],
        "bottom_terms": [],
        "benchmarks": [],
        "events": [],
    }


DATA = load_data()
PAGE_DATA = {
    "updated": DATA.get("updated", ""),
    "years": DATA.get("years", 0),
    "terms_total": DATA.get("terms_total", 0),
    "sample_total": DATA.get("sample_total", 0),
    "universe_total": DATA.get("universe_total", 0),
    "events_total": DATA.get("events_total", 0),
    "summary": DATA.get("summary", {}),
    "window": DATA.get("window", {}),
    "offset_stats": DATA.get("offset_stats", []),
    "term_stats": DATA.get("term_stats", []),
    "top_terms": DATA.get("top_terms", []),
    "bottom_terms": DATA.get("bottom_terms", []),
    "benchmarks": DATA.get("benchmarks", []),
    "source": DATA.get("source", {}),
}
DATA_JSON = json.dumps(PAGE_DATA, ensure_ascii=False)

html = """<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>節氣窗口回測</title>
<style>
:root {
  --bg:#0b1220; --panel:#111a2c; --line:#27314a; --text:#e5edf8; --muted:#8ea0bf;
  --green:#2ec27e; --red:#ef5350; --amber:#d8a327; --blue:#57a6ff;
}
* { box-sizing:border-box; }
body { margin:0; background:radial-gradient(circle at top,#101a30 0%,#0b1220 44%,#09101b 100%); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }
a { color:inherit; text-decoration:none; }
.site-nav { display:flex; gap:6px 12px; flex-wrap:wrap; padding:8px 12px; background:#0f172a; border-bottom:1px solid #1e293b; font-size:13px; position:sticky; top:0; z-index:40; }
.site-nav a { color:#94a3b8; white-space:nowrap; }
.site-nav a.active { color:#38bdf8; font-weight:700; }
.wrap { width:min(1320px, calc(100vw - 24px)); margin:0 auto; padding:14px 0 28px; }
.hero { display:flex; justify-content:space-between; gap:14px; align-items:flex-end; padding:18px 16px; background:linear-gradient(180deg, rgba(17,26,44,.95), rgba(11,18,32,.95)); border:1px solid var(--line); border-radius:18px; box-shadow:0 20px 55px rgba(0,0,0,.24); }
.eyebrow { color:var(--blue); font-size:12px; letter-spacing:.18em; text-transform:uppercase; font-weight:800; }
.title { font-size:32px; font-weight:900; margin-top:4px; line-height:1.08; }
.subtitle { color:var(--muted); margin-top:8px; line-height:1.55; max-width:980px; font-size:13px; }
.hero-meta { text-align:right; color:var(--muted); font-size:12px; min-width:220px; }
.cards { display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:10px; margin-top:12px; }
.card { background:linear-gradient(180deg, rgba(17,26,44,.97), rgba(12,19,33,.97)); border:1px solid var(--line); border-radius:16px; padding:12px 14px; box-shadow:0 14px 32px rgba(0,0,0,.14); min-height:84px; }
.card .k { color:var(--muted); font-size:11px; letter-spacing:.04em; }
.card .v { font-size:28px; font-weight:900; margin-top:4px; line-height:1.0; }
.card .s { color:var(--muted); font-size:11px; margin-top:6px; line-height:1.35; }
.panel { background:rgba(15,23,42,.85); border:1px solid var(--line); border-radius:18px; padding:14px 16px; box-shadow:0 18px 35px rgba(0,0,0,.14); margin-top:12px; }
.panel-title { font-size:14px; font-weight:800; margin-bottom:10px; }
.grid-3 { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:12px; }
.mini-grid { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; }
.mini-grid.wide { grid-template-columns:repeat(5,minmax(0,1fr)); }
.mini { background:#10192b; border:1px solid #24304a; border-radius:14px; padding:12px; }
.mini .lab { color:var(--muted); font-size:11px; }
.mini .val { font-size:24px; font-weight:900; margin-top:5px; }
.table-wrap { overflow-x:auto; margin-top:8px; }
table { width:100%; border-collapse:collapse; min-width:1050px; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #1f2a40; font-size:12px; white-space:nowrap; }
th { color:var(--muted); font-weight:700; position:sticky; top:0; background:rgba(15,23,42,.96); }
tr:hover td { background:rgba(39,49,74,.22); }
.foot { color:var(--muted); font-size:11px; margin-top:12px; line-height:1.5; }
@media (max-width: 900px) {
  .wrap { width:auto; padding:12px; }
  .hero { flex-direction:column; align-items:flex-start; }
  .hero-meta { text-align:left; min-width:0; }
  .cards, .grid-3, .mini-grid { grid-template-columns:1fr; }
}
</style>
</head>
<body>
<nav class="site-nav">
  <a href="index.html">📦 Market</a>
  <a href="signals.html">🔔 訊號</a>
  <a href="watchlist.html">⭐ 自選</a>
  <a href="history.html">🕐 歷史</a>
  <a href="gap_fvg.html">⤴ Gap/FVG</a>
  <a href="fundflow.html">💰 資金</a>
  <a href="rights_analysis.html">📋 供配股</a>
  <a href="daily_trade_prompt.html">🚦 每日提示</a>
  <a href="timing_analysis.html">⏱ 時間窗口</a>
  <a href="distribution_day.html">📉 分佈日</a>
  <a href="vqc_analysis.html">📈 成交轉勢日</a>
  <a class="active" href="jieqi_analysis.html">🧭 節氣窗口</a>
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</nav>

<div class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">SOLAR TERM WINDOW</div>
      <div class="title">節氣窗口回測</div>
      <div class="subtitle">
        24 節氣係固定 calendar anchor。呢頁唔係講神秘力量，而係量化節氣附近有冇可重複嘅時間窗口。
        由節氣正日擴展到前後 2 個交易日，睇窗口命中率、最佳 offset、同 baseline all-days 有冇 edge。
      </div>
    </div>
    <div class="hero-meta">
      更新：<b id="updatedAt">__UPDATED__</b><br>
      年份：<b id="yearSpan">__YEARS__</b><br>
      樣本：<b id="sampleSpan">__SAMPLE__</b>
    </div>
  </section>

  <section class="cards" id="summaryCards"></section>

  <section class="panel">
    <div class="panel-title">市場 vs 股票樣本</div>
    <div class="grid-3" id="compareGrid"></div>
  </section>

  <section class="panel">
    <div class="panel-title">節氣熱度 / Edge 排名</div>
    <div class="mini-grid" id="topTermGrid"></div>
  </section>

  <section class="panel">
    <div class="panel-title">±2 日窗口分解</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Offset</th>
            <th>次數</th>
            <th>2D 命中</th>
            <th>Edge</th>
            <th>20D 中位</th>
            <th>Turn 中位</th>
          </tr>
        </thead>
        <tbody id="offsetTable"></tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <div class="panel-title">24 節氣統計表</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>節氣</th>
            <th>窗口次數</th>
            <th>窗口命中</th>
            <th>正日 2D</th>
            <th>窗口 Edge</th>
            <th>20D 中位</th>
          </tr>
        </thead>
        <tbody id="termTable"></tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <div class="panel-title">點樣用</div>
    <div class="foot" style="font-size:13px;color:var(--text);line-height:1.7">
      1. 節氣唔當方向預言，只當 calendar anchor。<br>
      2. 先睇 Market / Sample 數字有冇 edge，再配合 CCASS、公告、成交量。<br>
      3. 如果某節氣長期 edge 強，可以只作時間窗口提醒，而唔係盲目入市。<br>
      4. 如果 edge 近似 baseline，咁就只當日曆參考，唔好神化。<br>
    </div>
  </section>

  <div class="foot">
    來源：`https://sheup.org/24jieqi_3.php` · `tvDatafeed / TradingView` · `ccass.json` universe sample。<br>
    呢頁會跟 `data/jieqi_backtest.json` 同步更新。
  </div>
</div>

<script>
const DATA = __DATA_JSON__;

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%';
}

function renderSummary() {
  const s = DATA.summary || {};
  const edge = (s.overall_rate_2d ?? 0) - (s.baseline_overall_rate_2d ?? 0);
  const windowEdge = s.edge_window_any ?? null;
  const cards = [
    ['節氣次數', DATA.terms_total ?? 0, `${DATA.years ?? 0} 年`],
    ['股票樣本', DATA.sample_total ?? 0, `universe ${DATA.universe_total ?? 0}`],
    ['窗口命中', s.window_rate_any == null ? '—' : s.window_rate_any.toFixed(1)+'%', `baseline ${s.baseline_window_rate_any == null ? '—' : s.baseline_window_rate_any.toFixed(1)+'%'}`],
    ['窗口 Edge', windowEdge == null ? '—' : (windowEdge >= 0 ? '+' : '') + windowEdge.toFixed(1) + 'pt', '±2 trading days'],
    ['最佳 offset', s.best_offset == null ? '—' : (s.best_offset > 0 ? '+' : '') + s.best_offset + 'D', `best hit ${s.best_offset_rate_2d == null ? '—' : s.best_offset_rate_2d.toFixed(1)+'%'}`],
  ];
  document.getElementById('summaryCards').innerHTML = cards.map(([k,v,s2]) => `
    <div class="card">
      <div class="k">${k}</div>
      <div class="v">${v}</div>
      <div class="s">${s2}</div>
    </div>`).join('');

  document.getElementById('yearSpan').textContent = `${DATA.years ?? 0}`;
  document.getElementById('sampleSpan').textContent = `${DATA.sample_total ?? 0} stocks`;
  document.getElementById('updatedAt').textContent = (DATA.updated || '—').replace('T', ' ').slice(0, 16);
}

function renderCompare() {
  const refs = DATA.benchmarks || [];
  const sample = DATA.summary || {};
  const hk = refs.find(x => x.key === 'hk') || {};
  const cards = [
    {name:'HK proxy', s: hk.summary || {}, code: hk.code || 'HSI1!'},
    {name:'Stock sample', s: sample, code: `${DATA.sample_total ?? 0} stocks`},
  ];
  document.getElementById('compareGrid').innerHTML = cards.map(c => {
    const e = (c.s.window_rate_any ?? 0) - (c.s.baseline_window_rate_any ?? 0);
    return `
      <div class="card">
        <div class="k">${c.name}</div>
        <div class="v">${c.s.window_rate_any == null ? '—' : c.s.window_rate_any.toFixed(1)+'%'}</div>
        <div class="s">baseline ${c.s.baseline_window_rate_any == null ? '—' : c.s.baseline_window_rate_any.toFixed(1)+'%'} · edge ${e >= 0 ? '+' : ''}${e.toFixed(1)}pt<br>${c.code}</div>
      </div>`;
  }).join('');
}

function renderTopTerms() {
  const picks = (DATA.top_terms || []).slice(0, 4);
  document.getElementById('topTermGrid').innerHTML = picks.map(r => `
    <div class="mini">
      <div class="lab">${r.term_name || '—'}</div>
      <div class="val">${r.edge_window_any == null ? '—' : (r.edge_window_any >= 0 ? '+' : '') + r.edge_window_any.toFixed(1) + 'pt'}</div>
      <div class="foot" style="margin-top:4px">窗口 ${r.window_rate_any == null ? '—' : r.window_rate_any.toFixed(1) + '%'} · 正日 ${r.exact_rate_2d == null ? '—' : r.exact_rate_2d.toFixed(1) + '%'}</div>
    </div>`).join('');
}

function renderOffsetTable() {
  const rows = (DATA.offset_stats || []).slice().sort((a, b) => (a.window_offset ?? 0) - (b.window_offset ?? 0));
  const base = DATA.summary?.baseline_overall_rate_2d ?? 0;
  document.getElementById('offsetTable').innerHTML = rows.map(r => `
    <tr>
      <td>${r.label || (r.window_offset > 0 ? '+' : '') + (r.window_offset ?? 0) + 'D'}</td>
      <td>${r.count ?? 0}</td>
      <td style="color:${(r.hit_rate_2d ?? 0) >= base ? '#6fe3a4' : '#ff9a98'}">${r.hit_rate_2d == null ? '—' : r.hit_rate_2d.toFixed(1) + '%'}</td>
      <td>${r.edge_turn_2d == null ? '—' : (r.edge_turn_2d >= 0 ? '+' : '') + r.edge_turn_2d.toFixed(1) + 'pt'}</td>
      <td>${r.median_20d == null ? '—' : r.median_20d.toFixed(2) + '%'}</td>
      <td>${r.median_move_2d == null ? '—' : r.median_move_2d.toFixed(2) + '%'}</td>
    </tr>`).join('');
}

function renderTable() {
  const rows = (DATA.term_stats || []).slice().sort((a,b) => (b.edge_turn_2d ?? -9999) - (a.edge_turn_2d ?? -9999));
  document.getElementById('termTable').innerHTML = rows.map(r => `
    <tr>
      <td>${r.term_name || '—'}</td>
      <td>${r.window_count ?? r.count ?? 0}</td>
      <td style="color:${(r.window_rate_any ?? 0) >= (DATA.summary?.baseline_window_rate_any ?? 0) ? '#6fe3a4' : '#ff9a98'}">${r.window_rate_any == null ? '—' : r.window_rate_any.toFixed(1) + '%'}</td>
      <td>${r.exact_rate_2d == null ? '—' : r.exact_rate_2d.toFixed(1) + '%'}</td>
      <td>${r.edge_window_any == null ? '—' : (r.edge_window_any >= 0 ? '+' : '') + r.edge_window_any.toFixed(1) + 'pt'}</td>
      <td>${r.median_20d == null ? '—' : r.median_20d.toFixed(2) + '%'}</td>
    </tr>`).join('');
}

renderSummary();
renderCompare();
renderTopTerms();
renderOffsetTable();
renderTable();
</script>
</body>
</html>"""

html = html.replace("__DATA_JSON__", DATA_JSON)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Generated {OUT_PATH} ({len(html)} bytes)")
