"""Single-process HKEX backfill for explicit historical gap dates.

Why this exists:
- `fill_missing.py` spawns one subprocess per stock.
- `backfill.py` wraps the daily runner and can stall inside a large batch.
- For a small set of known gap dates, the fastest stable route is one
  in-process HKEX session that iterates serially and writes snapshots directly.

This script is intentionally single-threaded to respect repo rules:
- no direct parallel HKEX scraping
- no parallel DB writes
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))

from src.db import DB_PATH, init_db  # noqa: E402
from src.logger import setup_logger  # noqa: E402
from src.scraper import HOLDINGSScraper, HKEXBlockedError, save_snapshot  # noqa: E402

logger = setup_logger("hkex_gap_backfill")
LOCK_FILE = os.path.join(tempfile.gettempdir(), "holdings_backfill.lock")
EXCLUDE_PATTERNS = ("029%", "04%", "8%")


def _acquire_lock() -> bool:
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        logger.info("Lock acquired (PID %d)", os.getpid())
        return True
    except FileExistsError:
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            logger.error("Another backfill is already running (PID %d)", old_pid)
            return False
        except (OSError, ValueError):
            logger.warning("Removing stale lock")
            os.remove(LOCK_FILE)
            return _acquire_lock()


def _release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock released")
    except OSError:
        pass


def _load_scraper() -> HOLDINGSScraper:
    import yaml

    cfg_path = PROJECT / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    sc = cfg.get("scraping", {})

    delay_min = min(float(sc.get("delay_min_seconds", 4.0)), float(os.environ.get("FILL_DELAY_MIN", "1.5")))
    delay_max = min(float(sc.get("delay_max_seconds", 10.0)), float(os.environ.get("FILL_DELAY_MAX", "3.0")))
    timeout = min(int(sc.get("timeout_seconds", 30)), int(os.environ.get("FILL_TIMEOUT", "20")))
    retries = min(int(sc.get("max_retries", 3)), int(os.environ.get("FILL_RETRIES", "1")))
    ua = sc.get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )

    logger.info(
        "HKEX scraper config delay=%.1f-%.1fs timeout=%ss retries=%s",
        delay_min,
        delay_max,
        timeout,
        retries,
    )
    return HOLDINGSScraper(
        user_agent=ua,
        delay_min=delay_min,
        delay_max=delay_max,
        timeout=timeout,
        max_retries=retries,
    )


def _missing_codes(trade_date: str) -> list[str]:
    with sqlite3.connect(DB_PATH) as con:
        clauses = " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])
        full = {
            r[0]
            for r in con.execute(
                f"""
                SELECT stock_code
                FROM stock_universe
                WHERE is_active=1 AND {clauses}
                ORDER BY stock_code
                """,
                EXCLUDE_PATTERNS,
            ).fetchall()
        }
        have = {
            r[0]
            for r in con.execute(
                """
                SELECT DISTINCT stock_code
                FROM ccass_daily
                WHERE trade_date=? AND validation_failed=0
                """,
                (trade_date,),
            ).fetchall()
        }
    return sorted(full - have)


def _coverage(trade_date: str) -> tuple[int, int, float]:
    with sqlite3.connect(DB_PATH) as con:
        clauses = " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])
        total = int(
            con.execute(
                f"""
                SELECT COUNT(*)
                FROM stock_universe
                WHERE is_active=1 AND {clauses}
                """,
                EXCLUDE_PATTERNS,
            ).fetchone()[0]
            or 0
        )
        have = int(
            con.execute(
                f"""
                SELECT COUNT(DISTINCT stock_code)
                FROM ccass_daily
                WHERE trade_date=? AND validation_failed=0 AND {clauses}
                """,
                (trade_date, *EXCLUDE_PATTERNS),
            ).fetchone()[0]
            or 0
        )
    return have, total, (have / total if total else 0.0)


def backfill_date(trade_date: str, limit: int | None = None) -> int:
    target = date.fromisoformat(trade_date)
    todo = _missing_codes(trade_date)
    if limit:
        todo = todo[:limit]

    have, total, pct = _coverage(trade_date)
    logger.info("DATE %s start coverage=%d/%d (%.1f%%) missing=%d", trade_date, have, total, pct * 100, len(todo))
    if not todo:
        return 0

    scraper = _load_scraper()
    ok = 0
    fail = 0
    started = time.time()
    try:
        for i, code in enumerate(todo, 1):
            try:
                snap = scraper.scrape_stock(code, target)
                if snap and snap.holdings:
                    save_snapshot(snap)
                    ok += 1
                else:
                    fail += 1
            except HKEXBlockedError:
                logger.error("HKEX blocked during %s after %d successes / %d failures", trade_date, ok, fail)
                raise
            except Exception as exc:
                fail += 1
                logger.warning("%s %s failed: %s", trade_date, code, exc)

            if i % 25 == 0 or i == len(todo):
                cur_have, _, cur_pct = _coverage(trade_date)
                elapsed = max(time.time() - started, 0.1)
                rate = i / elapsed
                eta = (len(todo) - i) / rate if rate > 0 else 0
                logger.info(
                    "DATE %s progress %d/%d ok=%d fail=%d coverage=%d/%d (%.1f%%) rate=%.2f/s eta=%.0fs",
                    trade_date,
                    i,
                    len(todo),
                    ok,
                    fail,
                    cur_have,
                    total,
                    cur_pct * 100,
                    rate,
                    eta,
                )
    finally:
        try:
            scraper.session.close()
        except Exception:
            pass

    cur_have, _, cur_pct = _coverage(trade_date)
    logger.info("DATE %s done ok=%d fail=%d coverage=%d/%d (%.1f%%)", trade_date, ok, fail, cur_have, total, cur_pct * 100)
    return 0 if fail == 0 else 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="Comma-separated trade dates YYYY-MM-DD")
    parser.add_argument("--limit", type=int, help="Optional cap for smoke testing")
    args = parser.parse_args()

    init_db()
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    for d in dates:
        date.fromisoformat(d)

    if not _acquire_lock():
        return 1
    try:
        rc = 0
        for d in dates:
            rc = backfill_date(d, args.limit)
            if rc != 0:
                return rc
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
