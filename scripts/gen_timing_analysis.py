#!/usr/bin/env python3
"""Generate combined timing signal table."""

from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
VQC_PATH = BASE / "data" / "vqc_backtest.json"
DD_PATH = BASE / "data" / "distribution_day_backtest.json"
JIEQI_PATH = BASE / "data" / "jieqi_backtest.json"
OUT_PATH = BASE / "timing_analysis.html"


def load_json(path: Path, default: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def fmt_pct(value) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


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


def state_label(value) -> str:
    if value == "under_pressure":
        return "under pressure"
    return str(value or "—")


def distance_label(signal_date: date | None, today: date) -> tuple[str, str]:
    if not signal_date:
        return "—", "state-gray"
    delta = (signal_date - today).days
    if delta == 0:
        return "今日", "state-green"
    if delta > 0:
        return f"D+{delta}", "state-blue"
    return f"D{delta}", "state-gray"


def nav(active: str) -> str:
    items = [
        ("index.html", "🇭🇰 港股牌"),
        ("signals.html", "🔂 信號"),
        ("watchlist.html", "⭐ 自選"),
        ("history.html", "🕰 歷史"),
        ("fundflow.html", "💵 資金"),
        ("rights_analysis.html", "📋 供配股"),
        ("trading_desk.html", "交易台"),
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
:root{--bg:#0b1220;--panel:#111a2c;--line:#27314a;--text:#e5edf8;--muted:#8ea0bf;--green:#2ec27e;--blue:#57a6ff;--red:#ef5350;--amber:#d8a327}
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}a{color:inherit;text-decoration:none}
.site-nav{display:flex;gap:6px 12px;flex-wrap:wrap;padding:8px 12px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:13px;position:sticky;top:0;z-index:40}.site-nav a{color:#94a3b8;white-space:nowrap}.site-nav a.active{color:#38bdf8;font-weight:700}
.wrap{width:min(1260px,calc(100vw - 24px));margin:0 auto;padding:14px 0 28px}.hero{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;padding:18px 16px;background:#10192b;border:1px solid var(--line);border-radius:8px}
.eyebrow{color:var(--blue);font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:800}.title{font-size:30px;font-weight:900;margin-top:4px}.subtitle{color:var(--muted);margin-top:8px;line-height:1.55;max-width:880px;font-size:13px}.hero-meta{text-align:right;color:var(--muted);font-size:12px;min-width:180px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.card{background:#10192b;border:1px solid var(--line);border-radius:8px;padding:12px 14px}.card .k{color:var(--muted);font-size:11px}.card .v{font-size:24px;font-weight:900;margin-top:4px}.card .s{color:var(--muted);font-size:11px;margin-top:5px}
.panel{background:#0f172a;border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-top:12px}.panel-title{font-size:14px;font-weight:800;margin-bottom:10px}.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:1020px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #1f2a40;font-size:12px;white-space:nowrap}th{color:var(--muted);font-weight:800}tr.future td{background:rgba(87,166,255,.06)}
.pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:800}.kind-jieqi{background:rgba(87,166,255,.13);color:#8ec1ff}.kind-dd{background:rgba(239,83,80,.13);color:#ff9a98}.kind-vqc{background:rgba(46,194,126,.12);color:#6fe3a4}
.state-green{background:rgba(46,194,126,.12);color:#6fe3a4}.state-blue{background:rgba(87,166,255,.13);color:#8ec1ff}.state-gray{background:rgba(148,163,184,.12);color:#cbd5e1}
.count-cell{display:grid;grid-template-columns:42px 120px;gap:8px;align-items:center}.count-num{font-weight:900}.log-track{height:10px;border:1px solid #24304a;background:#17233a;border-radius:999px;overflow:hidden}.log-fill{display:block;height:100%;background:linear-gradient(90deg,#57a6ff,#2ec27e)}
.note{color:var(--muted);max-width:420px;overflow:hidden;text-overflow:ellipsis}.foot{color:var(--muted);font-size:11px;margin-top:12px;line-height:1.5}
@media(max-width:900px){.wrap{width:auto;padding:12px}.hero{flex-direction:column;align-items:flex-start}.hero-meta{text-align:left}.cards{grid-template-columns:1fr 1fr}}
"""


def jieqi_rows(data: dict, today: date) -> list[dict]:
    calendar = ((data.get("calendar") or {}).get("years") or {})
    term_stats = data.get("term_stats") or []
    stats_by_id = {i + 1: stat for i, stat in enumerate(term_stats[:24])}
    entries = []
    for year, terms in calendar.items():
        if not isinstance(terms, dict):
            continue
        for raw_id, item in terms.items():
            try:
                term_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            d = parse_day(item.get("date"))
            if not d:
                continue
            if d < today:
                continue
            stat = stats_by_id.get(term_id, {})
            count = stat.get("window_count") or stat.get("count") or 0
            entries.append(
                {
                    "date": d,
                    "date_text": d.isoformat(),
                    "kind": "節氣窗口",
                    "kind_class": "kind-jieqi",
                    "signal": item.get("name", ""),
                    "scope": "±2 交易日",
                    "count": count,
                    "note": f"序號 {term_id}",
                    "future": True,
                }
            )
    entries.sort(key=lambda r: r["date"])
    return entries[:8]


def distribution_rows(data: dict) -> list[dict]:
    rows = []
    for bench in data.get("benchmarks", []) or []:
        label = bench.get("label") or bench.get("name") or bench.get("symbol") or bench.get("key")
        for signal in bench.get("signals", []) or []:
            d = parse_day(signal.get("date"))
            if not d:
                continue
            rows.append(
                {
                    "date": d,
                    "date_text": d.isoformat(),
                    "kind": "分佈日",
                    "kind_class": "kind-dd",
                    "signal": f"{label} · {state_label(signal.get('market_state'))}",
                    "scope": f"{signal.get('dd_count_25d', '—')} / 25D",
                    "count": signal.get("dd_count_25d"),
                    "note": f"{fmt_pct(signal.get('pct_change'))} · 量比 {signal.get('volume_ratio', '—')}",
                    "future": False,
                }
            )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:10]


def vqc_rows(data: dict) -> list[dict]:
    by_date: dict[date, list[dict]] = defaultdict(list)
    for event in data.get("events", []) or []:
        d = parse_day(event.get("signal_date"))
        if d:
            by_date[d].append(event)
    rows = []
    for d, events in by_date.items():
        codes = ", ".join(str(e.get("code", "")) for e in events[:8])
        rows.append(
            {
                "date": d,
                "date_text": d.isoformat(),
                "kind": "成交轉勢日",
                "kind_class": "kind-vqc",
                "signal": f"{len(events)} 隻股票",
                "scope": "個股高成交窗口",
                "count": len(events),
                "note": codes,
                "future": False,
            }
        )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:10]


def render_table(rows: list[dict], today: date) -> str:
    max_count = max([r.get("count") or 0 for r in rows] or [0])
    out = []
    for row in rows:
        dist, dist_cls = distance_label(row.get("date"), today)
        tr_cls = ' class="future"' if row.get("future") else ""
        out.append(
            f"<tr{tr_cls}>"
            f"<td>{esc(row['date_text'])}</td>"
            f"<td><span class=\"pill {row['kind_class']}\">{esc(row['kind'])}</span></td>"
            f"<td>{esc(row['signal'])}</td>"
            f"<td><span class=\"pill {dist_cls}\">{esc(dist)}</span></td>"
            f"<td>{esc(row['scope'])}</td>"
            f"<td>{count_cell(row.get('count'), max_count)}</td>"
            f"<td class=\"note\">{esc(row.get('note'))}</td>"
            "</tr>"
        )
    return "\n".join(out) or '<tr><td colspan="7">暫無訊號</td></tr>'


def main() -> None:
    today = date.today()
    page_updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    vqc = load_json(VQC_PATH, {"events": [], "updated": ""})
    dd = load_json(DD_PATH, {"benchmarks": [], "updated": ""})
    jieqi = load_json(JIEQI_PATH, {"calendar": {"years": {}}, "term_stats": [], "updated": ""})

    future_rows = jieqi_rows(jieqi, today)
    recent_dd = distribution_rows(dd)
    recent_vqc = vqc_rows(vqc)
    rows = future_rows + recent_dd + recent_vqc
    latest_dd = recent_dd[0] if recent_dd else {}
    latest_vqc = recent_vqc[0] if recent_vqc else {}
    next_signal = future_rows[0] if future_rows else {}

    html_out = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>時間窗口訊號表</title>
<style>{STYLE}</style>
</head>
<body>
<nav class="site-nav">{nav("timing_analysis.html")}</nav>
<main class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">TIMING SIGNALS</div>
      <div class="title">⏱ 時間窗口訊號表</div>
      <div class="subtitle">將節氣窗口、分佈日、成交轉勢日放成同一張日期表；重點係「幾時出現訊號」，唔再用第一屏堆統計圖。</div>
    </div>
    <div class="hero-meta">頁面更新：<b>{esc(page_updated)}</b><br>今日：<b>{esc(today.isoformat())}</b><br>VQC樣本：<b>{esc(str(vqc.get("updated", ""))[:10])}</b><br>DD/Jieqi樣本：<b>{esc(str(dd.get("updated", ""))[:10])} / {esc(str(jieqi.get("updated", ""))[:10])}</b></div>
  </section>
  <section class="cards">
    <div class="card"><div class="k">下一個窗口</div><div class="v">{esc(next_signal.get("date_text", "—"))}</div><div class="s">{esc(next_signal.get("signal", "—"))}</div></div>
    <div class="card"><div class="k">最近分佈日</div><div class="v">{esc(latest_dd.get("date_text", "—"))}</div><div class="s">{esc(latest_dd.get("signal", "—"))}</div></div>
    <div class="card"><div class="k">最近成交轉勢</div><div class="v">{esc(latest_vqc.get("date_text", "—"))}</div><div class="s">{esc(latest_vqc.get("signal", "—"))}</div></div>
    <div class="card"><div class="k">顯示行數</div><div class="v">{len(rows)}</div><div class="s">Count bar 用 log1p</div></div>
  </section>
  <section class="panel">
    <div class="panel-title">下一批 / 最近訊號</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>日期</th><th>類型</th><th>訊號</th><th>距離</th><th>窗口/範圍</th><th>Count (log)</th><th>備註</th></tr></thead>
        <tbody>{render_table(rows, today)}</tbody>
      </table>
    </div>
  </section>
  <div class="foot">來源：VQC、Distribution Day、節氣 calendar JSON。Count bar 使用 log1p 比例，真實數字仍顯示在左邊。</div>
</main>
</body>
</html>
"""
    OUT_PATH.write_text(html_out, encoding="utf-8")
    print(f"Generated {OUT_PATH.name} ({len(html_out)} bytes, {len(rows)} rows)")


if __name__ == "__main__":
    main()
