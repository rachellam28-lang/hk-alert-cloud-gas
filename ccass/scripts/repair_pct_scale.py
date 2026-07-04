"""Repair legacy CCASS total_pct rows stored as fractions.

Some historical rows were saved with total_pct as 0.67/1.0 while nearby rows
for the same stock and almost identical total_shares show 67/100. This keeps
latest Longbridge data valid but makes day-over-day verifiers scream. The repair
is intentionally conservative and backs up the DB before writing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import DB_PATH, backup_db


CANDIDATE_SQL = """
SELECT d.stock_code, d.trade_date, d.total_pct, ROUND(d.total_pct * 100, 2) AS fixed_pct
FROM ccass_daily d
WHERE d.validation_failed = 0
  AND d.total_pct > 0
  AND d.total_pct <= 1.0
  AND ROUND(d.total_pct * 100, 2) BETWEEN 5 AND 100
  AND EXISTS (
    SELECT 1
    FROM ccass_daily p
    WHERE p.stock_code = d.stock_code
      AND p.trade_date <> d.trade_date
      AND p.validation_failed = 0
      AND p.total_pct BETWEEN 5 AND 100
      AND ABS(p.total_pct - d.total_pct * 100) <= 3
      AND p.total_shares > 0
      AND d.total_shares > 0
      AND ABS(p.total_shares - d.total_shares) * 100.0 / p.total_shares <= 5
  )
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair legacy total_pct fraction rows")
    parser.add_argument("--dry-run", action="store_true", help="List candidates without updating")
    parser.add_argument("--limit", type=int, default=12, help="Examples to print")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(CANDIDATE_SQL + " ORDER BY d.trade_date DESC, d.stock_code").fetchall()
    if not rows:
        print("pct_scale_repair: no candidates")
        conn.close()
        return 0

    print(f"pct_scale_repair: candidates={len(rows)}")
    for stock_code, trade_date, old_pct, fixed_pct in rows[: args.limit]:
        print(f"  {stock_code} {trade_date}: {old_pct} -> {fixed_pct}")

    if args.dry_run:
        conn.close()
        return 0

    conn.close()
    backup = backup_db(DB_PATH)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"""
            WITH candidates AS ({CANDIDATE_SQL})
            UPDATE ccass_daily
            SET total_pct = ROUND(total_pct * 100, 2)
            WHERE stock_code || '|' || trade_date IN (
                SELECT stock_code || '|' || trade_date FROM candidates
            )
            """
        )
        changed = conn.total_changes
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"pct_scale_repair: updated={changed} backup={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
