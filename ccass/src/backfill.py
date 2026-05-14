"""CCASS historical backfill.

逐日 scrape 過去 N 個交易日（唔 send alerts，唔重複已有數據）。
用法:
    python -m src.backfill --days 10
"""
from __future__ import annotations

import argparse
import sys

from src.db import init_db, get_conn
from src.logger import setup_logger
from src.runner import run_daily
from src.trading_calendar import today_hk, last_n_trading_days

logger = setup_logger("backfill")


def already_scraped(trade_date) -> bool:
    """Check 係咪已經有呢日嘅數據 (>= 10 stocks scraped)."""
    date_str = trade_date.strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM ccass_daily WHERE trade_date = ?",
            (date_str,),
        ).fetchone()
        return row["n"] >= 10


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=10,
                        help="過去幾多個交易日 (default: 10)")
    parser.add_argument("--force", action="store_true",
                        help="強制重新 scrape 已有數據")
    args = parser.parse_args()

    init_db()

    today = today_hk()
    trading_days = last_n_trading_days(today, args.days)

    logger.info("=" * 60)
    logger.info("CCASS Backfill: %d trading days from %s to %s",
                len(trading_days), trading_days[0], trading_days[-1])
    logger.info("=" * 60)

    success = 0
    skipped = 0
    failed = 0

    for i, td in enumerate(trading_days, 1):
        logger.info("[%d/%d] Processing %s ...", i, len(trading_days), td)

        if not args.force and already_scraped(td):
            logger.info("  Already have data for %s, skip", td)
            skipped += 1
            continue

        rc = run_daily(
            target_date=td,
            skip_alerts=True,
            force_universe_refresh=(i == 1),
        )
        if rc in (0, 1):
            success += 1
        else:
            failed += 1
            logger.error("  Failed for %s", td)

    logger.info("=" * 60)
    logger.info("Backfill complete: %d scraped, %d skipped, %d failed",
                success, skipped, failed)
    logger.info("=" * 60)

    # 最後 export 最新日期嘅 ccass.json + send alerts
    if trading_days:
        latest = trading_days[-1]
        logger.info("Final pass: export ccass.json + alerts for %s", latest)
        run_daily(
            target_date=latest,
            skip_scrape=True,
            skip_alerts=False,
        )

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
