"""CCASS historical backfill.

逐日 scrape 過去 N 個交易日（唔 send alerts，唔重複已有數據）。
用法:
    python -m src.backfill --days 5
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

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


def _commit_ccass_json(trade_date: str, day_idx: int, total: int) -> None:
    """每 scraped 一日就 commit ccass.json，dashboard 逐步更新。"""
    repo_root = Path(__file__).parent.parent.parent
    try:
        subprocess.run(["git", "add", "ccass.json"], cwd=repo_root,
                       capture_output=True, timeout=30, check=True)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"],
                           cwd=repo_root, capture_output=True, timeout=30)
        if r.returncode == 0:
            logger.info("ccass.json unchanged, skip commit")
            return
        msg = f"chore: update ccass.json day {day_idx}/{total} ({trade_date}) [skip ci]"
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_root,
                       capture_output=True, timeout=30, check=True)
        for attempt in range(3):
            r = subprocess.run(["git", "push", "origin", "HEAD:main"],
                               cwd=repo_root, capture_output=True, timeout=60)
            if r.returncode == 0:
                logger.info("Committed ccass.json for %s", trade_date)
                return
            if attempt < 2:
                subprocess.run(["git", "fetch", "origin", "main"],
                               cwd=repo_root, capture_output=True, timeout=30)
                subprocess.run(["git", "rebase", "origin/main"],
                               cwd=repo_root, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning("ccass.json commit failed: %s", e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5,
                        help="過去幾多個交易日 (default: 5)")
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
            _commit_ccass_json(td.strftime("%Y-%m-%d"), i, len(trading_days))
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
        _commit_ccass_json(latest.strftime("%Y-%m-%d"), len(trading_days), len(trading_days))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
