# -*- coding: utf-8 -*-
"""
health_check.py — 每日系統健康檢查
====================================
每日自動 check + push Telegram。

Checks:
  1. 數據新鮮度 — 各核心 file 嘅 mtime
  2. 公告量異常 — vs 過去 20 日中位數
  3. DeepSeek balance — < $5 就警告
  4. 結構完整性 — corpTypes 全 false / events 零增長

用法:
    python scripts/health_check.py
    python scripts/health_check.py --telegram
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import parse_announcement_date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CCASS_DIR = os.path.join(BASE, "ccass")

WATCH_FILES = {
    "holdings.json":        {"path": os.path.join(BASE, "holdings.json"),              "max_age_h": 26},
    "data/holdings.json":   {"path": os.path.join(BASE, "data", "holdings.json"),      "max_age_h": 26},
    "publish_bundle":      {"path": os.path.join(BASE, "data", "publish_bundle.json"), "max_age_h": 26},
    "signals.json":         {"path": os.path.join(BASE, "data", "signals.json"),       "max_age_h": 26},
    "alerts.json":          {"path": os.path.join(BASE, "data", "alerts.json"),        "max_age_h": 26},
    "announcements.json":   {"path": os.path.join(BASE, "data", "announcements.json"), "max_age_h": 26},
    "events.json":          {"path": os.path.join(BASE, "events.json"),                "max_age_h": 26},
    "price_snapshot":       {"path": os.path.join(BASE, "data", "stock_prices.json"),  "max_age_h": 26},
    "jieqi_backtest":       {"path": os.path.join(BASE, "data", "jieqi_backtest.json"), "max_age_h": 72},
}

DEEPSEEK_BALANCE_WARN = 5.0
ANN_DEVIATION_WARN = 0.7
HEALTH_OUT = os.path.join(BASE, "health.json")
ICON_OK = "🟢"
ICON_WARN = "⚠️"
ICON_FAIL = "🔴"
ICON_SKIP = "⚪"


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _latest_date_from_items(items, keys):
    dates = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            val = item.get(key)
            if not val:
                continue
            dates.append(str(val)[:10])
            break
    return max(dates) if dates else None


def _latest_price_time(data):
    vals = []
    if isinstance(data, dict):
        rows = data.values()
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        val = row.get("price_updated_at") or row.get("lp_time") or row.get("source_date")
        if val:
            vals.append(str(val))
    return max(vals) if vals else None


def _previous_weekday(d):
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def check_freshness():
    rows = []
    for name, cfg in WATCH_FILES.items():
        if not os.path.exists(cfg["path"]):
            rows.append({"name": name, "status": "⚪", "detail": "file missing"})
            continue
        if name in ("holdings.json", "data/holdings.json"):
            data = load_json(cfg["path"], default={}) or {}
            updated = data.get("updated", "—")
            coverage = data.get("coverage_pct")
            stock_count = data.get("stock_count")
            complete = data.get("is_complete")
            if updated in (None, "", "—"):
                status = ICON_FAIL
            elif complete is True:
                status = ICON_OK
            else:
                status = ICON_WARN
            rows.append({
                "name": name,
                "status": status,
                "detail": f"updated={updated} coverage={coverage}% stock_count={stock_count} complete={complete}",
            })
        elif name == "publish_bundle":
            data = load_json(cfg["path"], default={}) or {}
            generated = str(data.get("generated_at") or "—")[:19].replace("T", " ")
            publish = data.get("publish", {}) or {}
            files = data.get("files", {}) or {}
            holdings = files.get("holdings", {}) or {}
            signals = files.get("signals", {}) or {}
            alerts = files.get("alerts", {}) or {}
            publish_status = str(publish.get("status") or "").upper()
            if generated == "—":
                status = ICON_FAIL
            elif publish_status == "PASS":
                status = ICON_OK
            elif publish_status == "WARN":
                status = ICON_WARN
            else:
                status = ICON_FAIL
            rows.append({
                "name": name,
                "status": status,
                "detail": (
                    f"generated={generated} publish={publish.get('status', '—')} "
                    f"holdings={holdings.get('updated', '—')} "
                    f"signals={signals.get('updated', '—')} "
                    f"alerts={alerts.get('updated', '—')}"
                ),
            })
        elif name == "signals.json":
            data = load_json(cfg["path"], default={}) or {}
            updated = str(data.get("updatedAt") or data.get("updated") or "—")[:19].replace("T", " ")
            rows.append({
                "name": name,
                "status": "🟢" if updated != "—" else "🔴",
                "detail": f"updated={updated} groups={len(data.get('groups', []))}",
            })
        elif name == "alerts.json":
            data = load_json(cfg["path"], default={}) or {}
            updated = data.get("updated", "—")
            rows.append({
                "name": name,
                "status": "🟢" if updated not in (None, "", "—") else "🔴",
                "detail": f"updated={updated} count={data.get('count', '—')}",
            })
        elif name == "announcements.json":
            data = load_json(cfg["path"], default=[]) or []
            latest = _latest_date_from_items(data, ("date", "release_time"))
            rows.append({
                "name": name,
                "status": "🟢" if latest else "⚪",
                "detail": f"latest={latest or '—'} count={len(data)}",
            })
        elif name == "events.json":
            data = load_json(cfg["path"], default=[]) or []
            if isinstance(data, dict):
                data = data.get("events", [])
            latest = _latest_date_from_items(data, ("alert_date", "signal_date"))
            rows.append({
                "name": name,
                "status": "🟢" if latest else "⚪",
                "detail": f"latest={latest or '—'} count={len(data)}",
            })
        elif name == "jieqi_backtest":
            data = load_json(cfg["path"], default={}) or {}
            updated = str(data.get("updated") or "—")[:19].replace("T", " ")
            rows.append({
                "name": name,
                "status": "🟢" if updated != "—" else "⚪",
                "detail": f"updated={updated} terms={len(data.get('term_stats', []))}",
            })
        elif name == "price_snapshot":
            data = load_json(cfg["path"], default={}) or {}
            latest = _latest_price_time(data)
            today = datetime.now().date()
            expected = _previous_weekday(today)
            latest_date = None
            if latest:
                try:
                    latest_date = datetime.fromisoformat(str(latest).replace("Z", "+00:00")[:10]).date()
                except Exception:
                    latest_date = None
            if not latest_date:
                status = ICON_FAIL
            elif latest_date >= expected:
                status = ICON_OK
            elif today.weekday() >= 5 and latest_date >= expected:
                status = ICON_OK
            else:
                status = ICON_WARN
            rows.append({
                "name": name,
                "status": status,
                "detail": f"latest_price={latest or '—'} stocks={len(data) if isinstance(data, dict) else '—'}",
            })
        else:
            age_h = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cfg["path"]))).total_seconds() / 3600
            status = "🔴" if age_h > cfg["max_age_h"] else "🟢"
            rows.append({"name": name, "status": status, "detail": f"{age_h:.1f}h old"})
    return rows


def check_announcement_volume():
    anns = load_json(WATCH_FILES["announcements.json"]["path"], default=[])
    if not anns:
        return {"status": "⚪", "detail": "announcements.json empty"}

    today = datetime.now().strftime("%Y-%m-%d")
    by_date = {}
    for a in anns:
        d = parse_announcement_date(a.get("date") or a.get("release_time"))
        if d:
            by_date[d] = by_date.get(d, 0) + 1

    today_n = by_date.get(today, 0)
    past = sorted(by_date.items(), reverse=True)
    past_counts = [n for d, n in past if d != today][:20]

    if len(past_counts) < 5:
        return {"status": "⚪", "detail": f"today={today_n}, baseline too small ({len(past_counts)}d)"}

    med = statistics.median(past_counts)
    if med == 0:
        return {"status": "⚪", "detail": "baseline median=0"}

    dev = abs(today_n - med) / med
    is_weekday = datetime.now().weekday() < 5
    if today_n == 0 and is_weekday:
        return {"status": "⚠️", "detail": f"today 0 vs median {med:.0f} — check scraper"}
    elif dev > ANN_DEVIATION_WARN:
        return {"status": "⚠️", "detail": f"today {today_n} vs median {med:.0f} ({dev*100:.0f}% dev)"}
    return {"status": "🟢", "detail": f"today {today_n} vs median {med:.0f}"}


def check_deepseek_balance():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return {"status": "⚪", "detail": "DEEPSEEK_API_KEY not set"}
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        bal = float(data["balance_infos"][0]["total_balance"])
        cur = data["balance_infos"][0].get("currency", "USD")
        if bal < DEEPSEEK_BALANCE_WARN:
            return {"status": "⚠️", "detail": f"${bal:.2f} {cur} — top up needed"}
        return {"status": "🟢", "detail": f"${bal:.2f} {cur}"}
    except Exception as exc:
        return {"status": "🔴", "detail": f"balance API error: {exc}"}


def check_integrity():
    rows = []

    # Hard consistency check: root holdings.json and data/holdings.json must match.
    root_holdings = load_json(WATCH_FILES["holdings.json"]["path"], default={}) or {}
    data_holdings = load_json(WATCH_FILES["data/holdings.json"]["path"], default={}) or {}
    if root_holdings and data_holdings:
        same_updated = root_holdings.get("updated") == data_holdings.get("updated")
        same_count = root_holdings.get("stock_count") == data_holdings.get("stock_count")
        same_coverage = root_holdings.get("coverage_pct") == data_holdings.get("coverage_pct")
        if not (same_updated and same_count and same_coverage):
            rows.append({
                "name": "holdings-sync",
                "status": "🔴",
                "detail": (
                    f"root={root_holdings.get('updated')} / {root_holdings.get('stock_count')} "
                    f"vs data={data_holdings.get('updated')} / {data_holdings.get('stock_count')}"
                ),
            })
        else:
            rows.append({
                "name": "holdings-sync",
                "status": "🟢",
                "detail": f"updated={root_holdings.get('updated')} count={root_holdings.get('stock_count')}",
            })

    sig = load_json(WATCH_FILES["signals.json"]["path"], default={})
    groups = sig.get("groups", [])
    if groups:
        with_corp = sum(
            1 for g in groups
            if any(g.get("corpTypes", {}).get(t) for t in ("placement", "rights", "increase"))
        )
        if with_corp == 0:
            rows.append({"name": "corpTypes", "status": "🔴",
                         "detail": f"{len(groups)} stocks, 0 corp — pipeline broken!"})
        else:
            rows.append({"name": "corpTypes", "status": "🟢",
                         "detail": f"{with_corp}/{len(groups)} stocks have corp actions"})

    events = load_json(WATCH_FILES["events.json"]["path"], default=[])
    if isinstance(events, dict):
        events = events.get("events", [])
    if events:
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        recent = sum(1 for e in events if e.get("alert_date") in (today, yesterday))
        filled = sum(1 for e in events if e.get("outcome", {}).get("fwd_20d") is not None)
        rows.append({"name": "events", "status": "🟢" if recent or filled else "⚠️",
                     "detail": f"{len(events)} total, {recent} recent, {filled} filled"})
    return rows


def check_ccass_publish():
    """Use the real audit gate so Telegram reflects the actual publish state."""
    bundle = load_json(os.path.join(BASE, "data", "publish_bundle.json"), default={}) or {}
    if bundle:
        publish = bundle.get("publish", {}) or {}
        files = bundle.get("files", {}) or {}
        holdings = files.get("holdings", {}) or {}
        signals = files.get("signals", {}) or {}
        alerts = files.get("alerts", {}) or {}
        announcements = files.get("announcements", {}) or {}
        rights = files.get("rights_analysis", {}) or {}
        fundflow = files.get("fundflow", {}) or {}
        transfers = files.get("transfers", {}) or {}
        latest_db = publish.get("latest_db_date", "—")
        latest_db_count = publish.get("latest_db_stock_count", "—")
        latest_db_cov = publish.get("latest_db_coverage_pct", "—")
        holdings_updated = publish.get("holdings_updated") or holdings.get("updated", "—")
        coverage_pct = publish.get("coverage_pct")
        verify_data_obj = publish.get("verify_data", {}) or {}
        verify_dash_obj = publish.get("verify_dashboard", {}) or {}
        verify_data = verify_data_obj.get("status") or ("WARN" if verify_data_obj.get("warnings") else "PASS")
        verify_dash = verify_dash_obj.get("status") or ("WARN" if verify_dash_obj.get("warnings") else "PASS")
        detail = (
            f"bundle {bundle.get('generated_at', '—')[:19].replace('T', ' ')} | "
            f"DB {latest_db} rows={latest_db_count} cov={latest_db_cov}% | "
            f"publish {holdings_updated} | coverage {coverage_pct}% "
            f"| signals {signals.get('updated', '—')} | alerts {alerts.get('updated', '—')} "
            f"| verify_data {verify_data} | verify_dashboard {verify_dash}"
        )
        detail = detail.replace(
            " | verify_data ",
            (
                f" | anns {announcements.get('updated', 'n/a')}"
                f" | rights {rights.get('updated', 'n/a')}"
                f" | flow {fundflow.get('updated', 'n/a')}"
                f" | transfers {transfers.get('updated', 'n/a')}"
                " | verify_data "
            ),
        )
        if publish.get("status") == "PASS":
            return {"status": "🟢", "detail": detail, "raw": bundle}
        if publish.get("status") == "WARN":
            return {"status": "⚠️", "detail": detail, "raw": bundle}
        if publish.get("status"):
            return {"status": "🔴", "detail": detail, "raw": bundle}
        # fall through if bundle exists but publish block empty
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/audit_gate.py", "--min-coverage", "99.0"],
            cwd=CCASS_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        stdout = (proc.stdout or "").strip()
        if not stdout:
            return {
                "status": "🔴",
                "detail": "audit_gate returned no output",
                "raw": "",
            }
        data = json.loads(stdout)
        status = data.get("status", "FAIL")
        latest_db = data.get("latest_db_date", "—")
        latest_db_count = data.get("latest_db_stock_count", "—")
        latest_db_cov = data.get("latest_db_coverage_pct", "—")
        holdings_updated = data.get("holdings_updated", "—")
        coverage_pct = data.get("coverage_pct", "—")
        verify_data_obj = data.get("verify_data", {}) or {}
        verify_dash_obj = data.get("verify_dashboard", {}) or {}
        verify_data = verify_data_obj.get("status") or ("WARN" if verify_data_obj.get("warnings") else "PASS")
        verify_dash = verify_dash_obj.get("status") or ("WARN" if verify_dash_obj.get("warnings") else "PASS")
        detail = (
            f"DB {latest_db} rows={latest_db_count} cov={latest_db_cov}% | "
            f"publish {holdings_updated} | coverage {coverage_pct}% "
            f"| verify_data {verify_data} | verify_dashboard {verify_dash}"
        )
        if status == "PASS":
            return {"status": "🟢", "detail": detail, "raw": data}
        if status == "WARN":
            return {"status": "⚠️", "detail": detail, "raw": data}
        return {"status": "🔴", "detail": detail, "raw": data}
    except Exception as exc:
        return {"status": "🔴", "detail": f"audit_gate error: {exc}", "raw": ""}


def format_report(freshness, ann_vol, balance, integrity):
    lines = [f"🏥 System Health — {datetime.now().strftime('%Y-%m-%d %H:%M')} HKT", ""]
    lines.append("📁 Freshness")
    for r in freshness:
        lines.append(f"  {r['status']} {r['name']}: {r['detail']}")
    publish = check_ccass_publish()
    lines.append(f"🗃 CCASS publish: {publish['status']} {publish['detail']}")
    lines.append("ℹ️ Longbridge backfill: 只補歷史 holdings，不補 price / signals")
    lines.append(f"📰 Announcements: {ann_vol['status']} {ann_vol['detail']}")
    lines.append(f"💰 DeepSeek: {balance['status']} {balance['detail']}")
    if integrity:
        lines.append("🔧 Integrity")
        for r in integrity:
            lines.append(f"  {r['status']} {r['name']}: {r['detail']}")
    bad = [x for x in freshness + integrity if x["status"] == "🔴"]
    warn = [x for x in [ann_vol, balance] if x["status"] in ("⚠️", "🔴")]
    lines.append("")
    lines.append("❌ ISSUES" if bad else ("⚠️ WARNINGS" if warn else "✅ ALL OK"))
    return "\n".join(lines)


def push_telegram(text):
    token = (
        os.environ.get("HERMES_TELEGRAM_TOKEN", "")
        or os.environ.get("HERMES_TELEGRAM_BOT_TOKEN", "")
        or os.environ.get("HERMES_TG_BOT_TOKEN", "")
        or os.environ.get("HERMES_BOT_TOKEN", "")
        or os.environ.get("TELEGRAM_STATUS_TOKEN", "")
        or os.environ.get("TELEGRAM_TOKEN", "")
        or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        or os.environ.get("TG_BOT_TOKEN", "")
    )
    chat = (
        os.environ.get("HERMES_TELEGRAM_CHAT_ID", "")
        or os.environ.get("HERMES_TG_CHAT_ID", "")
        or os.environ.get("HERMES_CHAT_ID", "")
        or os.environ.get("TELEGRAM_STATUS_CHAT_ID", "")
        or os.environ.get("TELEGRAM_CHAT_ID", "")
        or os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    )
    if not (token and chat):
        print("⚪ no Telegram config, skip push")
        return
    data = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        print("✅ pushed to Telegram")
    except Exception as exc:
        print(f"🔴 Telegram push failed: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    freshness = check_freshness()
    ann_vol = check_announcement_volume()
    balance = check_deepseek_balance()
    integrity = check_integrity()

    report_text = format_report(freshness, ann_vol, balance, integrity)
    print(report_text)

    with open(HEALTH_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "at": datetime.now().isoformat(),
            "freshness": freshness, "ann_volume": ann_vol,
            "deepseek": balance, "integrity": integrity,
        }, f, ensure_ascii=False, indent=1)

    if args.telegram:
        push_telegram(report_text)

    has_red = any(r["status"] == "🔴" for r in freshness + integrity) or balance["status"] == "🔴"
    return 1 if has_red else 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.sentry_cron import run_monitored_callable

    sys.exit(run_monitored_callable("hk-alert-health-check", main))
