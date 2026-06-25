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
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "holdings.db"
RESUME = PROJECT / "scripts" / "resume_backfill_range.py"
THRESHOLD = 0.99
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


def _recent_dates(con: sqlite3.Connection, limit: int) -> list[str]:
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
    parser.add_argument("--lookback", type=int, default=20, help="How many recent dates to inspect")
    parser.add_argument("--max-batches", type=int, default=6)
    args = parser.parse_args()

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        dates = _recent_dates(con, args.lookback)
        if not dates:
            print("NO_DATES")
            return 0

        incomplete: list[str] = []
        for d in dates:
            n, total, cov = _coverage(con, d)
            print(f"CHECK {d} {n}/{total} {cov*100:.1f}%")
            if cov < THRESHOLD:
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
        ],
        cwd=PROJECT,
        env={
            **os.environ,
            "HOLDINGS_PROVIDER": "hkex",
            "HOLDINGS_BACKFILL_FAST": "1",
            "FILL_MISSING_WORKERS": "1",
            "PYTHONPATH": ".",
        },
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
