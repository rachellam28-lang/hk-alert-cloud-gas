#!/usr/bin/env python3
"""Generate a practical daily trade prompt page from VQC + Distribution Day data."""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VQC_PATH = BASE / "data" / "vqc_backtest.json"
DD_PATH = BASE / "data" / "distribution_day_backtest.json"
OUT_PATH = BASE / "daily_trade_prompt.html"


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
        "benchmarks": [],
        "benchmarks_with_data": 0,
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
<title>每日交易提示</title>
<style>
:root {
  --bg:#08101b; --panel:#10192b; --line:#26314a; --text:#e5edf8; --muted:#8ea0bf;
  --green:#2ec27e; --red:#ef5350; --amber:#d8a327; --blue:#57a6ff;
}
* { box-sizing:border-box; }
body { margin:0; background:radial-gradient(circle at top,#101a30 0%,#0b1220 44%,#09101b 100%); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }
a { color:inherit; text-decoration:none; }
.site-nav { display:flex; gap:6px 12px; flex-wrap:wrap; padding:8px 12px; background:#0f172a; border-bottom:1px solid #1e293b; font-size:13px; position:sticky; top:0; z-index:40; }
.site-nav a { color:#94a3b8; white-space:nowrap; }
.site-nav a.active { color:#38bdf8; font-weight:700; }
.wrap { width:min(1280px, calc(100vw - 24px)); margin:0 auto; padding:14px 0 28px; }
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
.grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.mini-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.mini { background:#10192b; border:1px solid #24304a; border-radius:14px; padding:12px; }
.mini .lab { color:var(--muted); font-size:11px; }
.mini .val { font-size:24px; font-weight:900; margin-top:5px; }
.bars { display:grid; gap:10px; }
.bar-row { display:grid; grid-template-columns: 112px 1fr 70px; gap:10px; align-items:center; }
.bar-track { height:14px; background:#18233a; border-radius:999px; overflow:hidden; border:1px solid #24304a; display:flex; }
.bar-fill-green { background:linear-gradient(90deg,#26a269,#3bd17f); }
.bar-fill-amber { background:linear-gradient(90deg,#a77e14,#e4b83a); }
.bar-fill-red { background:linear-gradient(90deg,#c63a36,#ff706d); }
.bar-fill-blue { background:linear-gradient(90deg,#2563eb,#60a5fa); }
.bar-num { text-align:right; color:var(--muted); font-size:12px; }
.pill { display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px; font-weight:800; }
.pill.good { background:rgba(46,194,126,.12); color:#6fe3a4; }
.pill.warn { background:rgba(216,163,39,.12); color:#edcb63; }
.pill.bad { background:rgba(239,83,80,.12); color:#ff9a98; }
.rule-list { color:var(--muted); font-size:13px; line-height:1.7; }
.note { color:var(--muted); font-size:11px; margin-top:10px; line-height:1.5; }
.link-row { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.btn { display:inline-block; border:1px solid #24304a; background:#10192b; color:var(--text); border-radius:999px; padding:8px 12px; font-size:12px; }
.btn.blue { border-color:#3d6fb2; background:#17315a; }
.btn.gold { border-color:#fde68a; color:#f5d06f; }
.btn.red { border-color:#fca5a5; color:#ffb2b2; }
.foot { color:var(--muted); font-size:11px; margin-top:12px; line-height:1.5; }
@media (max-width: 900px) {
  .wrap { width:auto; padding:12px; }
  .hero { flex-direction:column; align-items:flex-start; }
  .hero-meta { text-align:left; min-width:0; }
  .cards, .grid-2, .mini-grid { grid-template-columns:1fr; }
  .bar-row { grid-template-columns: 92px 1fr 58px; }
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
  <a class="active" href="daily_trade_prompt.html">🚦 每日提示</a>
  <a href="timing_analysis.html">⏱ 時間窗口</a>
  <a href="distribution_day.html">📉 分佈日</a>
  <a href="vqc_analysis.html">📈 成交轉勢日</a>
  <a href="docs/ccass-warroom.html">⚡ 戰情室</a>
  <a href="guide.html">📖 說明書</a>
</nav>

<div class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">DAILY TRADE PROMPT</div>
      <div class="title">今日交易提示</div>
      <div class="subtitle">
        先睇大市環境，再睇時間窗口。呢頁只做實戰提示：如果大市唔支持，就算有 VQC 亦只做觀察；如果大市健康而 VQC 轉勢窗出現，先考慮出手。
      </div>
    </div>
    <div class="hero-meta">
      更新：<b id="updatedAt">__UPDATED__</b><br>
      VQC：<b id="vqcUpdated">__VQC_UPDATED__</b><br>
      分佈日：<b id="ddUpdated">__DD_UPDATED__</b>
    </div>
  </section>

  <section class="cards" id="summaryCards"></section>

  <section class="panel">
    <div class="panel-title">今日總結</div>
    <div class="mini-grid" id="decisionGrid"></div>
    <div class="note" id="decisionNote"></div>
    <div class="link-row">
      <a class="btn blue" href="timing_analysis.html">開時間窗口</a>
      <a class="btn gold" href="distribution_day.html">開分佈日</a>
      <a class="btn red" href="vqc_analysis.html">開成交轉勢日</a>
    </div>
  </section>

  <div class="grid-2">
    <section class="panel">
      <div class="panel-title">市場濾網</div>
      <div class="bars" id="marketBars"></div>
      <div class="note" id="marketNote"></div>
    </section>
    <section class="panel">
      <div class="panel-title">時間窗口 trigger</div>
      <div class="bars" id="triggerBars"></div>
      <div class="note" id="triggerNote"></div>
    </section>
  </div>

  <section class="panel">
    <div class="panel-title">今日執行規則</div>
    <div class="rule-list" id="rules"></div>
  </section>

  <div class="foot">
    呢頁係工作提示，不係投資建議。`分佈日` 做環境，`成交轉勢日` 做 timing，兩者一齊睇先最實用。
  </div>
</div>

<script>
const VQC = __VQC_JSON__;
const DD = __DD_JSON__;

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%';
}
function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }
function stateLabel(s) {
  if (s === 'correction') return 'correction';
  if (s === 'under_pressure') return 'under pressure';
  if (s === 'caution') return 'caution';
  return 'healthy';
}
function stateScore(s) {
  if (s === 'healthy') return 82;
  if (s === 'caution') return 63;
  if (s === 'under_pressure') return 42;
  if (s === 'correction') return 18;
  return 50;
}
function verdict(score) {
  if (score >= 75) return ['可以做', 'good'];
  if (score >= 60) return ['選擇性做', 'warn'];
  if (score >= 45) return ['偏保守', 'warn'];
  return ['唔好新開倉', 'bad'];
}

function getBench(name) {
  return (DD.benchmarks || []).find(b => b.key === name) || {};
}

function renderSummary() {
  const vs = VQC.summary || {};
  const edge = VQC.edge || {};
  const hk = getBench('hk').summary || {};
  const us = getBench('us').summary || {};
  const hkState = hk.current_market_state || 'healthy';
  const usState = us.current_market_state || 'healthy';
  const marketScore = clamp(Math.round((stateScore(hkState) * 0.7) + (stateScore(usState) * 0.3)), 0, 100);
  const vqcBase = (vs.overall_rate_2d ?? 50) - (vs.baseline_overall_rate_2d ?? 50);
  const vqcEdge = edge.edge_turn_2d ?? 0;
  const vqcScore = clamp(Math.round(50 + vqcBase * 1.8 + vqcEdge * 2.2), 0, 100);
  const combined = clamp(Math.round(marketScore * 0.6 + vqcScore * 0.4), 0, 100);
  const [action, cls] = verdict(combined);
  const cards = [
    ['今日判斷', action, `score ${combined}/100`],
    ['市場濾網', stateLabel(hkState), `HK ${hk.current_dd_count_25d ?? '—'}D / US ${us.current_dd_count_25d ?? '—'}D`],
    ['VQC 信號', vs.overall_rate_2d == null ? '—' : vs.overall_rate_2d.toFixed(1) + '%', `edge ${vqcEdge >= 0 ? '+' : ''}${vqcEdge.toFixed(1)}pt`],
    ['環境基調', marketScore >= 70 ? '偏好' : marketScore >= 50 ? '中性' : '偏弱', `市場 ${marketScore} / VQC ${vqcScore}`],
  ];
  document.getElementById('summaryCards').innerHTML = cards.map(([k,v,s]) => `
    <div class="card">
      <div class="k">${k}</div>
      <div class="v">${v}</div>
      <div class="s">${s}</div>
    </div>`).join('');

  document.getElementById('decisionGrid').innerHTML = `
    <div class="mini"><div class="lab">行動</div><div class="val"><span class="pill ${cls}">${action}</span></div></div>
    <div class="mini"><div class="lab">總分</div><div class="val">${combined}</div></div>
    <div class="mini"><div class="lab">市場分</div><div class="val">${marketScore}</div></div>`;

  const notes = [];
  if (hkState === 'correction' || usState === 'correction') notes.push('大市已入 correction，先防守，唔好追新倉。');
  else if (hkState === 'under_pressure') notes.push('HK 市況受壓，只做最強 trigger。');
  else if (hkState === 'caution') notes.push('大市偏緊，要收窄出手條件。');
  else notes.push('大市環境正常，VQC 有機會先值得跟。');
  if ((vs.overall_rate_2d ?? 0) < (vs.baseline_overall_rate_2d ?? 0)) notes.push('VQC 回測未見 edge，信號只作觀察。');
  else notes.push('VQC 數字對 baseline 有優勢，可作 timing 參考。');
  document.getElementById('decisionNote').textContent = notes.join(' ');

  document.getElementById('updatedAt').textContent = new Date().toISOString().slice(0, 19).replace('T', ' ');
  document.getElementById('vqcUpdated').textContent = VQC.updated || '—';
  document.getElementById('ddUpdated').textContent = DD.updated || '—';
}

function renderBars() {
  const vs = VQC.summary || {};
  const hk = (getBench('hk').summary || {});
  const us = (getBench('us').summary || {});
  const marketState = [
    ['HK 狀態', stateLabel(hk.current_market_state), 'bar-fill-blue', stateScore(hk.current_market_state)],
    ['US 狀態', stateLabel(us.current_market_state), 'bar-fill-green', stateScore(us.current_market_state)],
    ['市場總分', 'market', 'bar-fill-amber', clamp(Math.round((stateScore(hk.current_market_state || 'healthy') * 0.7) + (stateScore(us.current_market_state || 'healthy') * 0.3)), 0, 100)],
  ];
  const triggerState = [
    ['VQC 整體2D', fmtPct(vs.overall_rate_2d), 'bar-fill-green', clamp(Math.round((vs.overall_rate_2d ?? 0)), 0, 100)],
    ['VQC Baseline', fmtPct(vs.baseline_overall_rate_2d), 'bar-fill-amber', clamp(Math.round((vs.baseline_overall_rate_2d ?? 0)), 0, 100)],
    ['VQC Edge', (VQC.edge?.edge_turn_2d == null ? '—' : (VQC.edge.edge_turn_2d >= 0 ? '+' : '') + VQC.edge.edge_turn_2d.toFixed(1) + 'pt'), 'bar-fill-red', clamp(Math.round(50 + (VQC.edge?.edge_turn_2d ?? 0) * 5), 0, 100)],
  ];
  document.getElementById('marketBars').innerHTML = marketState.map(([label,val,cls,pct]) => `
    <div class="bar-row">
      <div class="bar-label">${label} <span class="pill ${pct >= 70 ? 'good' : pct >= 50 ? 'warn' : 'bad'}">${val}</span></div>
      <div class="bar-track"><div class="${cls}" style="width:${Math.max(3, pct)}%"></div></div>
      <div class="bar-num">${pct.toFixed(0)}</div>
    </div>`).join('');
  document.getElementById('triggerBars').innerHTML = triggerState.map(([label,val,cls,pct]) => `
    <div class="bar-row">
      <div class="bar-label">${label} <span class="pill ${pct >= 70 ? 'good' : pct >= 50 ? 'warn' : 'bad'}">${val}</span></div>
      <div class="bar-track"><div class="${cls}" style="width:${Math.max(3, pct)}%"></div></div>
      <div class="bar-num">${pct.toFixed(0)}</div>
    </div>`).join('');

  document.getElementById('marketNote').textContent =
    `HK: ${stateLabel(hk.current_market_state)} · current ${hk.current_dd_count_25d ?? '—'}D · pressure days ${hk.pressure_days ?? 0}`;
  document.getElementById('triggerNote').textContent =
    `VQC events ${VQC.events_total ?? 0} · 2D window 以 ${VQC.summary?.overall_rate_2d ?? '—'}% 作主參考。`;
}

function renderRules() {
  const hk = getBench('hk').summary || {};
  const us = getBench('us').summary || {};
  const hkState = hk.current_market_state || 'healthy';
  const usState = us.current_market_state || 'healthy';
  const vqc = VQC.summary || {};
  const lines = [
    hkState === 'correction' || usState === 'correction'
      ? '1. 今日不宜主動加倉，先等大市壓力降級。'
      : '1. 可以做，但只限有明確 trigger 嘅標的。',
    hkState === 'under_pressure'
      ? '2. 若要出手，只做最強、最乾淨、最少噪音嘅 setup。'
      : '2. 若見到 VQC 窗口，先睇成交反應再決定。',
    (vqc.overall_rate_2d ?? 0) >= (vqc.baseline_overall_rate_2d ?? 0)
      ? '3. VQC 有 edge，可以當 timing 參考。'
      : '3. VQC 無明顯 edge，只當觀察。',
    '4. 任何情況都唔好單靠一個信號就重倉。',
    '5. 如果你要執行，先選市場方向，再選個股時間窗。',
  ];
  document.getElementById('rules').innerHTML = lines.map(x => `${x}<br>`).join('');
}

renderSummary();
renderBars();
renderRules();
</script>
</body>
</html>"""

html = html.replace("__VQC_JSON__", VQC_JSON).replace("__DD_JSON__", DD_JSON)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Generated {OUT_PATH} ({len(html)} bytes)")
