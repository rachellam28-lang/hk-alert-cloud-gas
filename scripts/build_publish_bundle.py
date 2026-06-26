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
        "source": "announcements.json + alerts.json + holdings.json",
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
    }


def summarize_prices():
    data = load_json(DATA / "stock_prices.json", {})
    return {
        "path": "data/stock_prices.json",
        "updated": data.get("updated") or data.get("updated_at"),
        "source": "Futu / Longbridge cache",
        "count": len(data.get("stocks", [])) if isinstance(data, dict) else None,
    }


def summarize_market():
    data = load_json(DATA / "market.json", {})
    return {
        "path": "data/market.json",
        "updated": data.get("updated_at") or data.get("updated"),
        "source": "market breadth / fear-greed cache",
        "keys": len(data) if isinstance(data, dict) else None,
    }


def summarize_backtest(name: str, path: Path, source: str):
    data = load_json(path, {})
    return {
        "path": str(path.relative_to(BASE)),
        "updated": data.get("updated"),
        "source": source,
        "summary": data.get("summary") or data.get("edge") or {},
    }


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
            return {"status": "FAIL", "detail": "audit_gate returned no output"}
        data = json.loads(stdout)
        return {
            "status": data.get("status", "FAIL"),
            "latest_db_date": data.get("latest_db_date"),
            "latest_db_stock_count": data.get("latest_db_stock_count"),
            "latest_db_coverage_pct": data.get("latest_db_coverage_pct"),
            "holdings_updated": data.get("holdings_updated"),
            "coverage_pct": data.get("coverage_pct"),
            "verify_data": data.get("verify_data") or {},
            "verify_dashboard": data.get("verify_dashboard") or {},
        }
    except Exception as exc:
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
        "signals_updated": bundle["files"]["signals"]["updated"],
        "alerts_updated": bundle["files"]["alerts"]["updated"],
        "prices_updated": bundle["files"]["prices"]["updated"],
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
            f"signals={bundle['files']['signals']['updated'] or '—'} | "
            f"alerts={bundle['files']['alerts']['updated'] or '—'}"
        )
    }

    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
