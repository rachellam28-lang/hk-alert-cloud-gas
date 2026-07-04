"""Resume CCASS backfill over a date range until target coverage is reached."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "holdings.db"
DEFAULT_THRESHOLD = 0.99


def active_total() -> int:
    with sqlite3.connect(DB) as con:
        return con.execute(
            """
            SELECT COUNT(*) FROM stock_universe
            WHERE is_active=1
              AND stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04%'
              AND stock_code NOT LIKE '8%'
            """
        ).fetchone()[0]


def coverage(trade_date: str) -> int:
    with sqlite3.connect(DB) as con:
        return con.execute(
            """
            SELECT COUNT(DISTINCT stock_code)
            FROM ccass_daily
            WHERE trade_date=?
              AND validation_failed=0
              AND stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04%'
              AND stock_code NOT LIKE '8%'
            """,
            (trade_date,),
        ).fetchone()[0]


def is_trading_day(d: date) -> bool:
    sys.path.insert(0, str(PROJECT))
    from src.trading_calendar import is_trading_day as _is_trading_day

    return _is_trading_day(d)


def latest_longbridge_date() -> str | None:
    """Probe the CLI once. Longbridge broker-holding detail has latest date only."""
    try:
        proc = subprocess.run(
            ["longbridge", "broker-holding", "detail", "00700.HK", "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
    except Exception as exc:
        print(f"LONG_BRIDGE_PROBE_FAIL {exc}", flush=True)
        return None
    if proc.returncode != 0:
        print(f"LONG_BRIDGE_PROBE_FAIL rc={proc.returncode} {(proc.stderr or proc.stdout)[-200:]}", flush=True)
        return None
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"LONG_BRIDGE_PROBE_FAIL json={exc}", flush=True)
        return None
    updated = str(raw.get("updated_at") or "")
    if len(updated) >= 10:
        return updated[:10].replace(".", "-")
    return None


def provider_for_date(provider: str, trade_date: str, lb_date: str | None) -> str:
    if provider != "auto":
        return provider
    if lb_date and trade_date == lb_date:
        return "longbridge"
    return "hkex"


def run(start: date, end: date, max_batches: int, provider: str, max_stocks: int, threshold: float) -> int:
    total = active_total()
    print(f"ACTIVE_TOTAL {total}", flush=True)
    lb_date = latest_longbridge_date() if provider in ("auto", "longbridge") else None
    if lb_date:
        print(f"LONG_BRIDGE_LATEST {lb_date}", flush=True)
    current = start
    while current <= end:
        if not is_trading_day(current):
            print(f"SKIP_NON_TRADING {current.isoformat()}", flush=True)
            current += timedelta(days=1)
            continue

        trade_date = current.isoformat()
        n = coverage(trade_date)
        print(f"DATE_START {trade_date} current={n}/{total} {n / total * 100:.1f}%", flush=True)
        if max_batches <= 0:
            print(f"DATE_DRY_RUN {trade_date} coverage={n}/{total} {n / total * 100:.1f}%", flush=True)
            current += timedelta(days=1)
            continue

        batch = 0
        while n / total < threshold:
            batch += 1
            selected_provider = provider_for_date(provider, trade_date, lb_date)
            print(f"BATCH_START {trade_date} batch={batch} provider={selected_provider}", flush=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = "."
            env["HOLDINGS_PROVIDER"] = selected_provider
            env["HOLDINGS_BACKFILL_FAST"] = env.get("HOLDINGS_BACKFILL_FAST", "1")
            if selected_provider == "longbridge":
                env["FILL_MISSING_WORKERS"] = env.get("FILL_MISSING_WORKERS", "4")
            else:
                env["FILL_MISSING_WORKERS"] = env.get("FILL_MISSING_WORKERS", "1")
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/fill_missing.py",
                    trade_date,
                    "--max-stocks",
                    str(max_stocks),
                ],
                cwd=PROJECT,
                env=env,
            )
            if proc.returncode != 0:
                print(f"BATCH_FAIL {trade_date} batch={batch} rc={proc.returncode}", flush=True)
                return proc.returncode
            n = coverage(trade_date)
            print(f"BATCH_DONE {trade_date} batch={batch} coverage={n}/{total} {n / total * 100:.1f}%", flush=True)
            if batch >= max_batches:
                print(f"DATE_ABORT_TOO_MANY_BATCHES {trade_date}", flush=True)
                break

        print(f"DATE_DONE {trade_date} coverage={n}/{total} {n / total * 100:.1f}%", flush=True)
        current += timedelta(days=1)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-batches", type=int, default=6)
    parser.add_argument("--max-stocks", type=int, default=1000)
    parser.add_argument("--provider", choices=("auto", "hkex", "longbridge"), default=os.environ.get("HOLDINGS_PROVIDER", "auto"))
    parser.add_argument("--target-coverage", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()
    return run(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.max_batches,
        args.provider,
        args.max_stocks,
        args.target_coverage,
    )


if __name__ == "__main__":
    raise SystemExit(main())
