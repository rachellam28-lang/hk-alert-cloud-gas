#!/usr/bin/env python3
"""Generate a combined timing page for 成交轉勢日 + Distribution Day."""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VQC_PATH = BASE / "data" / "vqc_backtest.json"
DD_PATH = BASE / "data" / "distribution_day_backtest.json"
OUT_PATH = BASE / "timing_analysis.html"


def load_json(path: Path, default: dict) -> dict:
    if path.exists():
        return json.load(open(path, encoding="utf-8"))
    return default


VQC = load_json(
    VQC_PATH,
    {
        "updated": "",
        "summary": {},
        "edge": {},
        "sample_total": 0,
        "universe_total": 0,
        "events_total": 0,
        "signal_label": "成交轉勢日",
    },
)
DD = load_json(
    DD_PATH,
    {
        "updated": "",
        "signals_total": 0,
        "benchmarks_with_data": 0,
        "benchmarks": [],
        "window_days": 25,
        "drop_pct": 0.2,
        "signal_label": "Distribution Day",
    },
)

VQC_JSON = json.dumps(VQC, ensure_ascii=False)
DD_JSON = json.dumps(DD, ensure_ascii=False)

html = """<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>時間窗口總覽</title>
<style>
:root {
  --bg:#09101b; --panel:#10192b; --line:#26314a; --text:#e5edf8; --muted:#8ea0bf;
  --green:#2ec27e; --red:#ef5350; --amber:#d8a327; --blue:#57a6ff; --violet:#b18cff;
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
.cards { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; margin-top:12px; }
.card { background:linear-gradient(180deg, rgba(17,26,44,.97), rgba(12,19,33,.97)); border:1px solid var(--line); border-radius:16px; padding:12px 14px; box-shadow:0 14px 32px rgba(0,0,0,.14); min-height:88px; }
.card .k { color:var(--muted); font-size:11px; letter-spacing:.04em; }
.card .v { font-size:28px; font-weight:900; margin-top:4px; line-height:1.0; }
.card .s { color:var(--muted); font-size:11px; margin-top:6px; line-height:1.35; }
.panel { background:rgba(15,23,42,.85); border:1px solid var(--line); border-radius:18px; padding:14px 16px; box-shadow:0 18px 35px rgba(0,0,0,.14); margin-top:12px; }
.panel-title { font-size:14px; font-weight:800; margin-bottom:10px; }
.backtest-hide { display:none !important; }
.grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.mini-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.mini { background:#10192b; border:1px solid #24304a; border-radius:14px; padding:12px; }
.mini .lab { color:var(--muted); font-size:11px; }
.mini .val { font-size:24px; font-weight:900; margin-top:5px; }
.bars { display:grid; gap:10px; }
.bar-row { display:grid; grid-template-columns: 118px 1fr 74px; gap:10px; align-items:center; }
.bar-label { font-weight:700; }
.bar-track { height:14px; background:#18233a; border-radius:999px; overflow:hidden; border:1px solid #24304a; display:flex; }
.bar-fill-green { background:linear-gradient(90deg,#26a269,#3bd17f); }
.bar-fill-amber { background:linear-gradient(90deg,#a77e14,#e4b83a); }
.bar-fill-red { background:linear-gradient(90deg,#c63a36,#ff706d); }
.bar-fill-blue { background:linear-gradient(90deg,#2563eb,#60a5fa); }
.bar-num { text-align:right; color:var(--muted); font-size:12px; }
.bench-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.bench-card { background:#10192b; border:1px solid #24304a; border-radius:14px; padding:12px; }
.bench-head { display:flex; justify-content:space-between; gap:8px; margin-bottom:8px; }
.bench-name { font-size:13px; font-weight:900; }
.bench-state { font-size:11px; font-weight:800; padding:2px 8px; border-radius:999px; }
.state-healthy { background:rgba(46,194,126,.12); color:#6fe3a4; }
.state-caution { background:rgba(216,163,39,.12); color:#edcb63; }
.state-pressure { background:rgba(239,83,80,.12); color:#ff9a98; }
.bar-wrap { display:grid; gap:8px; margin-top:10px; }
.rule-grid { display:grid; grid-template-columns:1.2fr .8fr; gap:12px; }
.rule-list { color:var(--muted); font-size:13px; line-height:1.68; }
.note { color:var(--muted); font-size:11px; margin-top:10px; line-height:1.5; }
.table-wrap { overflow-x:auto; margin-top:8px; }
table { width:100%; border-collapse:collapse; min-width:860px; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #1f2a40; font-size:12px; white-space:nowrap; }
th { color:var(--muted); font-weight:700; position:sticky; top:0; background:rgba(15,23,42,.96); }
tr:hover td { background:rgba(39,49,74,.22); }
.legend { display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:10px; color:var(--muted); font-size:11px; }
.legend-item { display:flex; align-items:center; gap:6px; white-space:nowrap; }
.legend-dot { width:10px; height:10px; border-radius:999px; display:inline-block; }
.link-row { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.btn { display:inline-block; border:1px solid #24304a; background:#10192b; color:var(--text); border-radius:999px; padding:8px 12px; font-size:12px; }
.btn.blue { border-color:#3d6fb2; background:#17315a; }
.btn.gold { border-color:#fde68a; color:#f5d06f; }
.btn.teal { border-color:#5eead4; color:#9df0e6; }
.foot { color:var(--muted); font-size:11px; margin-top:12px; line-height:1.5; }
@media (max-width: 900px) {
  .wrap { width:auto; padding:12px; }
  .hero { flex-direction:column; align-items:flex-start; }
  .hero-meta { text-align:left; min-width:0; }
  .cards, .grid-2, .rule-grid, .bench-grid, .mini-grid { grid-template-columns:1fr; }
  .bar-row { grid-template-columns: 96px 1fr 60px; }
}
</style>
</head>
<body>
<nav class="site-nav">
  <a href="index.html">🇭🇰 港股版</a>
  <a href="signals.html">🔔 訊號</a>
  <a href="watchlist.html">⭐ 自選</a>
  <a href="history.html">🕐 歷史</a>
  <a href="gap_fvg.html">⤴ Gap/FVG</a>
  <a href="fundflow.html">💰 資金</a>
  <a href="rights_analysis.html">📋 供配股</a>
  <a href="daily_trade_prompt.html">🚦 每日提示</a>
  <a class="active" href="timing_analysis.html">⏱ 時間窗口</a>
  <a href="jieqi_analysis.html">🧭 節氣窗口</a>
  <a href="distribution_day.html">📉 分佈日</a>
  <a href="vqc_analysis.html">📈 成交轉勢日</a>
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</nav>

<div class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">TIMING OVERVIEW</div>
      <div class="title">時間窗口總覽</div>
      <div class="subtitle">
        呢頁將 <b>成交轉勢日</b> 同 <b>Distribution Day 分佈日</b> 放喺同一個工作台。
        前者係搵個股 / 標的嘅高成交時間窗口，後者係睇大市壓力；兩套概念唔一樣，所以保持獨立展示，方便你一眼睇到節奏同環境。
      </div>
      <div class="note" style="margin-top:10px;color:#b7cdf1;font-size:12px"><b>新版週期表</b>：唔再主打回測表，第一屏直接顯示市場時間週期表。</div>
    </div>
    <div class="hero-meta">
      更新：<b id="updatedAt">__UPDATED__</b><br>
      VQC：<b id="vqcUpdated">__VQC_UPDATED__</b><br>
      分佈日：<b id="ddUpdated">__DD_UPDATED__</b>
    </div>
  </section>

  <section class="panel">
    <div class="panel-title">市場時間週期表</div>
    <div class="note">以 HSI proxy 的時間序列畫出節奏，而唔係再用回測表堆數字。色帶代表大市狀態，線條代表指數路徑。</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>日期</th>
            <th>收市</th>
            <th>狀態</th>
            <th>25D Count</th>
          </tr>
        </thead>
        <tbody id="cycleTable"></tbody>
      </table>
    </div>
    <div class="legend">
      <span class="legend-item"><i class="legend-dot" style="background:#3bd17f"></i>healthy</span>
      <span class="legend-item"><i class="legend-dot" style="background:#e4b83a"></i>caution</span>
      <span class="legend-item"><i class="legend-dot" style="background:#ff706d"></i>under pressure</span>
      <span class="legend-item"><i class="legend-dot" style="background:#60a5fa"></i>correction</span>
    </div>
  </section>

  <section class="cards backtest-hide" id="summaryCards"></section>

  <section class="panel">
    <div class="panel-title">點樣一齊用</div>
    <div class="rule-grid">
      <div class="rule-list">
        1. 先用 <b>分佈日</b> 睇大市環境：healthy / caution / under pressure / correction。<br>
        2. 再用 <b>成交轉勢日</b> 睇個股 / 標的是否進入高成交時間窗口。<br>
        3. 若大市處於 correction，VQC 窗口仍可保留但只當觀察，不當成強追擊信號。<br>
        4. 若大市 healthy，而 VQC 窗口出現，優先加權跟進。<br>
        5. 兩者都係概率工具，唔係預言。
      </div>
      <div class="rule-list">
        - 統一原則：先看環境，再看時間，再看價格反應。<br>
        - 呢頁只做總覽，個別回測細節仍然喺原頁。<br>
        - 如要落地執行，建議以原頁數字為準。
      </div>
    </div>
    <div class="link-row">
      <a class="btn red" href="daily_trade_prompt.html">開每日提示</a>
      <a class="btn blue" href="vqc_analysis.html">開成交轉勢日</a>
      <a class="btn teal" href="jieqi_analysis.html">開節氣窗口</a>
      <a class="btn gold" href="distribution_day.html">開分佈日</a>
      <a class="btn teal" href="guide.html">開說明書</a>
    </div>
  </section>

  <div class="grid-2 backtest-hide">
    <section class="panel">
      <div class="panel-title">成交轉勢日</div>
      <div class="mini-grid" id="vqcCards"></div>
      <div class="note" id="vqcNote"></div>
    </section>
    <section class="panel">
      <div class="panel-title">分佈日</div>
      <div class="mini-grid" id="ddCards"></div>
      <div class="note" id="ddNote"></div>
    </section>
  </div>

  <section class="panel backtest-hide">
    <div class="panel-title">分佈日 Benchmark 狀態</div>
    <div class="bench-grid" id="benchGrid"></div>
  </section>

  <section class="panel backtest-hide">
    <div class="panel-title">分佈日 壓力分布</div>
    <div class="bar-wrap" id="stateBars"></div>
  </section>

  <div class="foot">
    來源：`data/vqc_backtest.json` + `data/distribution_day_backtest.json`。<br>
    這頁只做 timing workflow 總覽，不將兩套方法合成同一個數值。
  </div>
</div>

<script>
const VQC = __VQC_JSON__;
const DD = __DD_JSON__;

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%';
}
function fmtNum(v, d=2) {
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toFixed(d);
}
function stateLabel(s) {
  if (s === 'correction') return 'correction';
  if (s === 'under_pressure') return 'under pressure';
  if (s === 'caution') return 'caution';
  return 'healthy';
}
function stateColor(s) {
  if (s === 'correction') return '#60a5fa';
  if (s === 'under_pressure') return '#ff706d';
  if (s === 'caution') return '#e4b83a';
  return '#3bd17f';
}
function dateTs(d) {
  return new Date(String(d) + 'T00:00:00Z').getTime();
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
}

function renderCycleTable() {
  const series = (((DD.benchmarks || [])[0] || {}).signals || [])
    .filter(r => r && r.date && Number.isFinite(Number(r.close)))
    .map(r => ({
      date: r.date,
      close: Number(r.close),
      state: r.market_state || 'healthy',
      count: Number(r.dd_count_25d || 0),
    }))
    .sort((a, b) => dateTs(a.date) - dateTs(b.date));
  const host = document.getElementById('cycleTable');
  if (!series.length) {
    host.innerHTML = '<div class="note">暫時冇足夠 data 顯示週期表。</div>';
    return;
  }
  const stateText = s => stateLabel(s).replace('_', ' ');
  host.innerHTML = series.map((d, idx) => `
    <tr>
      <td>${esc(d.date)}</td>
      <td>${d.close.toFixed(0)}</td>
      <td><span class="pill ${d.state === 'correction' ? 'bad' : d.state === 'under_pressure' ? 'bad' : d.state === 'caution' ? 'warn' : 'good'}">${esc(stateText(d.state))}</span></td>
      <td>${d.count}</td>
    </tr>`).join('');
}

function renderSummary() {
  const vs = VQC.summary || {};
  const ds = (DD.benchmarks || []).map(b => b.summary || {});
  const hk = ds[0] || {};
  const cards = [
    ['成交轉勢日訊號', VQC.events_total ?? 0, `sample ${VQC.sample_total ?? 0} / universe ${VQC.universe_total ?? 0}`],
    ['成交轉勢日2D', vs.overall_rate_2d == null ? '—' : vs.overall_rate_2d.toFixed(1) + '%', `edge ${VQC.edge?.edge_turn_2d == null ? '—' : (VQC.edge.edge_turn_2d >= 0 ? '+' : '') + VQC.edge.edge_turn_2d.toFixed(1) + 'pt'}`],
    ['分佈日訊號', DD.signals_total ?? 0, `benchmarks ${DD.benchmarks_with_data ?? 0}`],
    ['當前大市狀態', stateLabel(hk.current_market_state), `HK ${hk.current_dd_count_25d ?? '—'}D`],
  ];
  document.getElementById('summaryCards').innerHTML = cards.map(([k,v,s]) => `
    <div class="card">
      <div class="k">${k}</div>
      <div class="v">${v}</div>
      <div class="s">${s}</div>
    </div>`).join('');
}

function renderVQC() {
  const s = VQC.summary || {};
  const e = VQC.edge || {};
  const items = [
    ['2D 窗口', s.overall_rate_2d == null ? null : s.overall_rate_2d.toFixed(1) + '%'],
    ['Baseline 2D', s.baseline_overall_rate_2d == null ? null : s.baseline_overall_rate_2d.toFixed(1) + '%'],
    ['Edge 20D', e.edge_20d == null ? null : (e.edge_20d >= 0 ? '+' : '') + e.edge_20d.toFixed(2) + 'pt'],
    ['樣本股數', VQC.sample_total ?? 0],
    ['訊號數', VQC.events_total ?? 0],
    ['中位 20D', s.signal_median_20d == null ? null : s.signal_median_20d.toFixed(2) + '%'],
  ];
  document.getElementById('vqcCards').innerHTML = items.map(([k,v]) => `
    <div class="mini">
      <div class="lab">${k}</div>
      <div class="val">${v == null ? '—' : v}</div>
    </div>`).join('');
  document.getElementById('vqcNote').textContent =
    `更新：${VQC.updated || '—'} · 你可以當佢係「時間窗口」而唔係方向預言。`;
}

function renderDD() {
  const bms = DD.benchmarks || [];
  const hk = (bms[0] && bms[0].summary) || {};
  const items = [
    ['HK 現況', (hk.current_dd_count_25d ?? '—') + 'D'],
    ['總訊號', DD.signals_total ?? 0],
    ['窗口', DD.window_days ?? 25],
    ['跌幅門檻', (DD.drop_pct ?? 0).toFixed(1) + '%'],
    ['最新狀態', stateLabel(hk.current_market_state)],
  ];
  document.getElementById('ddCards').innerHTML = items.map(([k,v]) => `
    <div class="mini">
      <div class="lab">${k}</div>
      <div class="val">${v}</div>
    </div>`).join('');
  document.getElementById('ddNote').textContent =
    `更新：${DD.updated || '—'} · proxy = HSI1! · 主要看大市壓力是否支持你出手。`;
}

function renderBench() {
  const bms = DD.benchmarks || [];
  document.getElementById('benchGrid').innerHTML = bms.map(b => {
    const s = b.summary || {};
    const state = s.current_market_state || 'healthy';
    const cls = state === 'caution' ? 'state-caution' : state === 'under_pressure' || state === 'correction' ? 'state-pressure' : 'state-healthy';
    return `<div class="bench-card">
      <div class="bench-head">
        <div class="bench-name">${b.code} ${b.name}</div>
        <div class="bench-state ${cls}">${stateLabel(state)}</div>
      </div>
      <div class="mini-grid">
        <div class="mini"><div class="lab">25D Count</div><div class="val">${s.current_dd_count_25d ?? '—'}</div></div>
        <div class="mini"><div class="lab">Signal 數</div><div class="val">${s.signal_count ?? 0}</div></div>
        <div class="mini"><div class="lab">Pressure 日</div><div class="val">${s.pressure_days ?? 0}</div></div>
      </div>
      <div class="note">最新：${s.current_date || '—'}</div>
    </div>`;
  }).join('');
}

function renderBars() {
  const totals = {healthy:0, caution:0, under_pressure:0, correction:0};
  for (const b of (DD.benchmarks || [])) {
    const sc = (b.summary && b.summary.state_counts) || {};
    for (const k in totals) totals[k] += sc[k] || 0;
  }
  const total = Object.values(totals).reduce((a,b)=>a+b,0) || 1;
  const rows = [
    ['healthy', totals.healthy, 'bar-fill-green'],
    ['caution', totals.caution, 'bar-fill-amber'],
    ['under pressure', totals.under_pressure, 'bar-fill-red'],
    ['correction', totals.correction, 'bar-fill-blue'],
  ];
  document.getElementById('stateBars').innerHTML = rows.map(([label,count,cls]) => `
    <div class="bar-row">
      <div class="bar-label">${label} <span style="display:inline-block;padding:3px 8px;border-radius:999px;background:rgba(87,166,255,.12);color:#8ec1ff;font-size:11px;font-weight:800">${count}</span></div>
      <div class="bar-track"><div class="${cls}" style="width:${Math.max(3, count/total*100)}%"></div></div>
      <div class="bar-num">${(count/total*100).toFixed(1)}%</div>
    </div>`).join('');
}

document.getElementById('updatedAt').textContent = new Date().toISOString().slice(0, 19).replace('T', ' ');
document.getElementById('vqcUpdated').textContent = VQC.updated || '—';
document.getElementById('ddUpdated').textContent = DD.updated || '—';
renderSummary();
renderCycleTable();
renderVQC();
renderDD();
renderBench();
renderBars();
</script>
</body>
</html>"""

html = html.replace("__VQC_JSON__", VQC_JSON).replace("__DD_JSON__", DD_JSON)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Generated {OUT_PATH} ({len(html)} bytes)")
