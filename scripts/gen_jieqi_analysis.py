#!/usr/bin/env python3
"""Generate solar-term signal table from data/jieqi_backtest.json."""

from __future__ import annotations

import html
import json
import math
from datetime import date, datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / "data" / "jieqi_backtest.json"
OUT_PATH = BASE / "jieqi_analysis.html"


def load_data() -> dict:
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {"updated": "", "calendar": {"years": {}}, "term_stats": []}


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


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


def status_label(signal_date: date | None, today: date, is_next: bool) -> tuple[str, str]:
    if not signal_date:
        return "—", "state-gray"
    delta = (signal_date - today).days
    if is_next:
        return f"下一個 · D+{delta}", "state-green"
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
:root{--bg:#0b1220;--panel:#111a2c;--line:#27314a;--text:#e5edf8;--muted:#8ea0bf;--green:#2ec27e;--blue:#57a6ff;--amber:#d8a327}
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}a{color:inherit;text-decoration:none}
.site-nav{display:flex;gap:6px 12px;flex-wrap:wrap;padding:8px 12px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:13px;position:sticky;top:0;z-index:40}.site-nav a{color:#94a3b8;white-space:nowrap}.site-nav a.active{color:#38bdf8;font-weight:700}
.wrap{width:min(1220px,calc(100vw - 24px));margin:0 auto;padding:14px 0 28px}.hero{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;padding:18px 16px;background:#10192b;border:1px solid var(--line);border-radius:8px}
.eyebrow{color:var(--blue);font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:800}.title{font-size:30px;font-weight:900;margin-top:4px}.subtitle{color:var(--muted);margin-top:8px;line-height:1.55;max-width:860px;font-size:13px}.hero-meta{text-align:right;color:var(--muted);font-size:12px;min-width:180px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.card{background:#10192b;border:1px solid var(--line);border-radius:8px;padding:12px 14px}.card .k{color:var(--muted);font-size:11px}.card .v{font-size:26px;font-weight:900;margin-top:4px}.card .s{color:var(--muted);font-size:11px;margin-top:5px}
.panel{background:#0f172a;border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-top:12px}.panel-title{font-size:14px;font-weight:800;margin-bottom:10px}.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:900px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #1f2a40;font-size:12px;white-space:nowrap}th{color:var(--muted);font-weight:800}tr.next td{background:rgba(46,194,126,.08)}
.pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:800}.state-green{background:rgba(46,194,126,.12);color:#6fe3a4}.state-blue{background:rgba(87,166,255,.13);color:#8ec1ff}.state-gray{background:rgba(148,163,184,.12);color:#cbd5e1}
.count-cell{display:grid;grid-template-columns:42px 120px;gap:8px;align-items:center}.count-num{font-weight:900}.log-track{height:10px;border:1px solid #24304a;background:#17233a;border-radius:999px;overflow:hidden}.log-fill{display:block;height:100%;background:linear-gradient(90deg,#57a6ff,#2ec27e)}
.foot{color:var(--muted);font-size:11px;margin-top:12px;line-height:1.5}
@media(max-width:900px){.wrap{width:auto;padding:12px}.hero{flex-direction:column;align-items:flex-start}.hero-meta{text-align:left}.cards{grid-template-columns:1fr 1fr}}
"""


def main() -> None:
    data = load_data()
    today = date.today()
    page_updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    sample_updated = str(data.get("updated", "")).replace("T", " ")[:16] or "—"
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
            stat = stats_by_id.get(term_id, {})
            count = stat.get("window_count") or stat.get("count") or 0
            entries.append(
                {
                    "term_id": term_id,
                    "name": item.get("name", ""),
                    "date": d,
                    "date_text": d.isoformat(),
                    "month": d.strftime("%Y-%m"),
                    "count": count,
                }
            )
    entries.sort(key=lambda r: (r["date"], r["term_id"]))
    future = [r for r in entries if r["date"] >= today]
    rows = future[:18] if future else entries[-18:]
    max_count = max([r.get("count") or 0 for r in rows] or [0])
    next_date = rows[0] if rows else {}

    table_rows = []
    for idx, row in enumerate(rows):
        label, cls = status_label(row.get("date"), today, idx == 0 and bool(future))
        tr_cls = ' class="next"' if idx == 0 and bool(future) else ""
        table_rows.append(
            f"<tr{tr_cls}>"
            f"<td>{esc(row['date_text'])}</td>"
            f"<td>{esc(row['term_id'])}</td>"
            f"<td>{esc(row['name'])}</td>"
            f"<td>{esc(row['month'])}</td>"
            f"<td><span class=\"pill {cls}\">{esc(label)}</span></td>"
            f"<td>{count_cell(row.get('count'), max_count)}</td>"
            f"<td>±2 交易日</td>"
            "</tr>"
        )
    body = "\n".join(table_rows) or '<tr><td colspan="7">暫無節氣日期</td></tr>'

    years = sorted(calendar.keys())
    year_range = f"{years[0]}-{years[-1]}" if years else "—"
    html_out = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
<meta name="robots" content="noindex,nofollow">
<title>節氣窗口訊號表</title>
<style>{STYLE}</style>
</head>
<body>
<nav class="site-nav">{nav("jieqi_analysis.html")}</nav>
<main class="wrap">
  <section class="hero">
    <div>
      <div class="eyebrow">SOLAR TERM WINDOW</div>
      <div class="title">🧭 節氣窗口訊號表</div>
      <div class="subtitle">24 節氣只保留日期窗口；第一屏直接顯示下一批窗口日期、距離今日幾多日、歷史樣本 count。</div>
    </div>
    <div class="hero-meta">頁面更新：<b>{esc(page_updated)}</b><br>樣本更新：<b>{esc(sample_updated)}</b><br>年份：<b>{esc(year_range)}</b><br>樣本：<b>{esc(data.get("sample_total", 0))}</b></div>
  </section>
  <section class="cards">
    <div class="card"><div class="k">下一個窗口</div><div class="v">{esc(next_date.get("date_text", "—"))}</div><div class="s">{esc(next_date.get("name", "—"))}</div></div>
    <div class="card"><div class="k">窗口 Count</div><div class="v">{esc(next_date.get("count", "—"))}</div><div class="s">log bar 以此欄計</div></div>
    <div class="card"><div class="k">節氣數</div><div class="v">{esc(data.get("terms_total", len(entries)))}</div><div class="s">{esc(data.get("years", len(years)))} 年 calendar</div></div>
    <div class="card"><div class="k">今日</div><div class="v">{esc(today.isoformat())}</div><div class="s">按生成日計</div></div>
  </section>
  <section class="panel">
    <div class="panel-title">下一批節氣窗口</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>日期</th><th>序號</th><th>節氣</th><th>月份</th><th>距離</th><th>Count (log)</th><th>窗口</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  </section>
  <div class="foot">來源：節氣 calendar + 節氣訊號 JSON。Count bar 使用 log1p 比例，真實數字仍顯示在左邊。</div>
</main>
</body>
</html>
"""
    OUT_PATH.write_text(html_out, encoding="utf-8")
    print(f"Generated {OUT_PATH.name} ({len(html_out)} bytes, {len(rows)} rows)")


if __name__ == "__main__":
    main()
