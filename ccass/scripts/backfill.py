"""Backfill 歷史 CCASS 數據。

用法:
    python -m scripts.backfill --start 2024-01-01 --end 2024-12-31
    python -m scripts.backfill --days 90    # 過去 90 個交易日

注意:
- 全港股 × 1 日 ≈ 1-2 鐘頭
- Backfill 90 日 ≈ 4-7 日 24/7 跑
- FATAL-003: 唔可以加快 delay
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, date, timedelta

import yaml

from src.db import init_db
from src.logger import setup_logger
from src.trading_calendar import is_trading_day, last_n_trading_days, today_hk
from src.universe import get_active_stocks, refresh_universe
from src.scraper import CCASSScraper, save_snapshot
from src.runner import load_config

logger = setup_logger("backfill")


def backfill_range(start: date, end: date) -> None:
    init_db()
    config = load_config()

    if not get_active_stocks():
        logger.info("Universe empty, refreshing...")
        refresh_universe()

    stocks = get_active_stocks()
    sc_cfg = config["scraping"]
    scraper = CCASSScraper(
        user_agent=sc_cfg["user_agent"],
        delay_min=sc_cfg["delay_min_seconds"],
        delay_max=sc_cfg["delay_max_seconds"],
        timeout=sc_cfg["timeout_seconds"],
        max_retries=sc_cfg["max_retries"],
    )

    # 攞每日 trading days
    cur = start
    trading_days = []
    while cur <= end:
        if is_trading_day(cur):
            trading_days.append(cur)
        cur += timedelta(days=1)

    total = len(trading_days) * len(stocks)
    logger.info(
        "Backfill plan: %d trading days × %d stocks = %d requests "
        "(估計 ~%.1f 小時)",
        len(trading_days),
        len(stocks),
        total,
        total * 2 / 3600,
    )

    done = 0
    for d in trading_days:
        logger.info("Backfilling %s...", d)
        for code in stocks:
            try:
                snap = scraper.scrape_stock(code, d)
                if snap:
                    save_snapshot(snap)
            except Exception:
                logger.exception("Backfill error on %s/%s", code, d)
            done += 1
            if done % 100 == 0:
                logger.info("Progress: %d/%d (%.1f%%)", done, total, 100 * done / total)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, help="Last N trading days from today")
    args = parser.parse_args()

    if args.days:
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
