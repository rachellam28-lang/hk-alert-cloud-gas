from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "holdings.db"


def find_targets(
    conn: sqlite3.Connection,
    min_multiplier: float,
    min_diff: float,
    max_share_diff_pct: float,
) -> list[tuple[str, str, int, float, int, float, float]]:
    rows = conn.execute(
        """
        WITH agg AS (
          SELECT h.stock_code,
                 h.trade_date,
                 SUM(h.shares) AS sum_shares,
                 SUM(COALESCE(h.pct_of_issued, 0)) AS sum_pct,
                 COUNT(*) AS holdings_rows
          FROM ccass_holdings h
          GROUP BY h.stock_code, h.trade_date
        )
        SELECT a.stock_code,
               a.trade_date,
               d.total_shares,
               d.total_pct,
               a.holdings_rows,
               a.sum_pct,
               ABS(a.sum_shares - d.total_shares) * 100.0 / NULLIF(d.total_shares, 0) AS share_diff_pct
        FROM agg a
        JOIN ccass_daily d
          ON d.stock_code = a.stock_code
         AND d.trade_date = a.trade_date
        WHERE d.total_shares > 0
          AND d.total_pct IS NOT NULL
          AND d.total_pct > 0
          AND ABS(a.sum_shares - d.total_shares) * 100.0 / NULLIF(d.total_shares, 0) <= ?
          AND a.sum_pct > d.total_pct + ?
          AND a.sum_pct > d.total_pct * ?
        ORDER BY a.trade_date, a.stock_code
        """,
        (max_share_diff_pct, min_diff, min_multiplier),
    ).fetchall()
    return rows


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = DB.with_name(f"holdings_before_pct_repair_{stamp}.db")
    shutil.copy2(DB, target)
    return target


def repair(
    conn: sqlite3.Connection,
    targets: list[tuple[str, str, int, float, int, float, float]],
) -> tuple[int, int]:
    pair_count = 0
    row_count = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stock_code, trade_date, total_shares, total_pct, _, _, _ in targets:
            cur = conn.execute(
                """
                UPDATE ccass_holdings
                   SET pct_of_issued = ROUND((shares * 1.0 / ?) * ?, 4)
                 WHERE stock_code = ?
                   AND trade_date = ?
                """,
                (total_shares, total_pct, stock_code, trade_date),
            )
            row_count += cur.rowcount
            pair_count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return pair_count, row_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-multiplier", type=float, default=1.0)
    parser.add_argument("--min-diff", type=float, default=5.0)
    parser.add_argument("--max-share-diff-pct", type=float, default=2.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    try:
        targets = find_targets(conn, args.min_multiplier, args.min_diff, args.max_share_diff_pct)
        print(f"targets={len(targets)}")
        if targets:
            print(
                f"first={targets[0][0]} {targets[0][1]} total_pct={targets[0][3]} "
                f"sum_pct={targets[0][5]} share_diff_pct={targets[0][6]:.4f}"
            )
            print(
                f"last={targets[-1][0]} {targets[-1][1]} total_pct={targets[-1][3]} "
                f"sum_pct={targets[-1][5]} share_diff_pct={targets[-1][6]:.4f}"
            )
        if not args.apply:
            return 0

        backup = backup_db()
        print(f"backup={backup}")
        pair_count, row_count = repair(conn, targets)
        print(f"repaired_pairs={pair_count}")
        print(f"repaired_rows={row_count}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
