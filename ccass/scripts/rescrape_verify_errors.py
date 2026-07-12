from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from fill_missing import _load_scraping_config, _save_snapshot, _scrape_one
from src.db import backup_db


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "holdings.db"


def pct_error_targets(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """
        WITH agg AS (
          SELECT stock_code, trade_date,
                 SUM(shares) AS sum_shares,
                 SUM(COALESCE(pct_of_issued, 0)) AS sum_pct
          FROM ccass_holdings
          GROUP BY stock_code, trade_date
        )
        SELECT d.stock_code, d.trade_date,
               'pct_underflow'
        FROM ccass_daily d
        JOIN agg a
          ON a.stock_code = d.stock_code
         AND a.trade_date = d.trade_date
        WHERE d.total_pct IS NOT NULL
          AND d.total_pct > 0
          AND a.sum_pct > 0
          AND (d.total_pct - a.sum_pct) > 50
        ORDER BY d.trade_date, d.stock_code
        """
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def jump_error_targets(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """
        WITH changes AS (
            SELECT stock_code, trade_date, total_pct, total_shares,
                   LAG(total_pct) OVER w AS prev_pct,
                   LAG(total_shares) OVER w AS prev_shares,
                   LAG(trade_date) OVER w AS prev_date
            FROM ccass_daily
            WINDOW w AS (PARTITION BY stock_code ORDER BY trade_date)
        )
        SELECT stock_code, prev_date, trade_date,
               prev_pct, total_pct, prev_shares, total_shares
        FROM changes
        WHERE prev_pct IS NOT NULL
          AND total_pct > 0
          AND prev_pct > 0
          AND ABS(total_pct - prev_pct) > 50
          AND prev_shares > 0
          AND ABS(total_shares - prev_shares) * 100.0 / prev_shares < 5
        ORDER BY ABS(total_pct - prev_pct) DESC, stock_code, trade_date
        """
    ).fetchall()

    out: list[tuple[str, str, str]] = []
    for stock_code, prev_date, trade_date, *_ in rows:
        out.append((stock_code, prev_date, "jump_prev"))
        out.append((stock_code, trade_date, "jump_curr"))
    return out


def collect_targets(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for stock_code, trade_date, reason in pct_error_targets(conn) + jump_error_targets(conn):
        key = (stock_code, trade_date)
        if key in seen:
            continue
        seen.add(key)
        out.append((stock_code, trade_date, reason))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    os.environ.setdefault("HOLDINGS_PROVIDER", "hkex")
    sc_cfg = _load_scraping_config()

    conn = sqlite3.connect(DB)
    try:
        targets = collect_targets(conn)
        if args.limit > 0:
            targets = targets[:args.limit]
        print(f"targets={len(targets)}")
        for stock_code, trade_date, reason in targets[:30]:
            print(f"{trade_date} {stock_code} {reason}")
        if not args.apply or not targets:
            return 0

        backup = backup_db(DB)
        print(f"backup={backup}")

        ok = 0
        failed = 0
        for idx, (stock_code, trade_date, reason) in enumerate(targets, start=1):
            code, data, err = _scrape_one(stock_code, trade_date, sc_cfg)
            if err or not data:
                failed += 1
                print(f"FAIL {trade_date} {code} {reason} {err}")
                continue
            _save_snapshot(conn, data)
            ok += 1
            print(f"OK {idx}/{len(targets)} {trade_date} {code} {reason}")
        print(f"done ok={ok} failed={failed}")
        return 0 if failed == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
