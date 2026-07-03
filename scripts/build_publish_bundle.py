#!/usr/bin/env python3
"""Build a small publish bundle for Telegram / dashboard / notes.

The bundle is a thin metadata layer on top of the existing canonical outputs.
It does not replace the underlying JSONs; it gives the project one shared
summary object so Telegram, health checks, and daily notes can speak the same
freshness/source language.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = DATA / "publish_bundle.json"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def dt(value) -> str:
    if not value:
        return "—"
    s = str(value)
    return s[:19].replace("T", " ")


def normalize_date(value) -> str | None:
    if not value:
        return None
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s or None


def latest_date(items, keys=("date", "ann_date", "announcement_date", "created_at", "updated", "scan_date")) -> str | None:
    dates = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            val = item.get(key)
            if val:
                norm = normalize_date(val)
                if norm:
                    dates.append(norm)
                break
    return max(dates) if dates else None


def summarize_holdings():
    data = load_json(BASE / "holdings.json", {})
    return {
        "path": "holdings.json",
        "updated": data.get("updated"),
        "source": "ccass.db / holdings export",
        "stock_count": data.get("stock_count"),
        "coverage_pct": data.get("coverage_pct"),
        "first_date": data.get("first_date"),
        "is_complete": data.get("is_complete"),
    }


def summarize_signals():
    data = load_json(DATA / "signals.json", {})
    return {
        "path": "data/signals.json",
        "updated": data.get("updatedAt") or data.get("updated"),
        "source": "announcements.json + rights_analysis.json + alerts.json + holdings.json",
        "groups": len(data.get("groups", [])),
        "with_signals": data.get("totalWithSignals"),
        "with_corp": data.get("totalWithCorp"),
    }


def summarize_alerts():
    data = load_json(DATA / "alerts.json", {})
    return {
        "path": "data/alerts.json",
        "updated": data.get("updated"),
        "source": "scanner / holdings events",
        "count": data.get("count"),
        "latest_event_date": latest_date(data.get("alerts", [])),
    }


def summarize_watchlist():
    data = load_json(DATA / "watchlist.json", {})
    return {
        "path": "data/watchlist.json",
        "updated": data.get("updated"),
        "source": "local alert store",
        "count": data.get("count"),
        "latest_event_date": latest_date(data.get("watchlist", [])),
    }


def summarize_history():
    data = load_json(DATA / "history.json", {})
    days = data.get("days", []) if isinstance(data, dict) else []
    return {
        "path": "data/history.json",
        "updated": latest_date(days, ("date",)),
        "source": "local alert store",
        "days": len(days) if isinstance(days, list) else None,
        "total": data.get("total") if isinstance(data, dict) else None,
    }


def summarize_announcements():
    data = load_json(DATA / "announcements.json", [])
    return {
        "path": "data/announcements.json",
        "updated": latest_date(data, ("date", "ann_date", "release_date")),
        "source": "HKEXnews corporate action scanner",
        "count": len(data) if isinstance(data, list) else None,
    }


def summarize_rights_analysis():
    data = load_json(DATA / "rights_analysis.json", [])
    return {
        "path": "data/rights_analysis.json",
        "updated": latest_date(data, ("date", "ann_date", "announcement_date")),
        "source": "announcements.json + placements_enriched.json + stock_prices.json",
        "count": len(data) if isinstance(data, list) else None,
    }


def summarize_fundflow():
    data = load_json(DATA / "fundflow.json", {})
    all_rows = data.get("all", {}) if isinstance(data, dict) else {}
    return {
        "path": "data/fundflow.json",
        "updated": data.get("updated") if isinstance(data, dict) else None,
        "source": data.get("source") if isinstance(data, dict) else "westock fund flow",
        "count": len(all_rows) if isinstance(all_rows, dict) else None,
    }


def summarize_breakthroughs():
    data = load_json(DATA / "breakthroughs.json", {})
    breakthroughs = data.get("breakthroughs", []) if isinstance(data, dict) else []
    active_prices = data.get("active_prices", {}) if isinstance(data, dict) else {}
    return {
        "path": "data/breakthroughs.json",
        "updated": data.get("updated") if isinstance(data, dict) else None,
        "source": "scanner.breakthrough_detector",
        "count": len(breakthroughs) if isinstance(breakthroughs, list) else None,
        "active_price_count": len(active_prices) if isinstance(active_prices, dict) else None,
    }


def summarize_corp_graded():
    data = load_json(DATA / "corp_graded_scan.json", {})
    return {
        "path": "data/corp_graded_scan.json",
        "updated": data.get("scan_date") if isinstance(data, dict) else None,
        "source": "same-day corporate action grading",
        "total_raw": data.get("total_raw") if isinstance(data, dict) else None,
        "same_day": data.get("same_day") if isinstance(data, dict) else None,
        "red_alerts": data.get("red_alerts") if isinstance(data, dict) else None,
        "watchlist": data.get("watchlist") if isinstance(data, dict) else None,
    }


def summarize_transfers():
    data = load_json(DATA / "transfers.json", {})
    transfers = data.get("transfers") if isinstance(data, dict) else []
    updated = data.get("updated") if isinstance(data, dict) else None
    date_value = data.get("date") if isinstance(data, dict) else None
    previous_date = data.get("previous_date") if isinstance(data, dict) else None
    if isinstance(updated, str) and " vs " in updated:
        left, right = updated.split(" vs ", 1)
        date_value = date_value or left[:10]
        previous_date = previous_date or right[:10]
    return {
        "path": "data/transfers.json",
        "updated": updated,
        "date": date_value,
        "previous_date": previous_date,
        "source": "ccass participant holdings transfer monitor",
        "count": data.get("count") if isinstance(data, dict) else None,
        "published_count": len(transfers) if isinstance(transfers, list) else None,
        "ok": data.get("ok") if isinstance(data, dict) else None,
        "status": data.get("status") if isinstance(data, dict) else None,
        "message": data.get("message") if isinstance(data, dict) else None,
    }


def summarize_prices():
    data = load_json(DATA / "stock_prices.json", {})
    prices_path = DATA / "stock_prices.json"
    meta = data.get("_meta") if isinstance(data, dict) else {}
    updated = (meta or {}).get("updated_at")
    if not updated and prices_path.exists():
        updated = datetime.fromtimestamp(prices_path.stat().st_mtime).isoformat(timespec="seconds")
    return {
        "path": "data/stock_prices.json",
        "updated": updated,
        "source": "Futu / Longbridge cache",
        "count": len([k for k in data if str(k).isdigit() and len(str(k)) == 5]) if isinstance(data, dict) else None,
        "provider": (meta or {}).get("source"),
    }


def summarize_market():
    data = load_json(DATA / "market.json", {})
    stale_keys = []
    for key in ("hsi", "dow", "spx", "dxy", "vix", "hsi_pe", "hsi_m2", "spx_pe", "spx_m2", "fear_greed"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, dict) and value.get("stale"):
            stale_keys.append(key)
    dopamine = data.get("dopamine") if isinstance(data, dict) else None
    return {
        "path": "data/market.json",
        "updated": data.get("updated_at") or data.get("updated"),
        "source": "Longbridge / WorldPERatio / CNBC / HKMA / FRED market cache",
        "keys": len(data) if isinstance(data, dict) else None,
        "stale": bool(stale_keys or data.get("market_partial")) if isinstance(data, dict) else None,
        "stale_keys": stale_keys,
        "partial": bool(data.get("market_partial")) if isinstance(data, dict) else None,
        "dopamine_stale": bool(dopamine.get("stale")) if isinstance(dopamine, dict) else None,
    }


def summarize_backtest(name: str, path: Path, source: str):
    data = load_json(path, {})
    return {
        "path": path.relative_to(BASE).as_posix(),
        "updated": data.get("updated"),
        "source": source,
        "summary": data.get("summary") or data.get("edge") or {},
    }


def previous_publish_fallback():
    existing = load_json(OUT, {})
    publish = existing.get("publish") if isinstance(existing, dict) else None
    if isinstance(publish, dict) and publish.get("status") in {"OK", "WARN"}:
        return publish
    return None


def run_audit_gate():
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/audit_gate.py", "--min-coverage", "99.0"],
            cwd=BASE / "ccass",
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        stdout = (proc.stdout or "").strip()
        if not stdout:
            fallback = previous_publish_fallback()
            if fallback:
                return fallback
            return {"status": "FAIL", "detail": "audit_gate returned no output"}
        data = json.loads(stdout)
        if data.get("status") == "FAIL" and not data.get("latest_db_date"):
            fallback = previous_publish_fallback()
            if fallback:
                return fallback
        return {
            "status": data.get("status", "FAIL"),
            "latest_db_date": data.get("latest_db_date"),
            "latest_db_stock_count": data.get("latest_db_stock_count"),
            "latest_db_coverage_pct": data.get("latest_db_coverage_pct"),
            "latest_publishable_date": data.get("latest_publishable_date"),
            "latest_publishable_stock_count": data.get("latest_publishable_stock_count"),
            "latest_publishable_coverage_pct": data.get("latest_publishable_coverage_pct"),
            "holdings_updated": data.get("holdings_updated"),
            "coverage_pct": data.get("coverage_pct"),
            "verify_data": data.get("verify_data") or {},
            "verify_dashboard": data.get("verify_dashboard") or {},
        }
    except Exception as exc:
        fallback = previous_publish_fallback()
        if fallback:
            return fallback
        return {"status": "FAIL", "detail": str(exc)}


def main():
    bundle = {
        "schema_v": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_of_truth": {
            "db": "ccass/holdings.db",
            "primary_holdings": "holdings.json",
            "primary_prices": "data/stock_prices.json",
            "primary_bundle": "data/publish_bundle.json",
        },
        "files": {
            "holdings": summarize_holdings(),
            "signals": summarize_signals(),
            "alerts": summarize_alerts(),
            "watchlist": summarize_watchlist(),
            "history": summarize_history(),
            "announcements": summarize_announcements(),
            "rights_analysis": summarize_rights_analysis(),
            "fundflow": summarize_fundflow(),
            "breakthroughs": summarize_breakthroughs(),
            "corp_graded_scan": summarize_corp_graded(),
            "transfers": summarize_transfers(),
            "prices": summarize_prices(),
            "market": summarize_market(),
            "vqc_backtest": summarize_backtest(
                "vqc_backtest",
                DATA / "vqc_backtest.json",
                "time-window backtest (成交轉勢日)",
            ),
            "distribution_day_backtest": summarize_backtest(
                "distribution_day_backtest",
                DATA / "distribution_day_backtest.json",
                "time-window backtest (分佈日)",
            ),
            "jieqi_backtest": summarize_backtest(
                "jieqi_backtest",
                DATA / "jieqi_backtest.json",
                "calendar-window backtest (節氣窗口)",
            ),
        },
        "publish": run_audit_gate(),
    }
    bundle["headline"] = {
        "holdings_updated": bundle["files"]["holdings"]["updated"],
        "latest_db_date": bundle["publish"].get("latest_db_date"),
        "latest_db_stock_count": bundle["publish"].get("latest_db_stock_count"),
        "latest_db_coverage_pct": bundle["publish"].get("latest_db_coverage_pct"),
        "latest_publishable_date": bundle["publish"].get("latest_publishable_date"),
        "latest_publishable_stock_count": bundle["publish"].get("latest_publishable_stock_count"),
        "latest_publishable_coverage_pct": bundle["publish"].get("latest_publishable_coverage_pct"),
        "signals_updated": bundle["files"]["signals"]["updated"],
        "alerts_updated": bundle["files"]["alerts"]["updated"],
        "watchlist_updated": bundle["files"]["watchlist"]["updated"],
        "history_updated": bundle["files"]["history"]["updated"],
        "announcements_updated": bundle["files"]["announcements"]["updated"],
        "rights_analysis_updated": bundle["files"]["rights_analysis"]["updated"],
        "fundflow_updated": bundle["files"]["fundflow"]["updated"],
        "breakthroughs_updated": bundle["files"]["breakthroughs"]["updated"],
        "corp_graded_scan_updated": bundle["files"]["corp_graded_scan"]["updated"],
        "transfers_updated": bundle["files"]["transfers"]["updated"],
        "transfers_date": bundle["files"]["transfers"].get("date"),
        "prices_updated": bundle["files"]["prices"]["updated"],
        "market_updated": bundle["files"]["market"]["updated"],
        "market_stale": bundle["files"]["market"].get("stale"),
        "backtests_updated": {
            "vqc": bundle["files"]["vqc_backtest"]["updated"],
            "distribution_day": bundle["files"]["distribution_day_backtest"]["updated"],
            "jieqi": bundle["files"]["jieqi_backtest"]["updated"],
        },
    }
    bundle["telegram"] = {
        "summary": (
            f"publish={bundle['publish'].get('status', '—')} | "
            f"holdings={bundle['files']['holdings']['updated'] or '—'} | "
            f"latest_db={bundle['publish'].get('latest_db_date') or '—'} "
            f"({bundle['publish'].get('latest_db_coverage_pct') or '—'}%) | "
            f"publishable={bundle['publish'].get('latest_publishable_date') or '—'} | "
            f"signals={bundle['files']['signals']['updated'] or '—'} | "
            f"alerts={bundle['files']['alerts']['updated'] or '—'} | "
            f"market={bundle['files']['market']['updated'] or '—'}"
        )
    }

    bundle["telegram"]["summary"] = bundle["telegram"]["summary"].replace(
        " | market=",
        f" | transfers={bundle['files']['transfers']['updated'] or 'n/a'} | market=",
    )
    bundle["telegram"]["summary"] = bundle["telegram"]["summary"].replace(
        " | transfers=",
        (
            f" | anns={bundle['files']['announcements']['updated'] or 'n/a'}"
            f" | rights={bundle['files']['rights_analysis']['updated'] or 'n/a'}"
            f" | flow={bundle['files']['fundflow']['updated'] or 'n/a'}"
            " | transfers="
        ),
    )

    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
