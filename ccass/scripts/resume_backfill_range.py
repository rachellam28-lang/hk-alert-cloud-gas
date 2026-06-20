"""Resume Longbridge backfill over a date range until target coverage is reached."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "holdings.db"
THRESHOLD = 0.99


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


def run(start: date, end: date, max_batches: int) -> int:
    total = active_total()
    print(f"ACTIVE_TOTAL {total}", flush=True)
    current = start
    while current <= end:
        if current.weekday() >= 5:
            print(f"SKIP_WEEKEND {current.isoformat()}", flush=True)
            current += timedelta(days=1)
            continue

        trade_date = current.isoformat()
        n = coverage(trade_date)
        print(f"DATE_START {trade_date} current={n}/{total} {n / total * 100:.1f}%", flush=True)

        batch = 0
        while n / total < THRESHOLD:
            batch += 1
            print(f"BATCH_START {trade_date} batch={batch}", flush=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = "."
            env["HOLDINGS_PROVIDER"] = "longbridge"
            env["FILL_MISSING_WORKERS"] = env.get("FILL_MISSING_WORKERS", "4")
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/fill_missing.py",
                    trade_date,
                    "--max-stocks",
                    "1000",
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
    args = parser.parse_args()
    return run(date.fromisoformat(args.start), date.fromisoformat(args.end), args.max_batches)


if __name__ == "__main__":
    raise SystemExit(main())
