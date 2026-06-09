"""Backfill 歷史 HOLDINGS 數據 — simplified sequential version.

用法:
    python -m scripts.backfill --start 2024-01-01 --end 2024-12-31
    python -m scripts.backfill --days 90    # 過去 90 個交易日

注意:
- 每一日 call src.runner.run_daily()（skip_alerts=True）
- FATAL-003: 唔可以加快 delay
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, date

from src.db import init_db
from src.logger import setup_logger
from src.trading_calendar import is_trading_day, today_hk
from src.universe import refresh_universe, get_active_stocks
from src.runner import run_daily

logger = setup_logger("backfill")

# ── PID lock: prevent multiple backfills running at once ──────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "holdings_backfill.lock")


def _acquire_lock() -> bool:
    """Try to acquire the backfill lock. Returns True if lock acquired."""
    # Atomic create with O_CREAT | O_EXCL — no TOCTOU race
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        logger.info("Lock acquired (PID %d)", os.getpid())
        return True
    except FileExistsError:
        # Lock exists — check if old process is still alive
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Portable process check: os.kill(pid, 0) works on Windows + Unix
            os.kill(old_pid, 0)
            logger.error(
                "FATAL-003: Another backfill is already running (PID %d). "
                "Lock file: %s. Exiting.",
                old_pid, LOCK_FILE,
            )
            return False
        except (OSError, ValueError):
            # Process not found or corrupt lock — remove and retry
            logger.warning("Stale lock from dead/corrupt PID, removing.")
            os.remove(LOCK_FILE)
            return _acquire_lock()  # retry with fresh O_CREAT|O_EXCL


def _release_lock() -> None:
    """Release the backfill lock."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock released")
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────


def backfill_range(start: date, end: date) -> None:
    if not _acquire_lock():
        sys.exit(1)
    try:
        init_db()

        # Skip universe refresh if DB already has stocks (avoids HKEX requests.get() hang)
        import sqlite3
        from src.db import DB_PATH
        with sqlite3.connect(str(DB_PATH)) as conn:
            existing = conn.execute(
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
            rc = run_daily(target_date=d, skip_alerts=True, query_date_override=d)
            if rc == 0:
                success += 1
            else:
                logger.error("Backfill failed for %s (rc=%d)", d, rc)

        logger.info("Backfill complete: %d/%d days succeeded", success, total)
    finally:
        _release_lock()


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
