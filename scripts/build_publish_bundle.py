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
    stocks = data.get("stocks", []) if isinstance(data, dict) else []
    trend_rows = [
        stock for stock in stocks
        if stock.get("d5s") is not None and stock.get("d5p") is not None
    ]
    return {
        "path": "holdings.json",
        "updated": data.get("updated"),
        "source": "holdings.db / holdings export",
        "stock_count": data.get("stock_count"),
        "coverage_pct": data.get("coverage_pct"),
        "first_date": data.get("first_date"),
        "is_complete": data.get("is_complete"),
        "trend_reference_dates": data.get("trend_reference_dates", {}),
        "five_day_increase_count": (
            sum(1 for stock in trend_rows if stock["d5s"] > 0 and stock["d5p"] > 0)
            if trend_rows else None
        ),
        "five_day_decrease_count": (
            sum(1 for stock in trend_rows if stock["d5s"] < 0 and stock["d5p"] < 0)
            if trend_rows else None
        ),
    }


def summarize_signals():
    data = load_json(DATA / "signals.json", {})
    groups = data.get("groups", []) if isinstance(data, dict) else []

    def has_ccass_five_day(group):
        cc = group.get("ccass") if isinstance(group, dict) else {}
        try:
            shares = float(cc.get("sharesDelta5d"))
            pct = float(cc.get("pctDelta5d"))
        except (TypeError, ValueError, AttributeError):
            return False
        return shares > 0 and pct > 0

    ccass_groups = [group for group in groups if isinstance(group, dict) and isinstance(group.get("ccass"), dict)]

    return {
        "path": "data/signals.json",
        "updated": data.get("updatedAt") or data.get("updated"),
        "source": "announcements.json + rights_analysis.json + alerts.json + holdings.json",
        "groups": len(groups),
        "with_signals": data.get("totalWithSignals"),
        "with_corp": data.get("totalWithCorp"),
        "ccass_five_day_increase_count": (
            sum(1 for group in ccass_groups if has_ccass_five_day(group))
            if ccass_groups else None
        ),
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
    path = DATA / "history.json"
    data = load_json(path, {})
    days = data.get("days", []) if isinstance(data, dict) else []
    updated = data.get("updated") if isinstance(data, dict) else None
    if not updated and path.exists():
        updated = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return {
        "path": "data/history.json",
        "updated": updated,
        "source": "local alert store",
        "days": len(days) if isinstance(days, list) else None,
        "total": data.get("total") if isinstance(data, dict) else None,
        "latest_event_date": latest_date(days, ("date",)),
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


def summarize_participant_anomalies():
    data = load_json(DATA / "participant_anomalies.json", {})
    anomalies = data.get("anomalies") if isinstance(data, dict) else []
    summary = data.get("summary") if isinstance(data, dict) else {}
    return {
        "path": "data/participant_anomalies.json",
        "updated": data.get("updated") if isinstance(data, dict) else None,
        "date": data.get("date") if isinstance(data, dict) else None,
        "previous_date": data.get("previous_date") if isinstance(data, dict) else None,
        "source": "ccass participant delta/anomaly monitor",
        "count": data.get("count") if isinstance(data, dict) else None,
        "published_count": len(anomalies) if isinstance(anomalies, list) else None,
        "delta_rows": data.get("delta_rows") if isinstance(data, dict) else None,
        "ok": data.get("ok") if isinstance(data, dict) else None,
        "status": data.get("status") if isinstance(data, dict) else None,
        "message": data.get("message") if isinstance(data, dict) else None,
        "summary": summary if isinstance(summary, dict) else {},
    }


def summarize_timesfm():
    data = load_json(DATA / "timesfm.json", {})
    fields = data.get("fields") if isinstance(data, dict) else []
    by_field = data.get("by_field") if isinstance(data, dict) else {}
    return {
        "path": "data/timesfm.json",
        "updated": data.get("updated") if isinstance(data, dict) else None,
        "generated_at": data.get("generated_at") if isinstance(data, dict) else None,
        "source": "TimesFM daily multi-field forecast",
        "primary_field": data.get("primary_field") if isinstance(data, dict) else None,
        "field_count": data.get("field_count") if isinstance(data, dict) else None,
        "horizon": data.get("horizon") if isinstance(data, dict) else None,
        "count": len(data.get("forecasts", [])) if isinstance(data, dict) else None,
        "fields": [
            {
                "field": item.get("field"),
                "count": item.get("count"),
                "error_count": item.get("error_count"),
                "top_codes": item.get("top_codes"),
            }
            for item in (fields or [])
            if isinstance(item, dict)
        ],
        "available_fields": sorted(by_field.keys()) if isinstance(by_field, dict) else [],
        "errors": data.get("errors") if isinstance(data, dict) else None,
    }


def summarize_trade_engine():
    data = load_json(DATA / "trade_engine.json", {})
    summary = data.get("summary") if isinstance(data, dict) else {}
    return {
        "path": "data/trade_engine.json",
        "updated": data.get("built_at") or data.get("updated_at") if isinstance(data, dict) else None,
        "source_updated": data.get("source_updated_at") if isinstance(data, dict) else None,
        "source": data.get("source") if isinstance(data, dict) else None,
        "runtime_version": data.get("runtime_version") if isinstance(data, dict) else None,
        "data_kind": data.get("data_kind") if isinstance(data, dict) else None,
        "is_observed": data.get("is_observed") if isinstance(data, dict) else None,
        "source_snapshot_dates": data.get("source_snapshot_dates") if isinstance(data, dict) else None,
        "universe_count": data.get("universe_count") if isinstance(data, dict) else None,
        "candidate_count": data.get("candidate_count") if isinstance(data, dict) else None,
        "analyzed_count": data.get("analyzed_count") if isinstance(data, dict) else None,
        "scope_count": data.get("scope_count") if isinstance(data, dict) else None,
        "momentum_count": data.get("momentum_count") if isinstance(data, dict) else None,
        "setup_counts": summary.get("setup_counts") if isinstance(summary, dict) else None,
        "top_momentum_symbol": summary.get("top_momentum_symbol") if isinstance(summary, dict) else None,
    }


def summarize_kbar_cache():
    data = load_json(DATA / "kbar_cache.json", {})
    symbols = data.get("symbols") if isinstance(data, dict) else {}
    return {
        "path": "data/kbar_cache.json",
        "updated": data.get("updated_at") if isinstance(data, dict) else None,
        "source": data.get("source") if isinstance(data, dict) else "Longbridge preset K-line cache",
        "symbol_count": len(symbols) if isinstance(symbols, dict) else None,
        "symbols": sorted(symbols.keys()) if isinstance(symbols, dict) else [],
        "supported_intervals": data.get("supported_intervals") if isinstance(data, dict) else [],
        "errors": len(data.get("errors", [])) if isinstance(data, dict) else None,
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


def summarize_sector_rotation():
    data = load_json(DATA / "sector_rotation.json", {})
    sectors = data.get("sectors") if isinstance(data, dict) else {}
    profiles = data.get("profiles") if isinstance(data, dict) else {}
    windows = data.get("windows") if isinstance(data, dict) else {}
    return {
        "path": "data/sector_rotation.json",
        "updated": data.get("updated") if isinstance(data, dict) else None,
        "source": data.get("source") if isinstance(data, dict) else None,
        "method": data.get("method") if isinstance(data, dict) else None,
        "schema_version": data.get("schema_version") if isinstance(data, dict) else None,
        "sector_count": len(sectors) if isinstance(sectors, dict) else 0,
        "coverage": data.get("coverage", {}) if isinstance(data, dict) else {},
        "windows": windows if isinstance(windows, dict) else {},
        "profiles": {
            key: {
                "available": value.get("available"),
                "as_of": value.get("as_of"),
                "short_reference_date": value.get("short_reference_date"),
                "long_reference_date": value.get("long_reference_date"),
                "market_stocks": value.get("market_stocks"),
            }
            for key, value in profiles.items()
            if isinstance(value, dict)
        } if isinstance(profiles, dict) else {},
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


def summarize_market_intel():
    data = load_json(DATA / "market_intel.json", {})
    ranks = data.get("ranks") if isinstance(data, dict) else {}
    rank_rows = sum(
        len(item.get("rows") or []) for item in (ranks or {}).values()
        if isinstance(item, dict)
    )
    movers = data.get("top_movers") if isinstance(data, dict) else {}
    return {
        "path": "data/market_intel.json",
        "updated": data.get("generated_at") if isinstance(data, dict) else None,
        "source": data.get("provider") if isinstance(data, dict) else "Longbridge CLI",
        "data_kind": data.get("data_kind") if isinstance(data, dict) else None,
        "is_observed": data.get("is_observed") if isinstance(data, dict) else None,
        "stale": data.get("stale") if isinstance(data, dict) else None,
        "rank_rows": rank_rows,
        "anomaly_count": len(data.get("anomalies") or []) if isinstance(data, dict) else None,
        "mover_count": len((movers or {}).get("rows") or []) if isinstance(movers, dict) else None,
        "refresh_errors": data.get("refresh_errors") if isinstance(data, dict) else None,
    }


def summarize_options_levels():
    data = load_json(DATA / "options_levels.json", {})
    underlyings = data.get("underlyings") if isinstance(data, dict) else []
    return {
        "path": "data/options_levels.json",
        "updated": data.get("generated_at") if isinstance(data, dict) else None,
        "observed_date": data.get("observed_date") if isinstance(data, dict) else None,
        "source": "HKEX official HSI daily report / Futu OpenD / MarketData.app observed option chains",
        "data_kind": data.get("data_kind") if isinstance(data, dict) else None,
        "is_observed": data.get("is_observed") if isinstance(data, dict) else None,
        "status": data.get("status") if isinstance(data, dict) else None,
        "stale": data.get("stale") if isinstance(data, dict) else None,
        "symbols": [item.get("symbol") for item in underlyings if isinstance(item, dict)],
        "expiry_count": sum(len(item.get("expiries") or []) for item in underlyings if isinstance(item, dict)),
        "refresh_errors": data.get("refresh_errors") if isinstance(data, dict) else None,
    }


def summarize_trend_matrix():
    data = load_json(DATA / "trend_matrix.json", {})
    indexes = data.get("indexes") if isinstance(data, dict) else {}
    return {
        "path": "data/trend_matrix.json",
        "updated": data.get("generated_at") if isinstance(data, dict) else None,
        "source": "Futu OpenD observed index daily and main-contract night-session K-lines",
        "data_kind": data.get("data_kind") if isinstance(data, dict) else None,
        "is_observed": data.get("is_observed") if isinstance(data, dict) else None,
        "observations_are_real": data.get("observations_are_real") if isinstance(data, dict) else None,
        "status": data.get("status") if isinstance(data, dict) else None,
        "stale": data.get("stale") if isinstance(data, dict) else None,
        "indexes": list(indexes) if isinstance(indexes, dict) else [],
        "daily_observed_through": {
            key: item.get("daily_observed_through")
            for key, item in indexes.items()
            if isinstance(item, dict)
        } if isinstance(indexes, dict) else {},
        "night_observed_through": {
            key: item.get("night_observed_through")
            for key, item in indexes.items()
            if isinstance(item, dict)
        } if isinstance(indexes, dict) else {},
        "errors": data.get("errors") if isinstance(data, dict) else None,
    }


def summarize_short_positions():
    data = load_json(DATA / "short_positions.json", {})
    return {
        "path": "data/short_positions.json",
        "updated": data.get("generated_at") if isinstance(data, dict) else None,
        "report_date": data.get("report_date") if isinstance(data, dict) else None,
        "previous_report_date": data.get("previous_report_date") if isinstance(data, dict) else None,
        "source": data.get("provider") if isinstance(data, dict) else "SFC Hong Kong",
        "data_kind": data.get("data_kind") if isinstance(data, dict) else None,
        "is_observed": data.get("is_observed") if isinstance(data, dict) else None,
        "stale": data.get("stale") if isinstance(data, dict) else None,
        "row_count": data.get("row_count") if isinstance(data, dict) else None,
        "coverage_note": data.get("coverage_note") if isinstance(data, dict) else None,
    }


def summarize_repo_audit():
    data = load_json(DATA / "repo_audit.json", {})
    pages = data.get("pages") if isinstance(data, dict) else []
    dates = data.get("dates") if isinstance(data, dict) else {}
    db = data.get("db") if isinstance(data, dict) else {}
    missing_ref_pages = sum(
        1 for page in (pages or [])
        if isinstance(page, dict) and page.get("missing_refs")
    )
    alias_pairs = dates.get("alias_pairs") if isinstance(dates, dict) else []
    alias_mismatches = sum(
        1 for pair in (alias_pairs or [])
        if isinstance(pair, dict) and not pair.get("match")
    )
    return {
        "path": "data/repo_audit.json",
        "updated": data.get("generated_at") if isinstance(data, dict) else None,
        "source": "repo-native audit snapshot",
        "page_count": len(pages) if isinstance(pages, list) else None,
        "missing_ref_pages": missing_ref_pages,
        "date_spread_days": dates.get("spread_days") if isinstance(dates, dict) else None,
        "alias_mismatches": alias_mismatches,
        "db_gap_count": db.get("missing_trading_day_count") if isinstance(db, dict) else None,
        "db_low_coverage_count": db.get("low_coverage_count") if isinstance(db, dict) else None,
    }


def summarize_backtest(name: str, path: Path, source: str):
    data = load_json(path, {})
    updated = data.get("updated") if isinstance(data, dict) else None
    if not updated and path.exists():
        updated = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return {
        "path": path.relative_to(BASE).as_posix(),
        "updated": updated,
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
            [sys.executable, "scripts/audit_gate.py", "--min-coverage", "98.0"],
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
            "status": data.get("publish_status") or data.get("status", "FAIL"),
            "audit_status": data.get("status", "FAIL"),
            "maintenance_status": data.get("maintenance_status", "PASS"),
            "current_warnings": data.get("current_warnings") or [],
            "maintenance_warnings": data.get("maintenance_warnings") or [],
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
            "participant_anomalies": summarize_participant_anomalies(),
            "timesfm": summarize_timesfm(),
            "trade_engine": summarize_trade_engine(),
            "kbar_cache": summarize_kbar_cache(),
            "prices": summarize_prices(),
            "sector_rotation": summarize_sector_rotation(),
            "market": summarize_market(),
            "market_intel": summarize_market_intel(),
            "options_levels": summarize_options_levels(),
            "trend_matrix": summarize_trend_matrix(),
            "short_positions": summarize_short_positions(),
            "repo_audit": summarize_repo_audit(),
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
        "ccass_trend_reference_dates": bundle["files"]["holdings"].get("trend_reference_dates", {}),
        "ccass_five_day_increase_count": (
            bundle["files"]["signals"].get("ccass_five_day_increase_count")
            or bundle["files"]["holdings"].get("five_day_increase_count")
        ),
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
        "participant_anomalies_updated": bundle["files"]["participant_anomalies"]["updated"],
        "participant_anomalies_date": bundle["files"]["participant_anomalies"].get("date"),
        "timesfm_updated": bundle["files"]["timesfm"].get("generated_at") or bundle["files"]["timesfm"].get("updated"),
        "timesfm_primary_field": bundle["files"]["timesfm"].get("primary_field"),
        "trade_engine_updated": bundle["files"]["trade_engine"].get("updated"),
        "trade_engine_source_updated": bundle["files"]["trade_engine"].get("source_updated"),
        "trade_engine_universe_count": bundle["files"]["trade_engine"].get("universe_count"),
        "trade_engine_candidate_count": bundle["files"]["trade_engine"].get("candidate_count"),
        "trade_engine_analyzed_count": bundle["files"]["trade_engine"].get("analyzed_count"),
        "trade_engine_momentum_count": bundle["files"]["trade_engine"].get("momentum_count"),
        "kbar_cache_updated": bundle["files"]["kbar_cache"].get("updated"),
        "prices_updated": bundle["files"]["prices"]["updated"],
        "market_updated": bundle["files"]["market"]["updated"],
        "market_stale": bundle["files"]["market"].get("stale"),
        "market_intel_updated": bundle["files"]["market_intel"].get("updated"),
        "market_intel_stale": bundle["files"]["market_intel"].get("stale"),
        "short_positions_report_date": bundle["files"]["short_positions"].get("report_date"),
        "repo_audit_updated": bundle["files"]["repo_audit"].get("updated"),
        "repo_audit_missing_ref_pages": bundle["files"]["repo_audit"].get("missing_ref_pages"),
        "repo_audit_date_spread_days": bundle["files"]["repo_audit"].get("date_spread_days"),
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
    engine = bundle["files"]["trade_engine"]
    bundle["telegram"]["summary"] += (
        f" | engine={engine.get('source_updated') or 'n/a'} "
        f"{engine.get('analyzed_count') or 0}/{engine.get('candidate_count') or 0} "
        f"of {engine.get('universe_count') or 0}"
    )

    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
