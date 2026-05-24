"""Backfill 歷史 CCASS 數據 — simplified sequential version.

用法:
    python -m scripts.backfill --start 2024-01-01 --end 2024-12-31
    python -m scripts.backfill --days 90    # 過去 90 個交易日

注意:
- 每一日 call src.runner.run_daily()（skip_alerts=True）
- FATAL-003: 唔可以加快 delay
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, date

from src.db import init_db
from src.logger import setup_logger
from src.trading_calendar import is_trading_day, today_hk
from src.universe import refresh_universe, get_active_stocks
from src.runner import run_daily

logger = setup_logger("backfill")


def backfill_range(start: date, end: date) -> None:
    init_db()

    # Skip universe refresh if DB already has stocks (avoids HKEX requests.get() hang)
    import sqlite3
    from src.db import DB_PATH
    existing = sqlite3.connect(str(DB_PATH)).execute(
        "SELECT COUNT(*) FROM stock_universe"
    ).fetchone()[0]
    if existing < 500:
        if not get_active_stocks():
            logger.info("Universe empty, refreshing...")
            refresh_universe()
    else:
        logger.info("Skip universe refresh: %d stocks already in DB", existing)

    # 攞每日 trading days
    cur = start
    trading_days = []
    while cur <= end:
        if is_trading_day(cur):
            trading_days.append(cur)
        from datetime import timedelta
        cur += timedelta(days=1)

    total = len(trading_days)
    logger.info(
        "Backfill plan: %d trading days",
        total,
    )

    success = 0
    for i, d in enumerate(trading_days, 1):
        logger.info("Backfilling %s (%d/%d)...", d, i, total)
        rc = run_daily(target_date=d, skip_alerts=True)
        if rc == 0:
            success += 1
        else:
            logger.error("Backfill failed for %s (rc=%d)", d, rc)

    logger.info("Backfill complete: %d/%d days succeeded", success, total)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, help="Last N trading days from today")
    args = parser.parse_args()

    if args.days:
        from src.trading_calendar import last_n_trading_days
        days = last_n_trading_days(today_hk(), args.days)
        start, end = days[0], days[-1]
    elif args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = (
            datetime.strptime(args.end, "%Y-%m-%d").date()
            if args.end
            else today_hk()
        )
    else:
        parser.error("Need --start or --days")

    backfill_range(start, end)


if __name__ == "__main__":
    main()
