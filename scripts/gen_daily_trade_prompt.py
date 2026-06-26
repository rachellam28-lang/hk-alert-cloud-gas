#!/usr/bin/env python3
"""Generate a practical daily trade prompt page from VQC + Distribution Day data."""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VQC_PATH = BASE / "data" / "vqc_backtest.json"
DD_PATH = BASE / "data" / "distribution_day_backtest.json"
JIEQI_PATH = BASE / "data" / "jieqi_backtest.json"
BUNDLE_PATH = BASE / "data" / "publish_bundle.json"
HOLDINGS_PATH = BASE / "holdings.json"
SIGNALS_PATH = BASE / "data" / "signals.json"
TRADEABLE_PATH = BASE / "data" / "tradeable.json"
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
JIEQI = load_json(
    JIEQI_PATH,
    {
        "updated": "",
        "summary": {},
        "window": {},
        "offset_stats": [],
        "top_terms": [],
        "terms_total": 0,
        "sample_total": 0,
        "universe_total": 0,
    },
)
BUNDLE = load_json(
    BUNDLE_PATH,
    {
        "generated_at": "",
        "publish": {},
        "files": {},
        "headline": {},
        "telegram": {},
    },
)

HOLDINGS = load_json(HOLDINGS_PATH, {"stocks": []})
SIGNALS = load_json(SIGNALS_PATH, {"groups": []})
TRADEABLE = load_json(TRADEABLE_PATH, [])

holdings_map = {}
for s in HOLDINGS.get("stocks", []):
    code = str(s.get("c", "")).zfill(5)
    holdings_map[code] = {
        "code": code,
        "name": s.get("n"),
        "tp": s.get("tp"),
        "t5": s.get("t5"),
        "t10": s.get("t10"),
        "hhi": s.get("hhi"),
        "lp": s.get("lp"),
        "mc": s.get("mc"),
        "chg": s.get("chg"),
        "yo": s.get("yo"),
        "py_pct": s.get("py_pct"),
        "vol": s.get("vol"),
        "avg_vol": s.get("avg_vol"),
    }

signals_map = {}
for g in SIGNALS.get("groups", []):
    code = str(g.get("code", "")).zfill(5)
    sigs = g.get("signals") or []
    sig_labels = []
    for s in sigs:
        if isinstance(s, dict):
            label = s.get("label") or s.get("category") or s.get("type") or ''
            date = s.get("date") or ''
            sig_labels.append(f"{label}{(' '+date) if date else ''}".strip())
        else:
            sig_labels.append(str(s))
    signals_map[code] = {
        "code": code,
        "name": g.get("name"),
        "latestPrice": g.get("latestPrice"),
        "signal_count": len(sigs),
        "signals": sig_labels[:5],
        "corpTypes": g.get("corpTypes") or {},
        "issuer": g.get("issuer"),
        "hkexLink": g.get("hkexLink") or "",
    }

tradeable_map = {}
for item in TRADEABLE:
    code = str(item.get("code", "")).zfill(5)
    prev = tradeable_map.get(code)
    if prev is None or (item.get("score") or 0) > (prev.get("score") or 0):
        tradeable_map[code] = {
            "code": code,
            "name": item.get("name"),
            "date": item.get("date"),
            "typeLabel": item.get("typeLabel"),
            "direction": item.get("direction"),
            "score": item.get("score"),
            "label": item.get("label"),
            "label_class": item.get("label_class"),
            "reasons": item.get("reasons") or [],
            "signal_count": item.get("signal_count"),
            "pattern": item.get("pattern"),
        }

VQC_JSON = json.dumps(VQC, ensure_ascii=False)
DD_JSON = json.dumps(DD, ensure_ascii=False)
JIEQI_JSON = json.dumps(JIEQI, ensure_ascii=False)
HOLDINGS_JSON = json.dumps(holdings_map, ensure_ascii=False)
SIGNALS_JSON = json.dumps(signals_map, ensure_ascii=False)
TRADEABLE_JSON = json.dumps(tradeable_map, ensure_ascii=False)

html = r"""<!DOCTYPE html>
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
  <a href="jieqi_analysis.html">🧭 節氣窗口</a>
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
    <div class="panel-title">今日節氣窗口</div>
    <div class="mini-grid" id="jieqiCards"></div>
    <div class="note" id="jieqiNote"></div>
    <div class="link-row">
      <a class="btn teal" href="jieqi_analysis.html">開節氣窗口</a>
    </div>
  </section>

  <section class="panel">
    <div class="panel-title">今日總結</div>
    <div class="mini-grid" id="decisionGrid"></div>
    <div class="note" id="decisionNote"></div>
    <div class="link-row">
      <a class="btn blue" href="timing_analysis.html">開時間窗口</a>
      <a class="btn teal" href="jieqi_analysis.html">開節氣窗口</a>
      <a class="btn gold" href="distribution_day.html">開分佈日</a>
      <a class="btn red" href="vqc_analysis.html">開成交轉勢日</a>
    </div>
  </section>

  <section class="panel">
    <div class="panel-title">CCASS 教室</div>
    <div class="mini-grid" id="ccassCards"></div>
    <div class="note" id="ccassNote"></div>
  </section>

  <section class="panel">
    <div class="panel-title">自選股版每日提示</div>
    <div class="mini-grid" id="watchlistCards"></div>
    <div class="note" id="watchlistNote"></div>
  </section>

  <section class="panel">
    <div class="panel-title">今日留意股票清單</div>
    <div class="table-wrap" style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;min-width:1050px">
        <thead>
          <tr style="text-align:left;color:var(--muted);font-size:11px">
            <th style="padding:8px 10px">代號</th>
            <th style="padding:8px 10px">名稱</th>
            <th style="padding:8px 10px">現價</th>
            <th style="padding:8px 10px">Market%</th>
            <th style="padding:8px 10px">5D</th>
            <th style="padding:8px 10px">20D</th>
            <th style="padding:8px 10px">訊號 / 可炒</th>
            <th style="padding:8px 10px">公告拆解</th>
            <th style="padding:8px 10px">今日原因</th>
          </tr>
        </thead>
        <tbody id="watchlistTable"></tbody>
      </table>
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
  <div class="foot" id="tradePromptFoot">
    更新於：載入中…<br>
    數據來源：data/vqc_backtest.json · data/distribution_day_backtest.json · holdings.json · localStorage（hk_watchlist_v1）
  </div>
</div>

<script>
const VQC = __VQC_JSON__;
const DD = __DD_JSON__;
const JIEQI = __JIEQI_JSON__;
const PUBLISH_BUNDLE = __BUNDLE_JSON__;
const HOLDINGS = __HOLDINGS_JSON__;
const SIGNALS = __SIGNALS_JSON__;
const TRADEABLE = __TRADEABLE_JSON__;

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

function loadWatchlist() {
  try {
    return JSON.parse(localStorage.getItem('hk_watchlist_v1') || '[]');
  } catch {
    return [];
  }
}

function normCode(code) {
  const s = String(code || '').trim().toUpperCase();
  if (!s) return '';
  return /^\d+$/.test(s) ? s.padStart(5, '0') : s;
}

function pickWatchData(code) {
  const c = normCode(code);
  return {
    holding: HOLDINGS[c] || null,
    signal: SIGNALS[c] || null,
    tradeable: TRADEABLE[c] || null,
  };
}

function watchScore(bundle, item) {
  let score = 0;
  const t = bundle.tradeable;
  const h = bundle.holding;
  const s = bundle.signal;
  if (t && typeof t.score === 'number') score += t.score;
  if (h && typeof h.chg === 'number') score += Math.max(-20, Math.min(20, h.chg * 4));
  if (h && typeof h.tp === 'number') score += Math.max(0, Math.min(15, h.tp / 8));
  if (s && typeof s.signal_count === 'number') score += Math.min(12, s.signal_count * 1.5);
  if ((item.note || '').trim()) score += 1;
  return Math.round(score);
}

function watchReason(bundle, item) {
  const parts = [];
  const t = bundle.tradeable;
  const h = bundle.holding;
  const s = bundle.signal;
  if (t && t.reasons && t.reasons.length) parts.push(t.reasons[0]);
  if (t && t.label) parts.push(t.label);
  if (s && s.signals && s.signals.length) parts.push(s.signals.slice(0, 2).join(' / '));
  if (h && h.chg != null) parts.push(`Market ${h.chg >= 0 ? '+' : ''}${Number(h.chg).toFixed(2)}%`);
  if ((item.signal || '').trim()) parts.push(item.signal);
  return parts.filter(Boolean).slice(0, 3).join(' · ') || '暫無明確訊號';
}

function issuerStack(issuer) {
  if (!issuer) return '<span class="pill warn">—</span>';
  const shareholder = issuer.shareholder_pressure || issuer;
  const reaction = issuer.reaction || {};
  const reactionPct = reaction.pct != null ? (reaction.pct >= 0 ? '+' : '') + Number(reaction.pct).toFixed(1) + '%' : '—';
  return `
    <div style="display:flex;flex-direction:column;gap:3px">
      <span class="pill ${issuer.cls || 'warn'}">發行方有利度 ${issuer.label || '中性'} ${issuer.score ?? '—'}</span>
      <span class="pill ${shareholder.cls || 'warn'}">股東短期壓力 ${shareholder.label || '中性'} ${shareholder.score ?? '—'}</span>
      <span class="pill ${reaction.cls || 'warn'}">公告後價格反應 ${reactionPct} ${reaction.label || '未足夠數據'}</span>
    </div>`;
}

function renderSummary() {
  const vs = VQC.summary || {};
  const edge = VQC.edge || {};
  const hk = getBench('hk').summary || {};
  const publish = PUBLISH_BUNDLE.publish || {};
  const hkState = hk.current_market_state || 'healthy';
  const marketScore = clamp(Math.round(stateScore(hkState)), 0, 100);
  const vqcBase = (vs.overall_rate_2d ?? 50) - (vs.baseline_overall_rate_2d ?? 50);
  const vqcEdge = edge.edge_turn_2d ?? 0;
  const vqcScore = clamp(Math.round(50 + vqcBase * 1.8 + vqcEdge * 2.2), 0, 100);
  const combined = clamp(Math.round(marketScore * 0.55 + vqcScore * 0.45), 0, 100);
  const [action, cls] = verdict(combined);
  const latestDbDate = publish.latest_db_date || '—';
  const latestDbCount = publish.latest_db_stock_count ?? '—';
  const latestDbCov = publish.latest_db_coverage_pct ?? '—';
  const holdingsUpdated = publish.holdings_updated || '—';
  const cards = [
    ['今日判斷', action, `score ${combined}/100`],
    ['市場濾網', stateLabel(hkState), `HK ${hk.current_dd_count_25d ?? '—'}D`],
    ['VQC 信號', vs.overall_rate_2d == null ? '—' : vs.overall_rate_2d.toFixed(1) + '%', `edge ${vqcEdge >= 0 ? '+' : ''}${vqcEdge.toFixed(1)}pt`],
    ['資料狀態', publish.status || '—', `完整 ${holdingsUpdated} · partial ${latestDbDate} (${latestDbCount}/${latestDbCov}%)`],
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
  if (hkState === 'correction') notes.push('大市已入 correction，先防守，唔好追新倉。');
  else if (hkState === 'under_pressure') notes.push('HK 市況受壓，只做最強 trigger。');
  else if (hkState === 'caution') notes.push('大市偏緊，要收窄出手條件。');
  else notes.push('大市環境正常，VQC 有機會先值得跟。');
  if ((vs.overall_rate_2d ?? 0) < (vs.baseline_overall_rate_2d ?? 0)) notes.push('VQC 回測未見 edge，信號只作觀察。');
  else notes.push('VQC 數字對 baseline 有優勢，可作 timing 參考。');
  if (publish.status === 'PASS') {
    notes.push(`資料已完整 publish：${holdingsUpdated}。`);
  } else {
    notes.push(`最新完整 publish 仍是 ${holdingsUpdated}；DB 最新 partial 係 ${latestDbDate}（${latestDbCount}/${latestDbCov}%）。`);
  }
  document.getElementById('decisionNote').textContent = notes.join(' ');

  const bundleUpdated = PUBLISH_BUNDLE.generated_at || new Date().toISOString().slice(0, 19);
  document.getElementById('updatedAt').textContent = String(bundleUpdated).replace('T', ' ').slice(0, 19);
  document.getElementById('vqcUpdated').textContent = VQC.updated || '—';
  document.getElementById('ddUpdated').textContent = DD.updated || '—';
}

function renderJieqi() {
  const s = JIEQI.summary || {};
  const top = (JIEQI.top_terms || [])[0] || {};
  const cards = [
    ['窗口命中', s.window_rate_any == null ? '—' : s.window_rate_any.toFixed(1) + '%', `baseline ${s.baseline_window_rate_any == null ? '—' : s.baseline_window_rate_any.toFixed(1) + '%'}`],
    ['最佳 offset', s.best_offset == null ? '—' : (s.best_offset > 0 ? '+' : '') + s.best_offset + 'D', `hit ${s.best_offset_rate_2d == null ? '—' : s.best_offset_rate_2d.toFixed(1) + '%'}`],
    ['窗口 Edge', s.edge_window_any == null ? '—' : (s.edge_window_any >= 0 ? '+' : '') + s.edge_window_any.toFixed(1) + 'pt', '±2 trading days'],
    ['首選節氣', top.term_name || '—', `window ${top.window_rate_any == null ? '—' : top.window_rate_any.toFixed(1) + '%'}`],
  ];
  document.getElementById('jieqiCards').innerHTML = cards.map(([k,v,s2]) => `
    <div class="mini">
      <div class="lab">${k}</div>
      <div class="val">${v}</div>
      <div class="note">${s2}</div>
    </div>`).join('');

  const notes = [];
  if (s.window_rate_any == null) {
    notes.push('節氣窗口暫時未有足夠回測資料。');
  } else {
    notes.push(`節氣以 ±${s.window_span_days ?? 2} 個交易日窗口去睇，唔再只睇正日。`);
    notes.push(`目前最佳 offset 係 ${s.best_offset == null ? '—' : (s.best_offset > 0 ? '+' : '') + s.best_offset + 'D'}。`);
    notes.push('如果窗口 edge 無明顯高過 baseline，就只當 calendar anchor。');
  }
  document.getElementById('jieqiNote').textContent = notes.join(' ');
}

function renderWatchlistPrompt() {
  const wl = loadWatchlist().map(x => ({
    ...x,
    code: normCode(x.code),
    name: x.name || '',
  })).filter(x => x.code);

  const bundles = wl.map(item => {
    const bundle = pickWatchData(item.code);
    const score = watchScore(bundle, item);
    const reason = watchReason(bundle, item);
    return { ...item, ...bundle, score, reason };
  }).sort((a, b) => b.score - a.score);

  const active = bundles.filter(x => x.score >= 40);
  const hot = bundles.filter(x => (x.tradeable && (x.tradeable.score || 0) >= 80) || (x.signal && x.signal.signal_count >= 1));

  const cards = [
    ['本機自選', wl.length, 'localStorage hk_watchlist_v1'],
    ['有資料配對', bundles.filter(x => x.holding || x.signal || x.tradeable).length, '可對上 holdings / signals / tradeable'],
    ['今日留意', hot.length, '高分 / 有訊號 / 有可炒形態'],
    ['建議出手', active.length ? active.length : 0, active.length ? '可優先留意' : '暫時偏少'],
  ];
  document.getElementById('watchlistCards').innerHTML = cards.map(([k,v,s]) => `
    <div class="mini">
      <div class="lab">${k}</div>
      <div class="val">${v}</div>
      <div class="note">${s}</div>
    </div>`).join('');

  if (!wl.length) {
    document.getElementById('watchlistNote').textContent =
      '你部機暫時冇本機自選。去自選頁按 ★ 加入，呢度先會即時見到你自己的清單。';
    document.getElementById('watchlistTable').innerHTML =
      '<tr><td colspan="9" style="padding:22px;color:#8ea0bf;text-align:center">暫無本機自選代號</td></tr>';
    return;
  }

  document.getElementById('watchlistNote').textContent =
    '已按今日可留意程度排序：Tradeable 高分 / 有信號 / Market 走勢較強的排前。';

  document.getElementById('watchlistTable').innerHTML = bundles.slice(0, 30).map(x => {
    const t = x.tradeable || {};
    const h = x.holding || {};
    const s = x.signal || {};
    const badge = t.label ? `<span class="pill ${t.label_class || 'warn'}">${t.label}</span>` : (s.signal_count ? '<span class="pill good">有信號</span>' : '<span class="pill warn">觀察</span>');
    const hkex = s.hkexLink ? `<a class="btn" style="padding:3px 8px" href="${s.hkexLink}" target="_blank">HKEX</a>` : '';
    return `<tr>
      <td style="padding:8px 10px;font-weight:700">${x.code}</td>
      <td style="padding:8px 10px">${x.name || h.name || s.name || ''}</td>
      <td style="padding:8px 10px">${h.lp == null ? '—' : Number(h.lp).toFixed(3)}</td>
      <td style="padding:8px 10px">${h.tp == null ? '—' : Number(h.tp).toFixed(1) + '%'}</td>
      <td style="padding:8px 10px;color:${(h.chg ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${h.chg == null ? '—' : (h.chg >= 0 ? '+' : '') + Number(h.chg).toFixed(2) + '%'}</td>
      <td style="padding:8px 10px">${h.t10 == null ? '—' : Number(h.t10).toFixed(1) + '%'}</td>
      <td style="padding:8px 10px">${badge}</td>
      <td style="padding:8px 10px">${issuerStack((x.signal && x.signal.issuer) || (x.tradeable && x.tradeable.issuer) || null)}</td>
      <td style="padding:8px 10px;max-width:360px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${x.reason}${hkex ? ` · ${hkex}` : ''}</td>
    </tr>`;
  }).join('');
}

function renderCcassLesson() {
  const stocks = Object.values(HOLDINGS || {});
  const valid = stocks.filter(s => s && typeof s.d5 === 'number');
  const gainers = valid
    .filter(s => (s.d5 || 0) > 0)
    .sort((a, b) => (b.d5 || 0) - (a.d5 || 0));
  const losers = valid
    .filter(s => (s.d5 || 0) < 0)
    .sort((a, b) => (a.d5 || 0) - (b.d5 || 0));
  const strongBuy = gainers.find(s => (s.su || 0) > 0) || gainers[0];
  const strongSell = losers.find(s => (s.sd || 0) > 0) || losers[0];
  const accCount = valid.filter(s => (s.d5 || 0) > 0 && (s.su || 0) > 0).length;
  const distCount = valid.filter(s => (s.d5 || 0) < 0 && (s.sd || 0) > 0).length;

  const cards = [
    ['增持/收集', accCount, 'd5 > 0 且 su = 1'],
    ['減持/派發', distCount, 'd5 < 0 且 sd = 1'],
    ['最強增持', strongBuy ? `${strongBuy.c}` : '—', strongBuy ? `${strongBuy.n} · ${fmtPct(strongBuy.d5)}` : '暫無'],
    ['最強減持', strongSell ? `${strongSell.c}` : '—', strongSell ? `${strongSell.n} · ${fmtPct(strongSell.d5)}` : '暫無'],
  ];
  document.getElementById('ccassCards').innerHTML = cards.map(([k,v,s]) => `
    <div class="mini">
      <div class="lab">${k}</div>
      <div class="val">${v}</div>
      <div class="note">${s}</div>
    </div>`).join('');

  const hints = [];
  if (strongBuy && strongBuy.d5 >= 10) {
    hints.push(`例子：${strongBuy.c} ${strongBuy.n} 近 5 日 +${strongBuy.d5.toFixed(2)}%，可當「收集窗」示範。`);
  }
  if (strongSell && strongSell.d5 <= -10) {
    hints.push(`例子：${strongSell.c} ${strongSell.n} 近 5 日 ${strongSell.d5.toFixed(2)}%，可當「派發窗」示範。`);
  }
  hints.push('教學重點：CCASS 睇的是「席位變化」，唔係即日方向；要配合股價、成交量、公告先解讀。');
  hints.push('你系統入面可以把呢頁當成「日常解讀層」，而唔係硬訊號。');
  document.getElementById('ccassNote').textContent = hints.join(' ');
}

function renderBars() {
  const vs = VQC.summary || {};
  const hk = (getBench('hk').summary || {});
  const marketState = [
    ['HK 狀態', stateLabel(hk.current_market_state), 'bar-fill-blue', stateScore(hk.current_market_state)],
    ['市場總分', 'market', 'bar-fill-amber', clamp(Math.round(stateScore(hk.current_market_state || 'healthy')), 0, 100)],
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
  const hkState = hk.current_market_state || 'healthy';
  const vqc = VQC.summary || {};
  const lines = [
    hkState === 'correction'
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
renderJieqi();
renderCcassLesson();
renderWatchlistPrompt();
renderBars();
renderRules();

const tradePromptFoot = document.getElementById('tradePromptFoot');
if (tradePromptFoot) {
  const updated = (PUBLISH_BUNDLE.generated_at || VQC.updated || '').replace('T', ' ').slice(0, 16) || '—';
  tradePromptFoot.innerHTML = `更新於：${updated}<br>數據來源：data/publish_bundle.json · data/vqc_backtest.json · data/distribution_day_backtest.json · data/jieqi_backtest.json · holdings.json · localStorage（hk_watchlist_v1）`;
}
</script>
</body>
</html>"""

html = (
    html.replace("__VQC_JSON__", VQC_JSON)
    .replace("__DD_JSON__", DD_JSON)
    .replace("__JIEQI_JSON__", JIEQI_JSON)
    .replace("__BUNDLE_JSON__", json.dumps(BUNDLE, ensure_ascii=False))
    .replace("__HOLDINGS_JSON__", HOLDINGS_JSON)
    .replace("__SIGNALS_JSON__", SIGNALS_JSON)
    .replace("__TRADEABLE_JSON__", TRADEABLE_JSON)
)
OUT_PATH.write_text(html, encoding="utf-8")
print(f"Generated {OUT_PATH} ({len(html)} bytes)")
