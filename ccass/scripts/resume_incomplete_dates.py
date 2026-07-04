"""Resume the latest incomplete HOLDINGS dates automatically.

This helper looks at recent trading dates in ccass_daily, finds any dates
with coverage below threshold, and delegates to resume_backfill_range.py.
It is intended for the separate resume workflow, not the daily bounded run.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import os
from datetime import date, timedelta
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "holdings.db"
RESUME = PROJECT / "scripts" / "resume_backfill_range.py"
DEFAULT_THRESHOLD = 0.99
EXCLUDE_PATTERNS = ("029%", "04%", "8%")


def _active_total(con: sqlite3.Connection) -> int:
    row = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM stock_universe
        WHERE is_active=1
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """
    ).fetchone()
    return int(row[0] or 0)


def _db_recent_dates(con: sqlite3.Connection, limit: int) -> list[str]:
    rows = con.execute(
        """
        SELECT DISTINCT trade_date
        FROM ccass_daily
        WHERE validation_failed=0
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(r[0]) for r in rows][::-1]


def _candidate_dates(con: sqlite3.Connection, lookback: int, start: str | None, end: str | None) -> list[str]:
    sys.path.insert(0, str(PROJECT))
    from src.trading_calendar import is_trading_day, last_n_trading_days, today_hk

    if start or end:
        if start:
            start_date = date.fromisoformat(start)
        else:
            db_dates = _db_recent_dates(con, lookback)
            start_date = date.fromisoformat(db_dates[0]) if db_dates else today_hk()
        end_date = date.fromisoformat(end) if end else today_hk()
        out: list[str] = []
        cur = start_date
        while cur <= end_date:
            if is_trading_day(cur):
                out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out

    return [d.isoformat() for d in last_n_trading_days(today_hk(), lookback)]


def _coverage(con: sqlite3.Connection, trade_date: str) -> tuple[int, int, float]:
    clauses = " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])
    row = con.execute(
        f"""
        SELECT COUNT(DISTINCT stock_code) AS n
        FROM ccass_daily
        WHERE trade_date=?
          AND validation_failed=0
          AND {clauses}
        """,
        (trade_date, *EXCLUDE_PATTERNS),
    ).fetchone()
    n = int(row[0] or 0)
    total = _active_total(con)
    cov = n / total if total else 0.0
    return n, total, cov


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, default=45, help="How many recent trading dates to inspect, including absent DB dates")
    parser.add_argument("--start", help="Optional start date YYYY-MM-DD")
    parser.add_argument("--end", help="Optional end date YYYY-MM-DD")
    parser.add_argument("--max-batches", type=int, default=6)
    parser.add_argument("--max-stocks", type=int, default=1000)
    parser.add_argument("--provider", choices=("auto", "hkex", "longbridge"), default=os.environ.get("HOLDINGS_PROVIDER", "auto"))
    parser.add_argument("--target-coverage", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        dates = _candidate_dates(con, args.lookback, args.start, args.end)
        if not dates:
            print("NO_DATES")
            return 0

        incomplete: list[str] = []
        for d in dates:
            n, total, cov = _coverage(con, d)
            print(f"CHECK {d} {n}/{total} {cov*100:.1f}%")
            if cov < args.target_coverage:
                incomplete.append(d)

    if not incomplete:
        print("ALL_COMPLETE")
        return 0

    start = incomplete[0]
    end = incomplete[-1]
    print(f"RESUME {start} -> {end} ({len(incomplete)} dates)")
    proc = subprocess.run(
        [
            sys.executable,
            str(RESUME),
            "--start", start,
            "--end", end,
            "--max-batches", str(args.max_batches),
            "--max-stocks", str(args.max_stocks),
            "--provider", args.provider,
            "--target-coverage", str(args.target_coverage),
        ],
        cwd=PROJECT,
        env={
            **os.environ,
            "HOLDINGS_BACKFILL_FAST": "1",
            "PYTHONPATH": ".",
        },
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
