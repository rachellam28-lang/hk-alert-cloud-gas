#!/usr/bin/env python3
"""Generate Distribution Day signal table from data/distribution_day_backtest.json."""

from __future__ import annotations

import html
import json
import math
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / "data" / "distribution_day_backtest.json"
OUT_PATH = BASE / "distribution_day.html"


def load_data() -> dict:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {
        "updated": "",
        "signals_total": 0,
        "benchmarks_with_data": 0,
        "benchmarks": [],
        "window_days": 25,
        "drop_pct": 0.2,
    }


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_num(value, digits=2) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(value) -> str:
    try:
        if value is None:
            return "—"
        v = float(value)
        return f"{v:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def state_label(value) -> str:
    labels = {
        "healthy": "healthy",
        "caution": "caution",
        "under_pressure": "under pressure",
        "correction": "correction",
    }
    return labels.get(str(value or ""), str(value or "—"))


def state_class(value) -> str:
    if value == "correction":
        return "state-red"
    if value == "under_pressure":
        return "state-orange"
    if value == "caution":
        return "state-amber"
    return "state-green"


def log_width(value, max_value) -> int:
    try:
        v = max(float(value or 0), 0.0)
        mx = max(float(max_value or 0), 0.0)
    except (TypeError, ValueError):
        return 0
    if mx <= 0 or v <= 0:
        return 0
    return max(8, round(math.log1p(v) / math.log1p(mx) * 100))


def count_cell(value, max_value) -> str:
    width = log_width(value, max_value)
    return (
        '<div class="count-cell">'
        f'<span class="count-num">{esc(value if value is not None else "—")}</span>'
        '<span class="log-track">'
        f'<span class="log-fill" style="width:{width}%"></span>'
        "</span></div>"
    )


def nav(active: str) -> str:
    items = [
        ("index.html", "🇭🇰 港股牌"),
        ("signals.html", "🔂 信號"),
        ("watchlist.html", "⭐ 自選"),
        ("history.html", "🕰 歷史"),
        ("gap_fvg.html", "🦅 Gap/FVG"),
        ("fundflow.html", "💵 資金"),
        ("rights_analysis.html", "📋 供配股"),
        ("daily_trade_prompt.html", "🚦 每日提示"),
        ("timing_analysis.html", "⏱ 時間窗口"),
        ("jieqi_analysis.html", "🧭 節氣窗口"),
        ("distribution_day.html", "📉 分佈日"),
        ("vqc_analysis.html", "📈 成交轉勢日"),
        ("docs/ccass-warroom.html", "⚔ 戰情室"),
        ("guide.html", "📉 說明書"),
    ]
    links = []
    for href, label in items:
        cls = ' class="active"' if href == active else ""
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    return "\n".join(links)


STYLE = """
:root{--bg:#0b1220;--panel:#111a2c;--line:#27314a;--text:#e5edf8;--muted:#8ea0bf;--green:#2ec27e;--red:#ef5350;--amber:#d8a327;--blue:#57a6ff;--orange:#fb923c}
*{box-sizing:border-box}
body{margin:0;background:#0b1220;color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
a{color:inherit;text-decoration:none}
.site-nav{display:flex;gap:6px 12px;flex-wrap:wrap;padding:8px 12px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:13px;position:sticky;top:0;z-index:40}
.site-nav a{color:#94a3b8;white-space:nowrap}.site-nav a.active{color:#38bdf8;font-weight:700}
.wrap{width:min(1220px,calc(100vw - 24px));margin:0 auto;padding:14px 0 28px}
.hero{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;padding:18px 16px;background:#10192b;border:1px solid var(--line);border-radius:8px}
.eyebrow{color:var(--blue);font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:800}.title{font-size:30px;font-weight:900;margin-top:4px}
.subtitle{color:var(--muted);margin-top:8px;line-height:1.55;max-width:860px;font-size:13px}.hero-meta{text-align:right;color:var(--muted);font-size:12px;min-width:180px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.card{background:#10192b;border:1px solid var(--line);border-radius:8px;padding:12px 14px}.card .k{color:var(--muted);font-size:11px}.card .v{font-size:26px;font-weight:900;margin-top:4px}.card .s{color:var(--muted);font-size:11px;margin-top:5px}
.panel{background:#0f172a;border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-top:12px}.panel-title{font-size:14px;font-weight:800;margin-bottom:10px}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:920px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #1f2a40;font-size:12px;white-space:nowrap}th{color:var(--muted);font-weight:800}tr:hover td{background:rgba(39,49,74,.22)}
.pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:800}.state-green{background:rgba(46,194,126,.12);color:#6fe3a4}.state-amber{background:rgba(216,163,39,.13);color:#edcb63}.state-orange{background:rgba(251,146,60,.13);color:#fdba74}.state-red{background:rgba(239,83,80,.13);color:#ff9a98}
.count-cell{display:grid;grid-template-columns:42px 120px;gap:8px;align-items:center}.count-num{font-weight:900}.log-track{height:10px;border:1px solid #24304a;background:#17233a;border-radius:999px;overflow:hidden}.log-fill{display:block;height:100%;background:linear-gradient(90deg,#3b82f6,#2ec27e)}
.foot{color:var(--muted);font-size:11px;margin-top:12px;line-height:1.5}
@media(max-width:900px){.wrap{width:auto;padding:12px}.hero{flex-direction:column;align-items:flex-start}.hero-meta{text-align:left}.cards{grid-template-columns:1fr 1fr}}
"""


def main() -> None:
    data = load_data()
    page_updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    sample_updated = str(data.get("updated", "")).replace("T", " ")[:16] or "—"
    rows = []
    for bench in data.get("benchmarks", []) or []:
        label = bench.get("label") or bench.get("name") or bench.get("symbol") or bench.get("key")
        for signal in bench.get("signals", []) or []:
            rows.append(
                {
                    "date": signal.get("date", ""),
                    "benchmark": label,
                    "close": signal.get("close"),
                    "pct_change": signal.get("pct_change"),
                    "volume_ratio": signal.get("volume_ratio"),
                    "count": signal.get("dd_count_25d"),
                    "state": signal.get("market_state"),
                }
            )
    rows.sort(key=lambda r: r["date"], reverse=True)
    max_count = max([r.get("count") or 0 for r in rows] or [0])
    latest = rows[0] if rows else {}
    table_rows = "\n".join(
        "<tr>"
        f"<td>{esc(r['date'])}</td>"
        f"<td>{esc(r['benchmark'])}</td>"
        f"<td>{fmt_num(r['close'], 0)}</td>"
        f"<td class=\"{'neg' if (r.get('pct_change') or 0) < 0 else 'pos'}\">{fmt_pct(r.get('pct_change'))}</td>"
        f"<td>{fmt_num(r.get('volume_ratio'), 2)}x</td>"
        f"<td>{count_cell(r.get('count'), max_count)}</td>"
        f"<td><span class=\"pill {state_class(r.get('state'))}\">{state_label(r.get('state'))}</span></td>"
        "</tr>"
        for r in rows[:120]
    )
    if not table_rows:
        table_rows = '<tr><td colspan="7">暫無訊號</td></tr>'

    html_out = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>分佈日訊號表</title>
<style>{STYLE}</style>
</head>
<body>
<nav class="site-nav">{nav("distribution_day.html")}</nav>
<main class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">DISTRIBUTION DAY</div>
      <div class="title">📉 分佈日訊號表</div>
      <div class="subtitle">用 HSI proxy 記錄市場壓力日期；表格直接顯示最近訊號、25D count 同狀態，唔再將第一屏放成績統計。</div>
    </div>
    <div class="hero-meta">頁面更新：<b>{esc(page_updated)}</b><br>樣本更新：<b>{esc(sample_updated)}</b><br>窗口：<b>{esc(data.get("window_days", 25))}D</b><br>跌幅門檻：<b>{esc(data.get("drop_pct", 0.2))}%</b></div>
  </section>
  <section class="cards">
    <div class="card"><div class="k">最新訊號</div><div class="v">{esc(latest.get("date", "—"))}</div><div class="s">{state_label(latest.get("state"))}</div></div>
    <div class="card"><div class="k">25D Count</div><div class="v">{esc(latest.get("count", "—"))}</div><div class="s">log bar 以此欄計</div></div>
    <div class="card"><div class="k">總訊號</div><div class="v">{esc(data.get("signals_total", len(rows)))}</div><div class="s">benchmarks {esc(data.get("benchmarks_with_data", 0))}</div></div>
    <div class="card"><div class="k">最近收市</div><div class="v">{fmt_num(latest.get("close"), 0)}</div><div class="s">{fmt_pct(latest.get("pct_change"))}</div></div>
  </section>
  <section class="panel">
    <div class="panel-title">最近分佈日</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>日期</th><th>Benchmark</th><th>收市</th><th>跌幅</th><th>量比</th><th>Count (log)</th><th>狀態</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
  </section>
  <div class="foot">來源：分佈日訊號 JSON。Count bar 使用 log1p 比例，真實數字仍顯示在左邊。</div>
</main>
</body>
</html>
"""
    OUT_PATH.write_text(html_out, encoding="utf-8")
    print(f"Generated {OUT_PATH.name} ({len(html_out)} bytes, {len(rows)} rows)")


if __name__ == "__main__":
    main()
