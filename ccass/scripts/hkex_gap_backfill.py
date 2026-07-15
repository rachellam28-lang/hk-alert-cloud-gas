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
from datetime import date, timedelta
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


def _target_codes(trade_date: str) -> tuple[set[str], list[str]]:
    """Build a historical candidate set from nearby complete dates, not today's universe."""
    with sqlite3.connect(DB_PATH) as con:
        clauses = " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])
        complete_dates = [
            str(row[0])
            for row in con.execute(
                f"""
                SELECT trade_date
                FROM ccass_daily
                WHERE validation_failed=0 AND total_shares>0 AND {clauses}
                GROUP BY trade_date
                HAVING COUNT(DISTINCT stock_code) >= 2000
                ORDER BY trade_date
                """,
                EXCLUDE_PATTERNS,
            ).fetchall()
        ]
        before = max((d for d in complete_dates if d < trade_date), default=None)
        after = min((d for d in complete_dates if d > trade_date), default=None)
        references = [d for d in (before, after) if d]
        if references:
            placeholders = ",".join("?" for _ in references)
            candidates = {
                str(row[0])
                for row in con.execute(
                    f"""
                    SELECT DISTINCT stock_code
                    FROM ccass_daily
                    WHERE trade_date IN ({placeholders})
                      AND validation_failed=0 AND total_shares>0 AND {clauses}
                    """,
                    (*references, *EXCLUDE_PATTERNS),
                ).fetchall()
            }
        else:
            candidates = {
                str(row[0])
                for row in con.execute(
                    f"SELECT stock_code FROM stock_universe WHERE is_active=1 AND {clauses}",
                    EXCLUDE_PATTERNS,
                ).fetchall()
            }
    return candidates, references


def _missing_codes(trade_date: str, candidates: set[str], require_participants: bool = False) -> list[str]:
    with sqlite3.connect(DB_PATH) as con:
        if require_participants:
            have = {
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT stock_code FROM ccass_holdings WHERE trade_date=?",
                    (trade_date,),
                ).fetchall()
            }
        else:
            have = {
                r[0]
                for r in con.execute(
                    """
                    SELECT DISTINCT stock_code
                    FROM ccass_daily
                    WHERE trade_date=? AND validation_failed=0 AND total_shares>0
                    """,
                    (trade_date,),
                ).fetchall()
            }
    return sorted(candidates - have)


def _coverage(trade_date: str, candidates: set[str], require_participants: bool = False) -> tuple[int, int, float]:
    with sqlite3.connect(DB_PATH) as con:
        if require_participants:
            sql = "SELECT DISTINCT stock_code FROM ccass_holdings WHERE trade_date=?"
        else:
            sql = (
                "SELECT DISTINCT stock_code FROM ccass_daily "
                "WHERE trade_date=? AND validation_failed=0 AND total_shares>0"
            )
        have_codes = {str(row[0]) for row in con.execute(sql, (trade_date,)).fetchall()}
    total = len(candidates)
    have = len(candidates & have_codes)
    return have, total, (have / total if total else 0.0)


def backfill_date(
    trade_date: str,
    limit: int | None = None,
    target_coverage: float = 0.99,
    require_participants: bool = False,
) -> int:
    target = date.fromisoformat(trade_date)
    candidates, references = _target_codes(trade_date)
    todo = _missing_codes(trade_date, candidates, require_participants)
    if limit:
        todo = todo[:limit]

    have, total, pct = _coverage(trade_date, candidates, require_participants)
    logger.info(
        "DATE %s mode=%s references=%s start coverage=%d/%d (%.1f%%) missing=%d",
        trade_date,
        "participant" if require_participants else "aggregate",
        ",".join(references) or "active-universe-fallback",
        have,
        total,
        pct * 100,
        len(todo),
    )
    if not todo or pct >= target_coverage:
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
                cur_have, _, cur_pct = _coverage(trade_date, candidates, require_participants)
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
                if cur_pct >= target_coverage:
                    logger.info("DATE %s target %.1f%% reached", trade_date, target_coverage * 100)
                    break
    finally:
        try:
            scraper.session.close()
        except Exception:
            pass

    cur_have, _, cur_pct = _coverage(trade_date, candidates, require_participants)
    logger.info("DATE %s done ok=%d fail=%d coverage=%d/%d (%.1f%%)", trade_date, ok, fail, cur_have, total, cur_pct * 100)
    return 0 if cur_pct >= target_coverage else 3


def _auto_target(target_coverage: float) -> tuple[str, bool] | None:
    """Pick the newest genuine aggregate gap, then participant-detail gaps."""
    from src.trading_calendar import is_trading_day

    with sqlite3.connect(DB_PATH) as con:
        bounds = con.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM ccass_daily WHERE validation_failed=0"
        ).fetchone()
    if not bounds or not bounds[0] or not bounds[1]:
        return None

    start = date.fromisoformat(str(bounds[0]))
    end = date.fromisoformat(str(bounds[1]))
    trading_dates: list[str] = []
    current = start
    while current <= end:
        if is_trading_day(current):
            trading_dates.append(current.isoformat())
        current += timedelta(days=1)

    for trade_date in reversed(trading_dates):
        candidates, _ = _target_codes(trade_date)
        if candidates and _coverage(trade_date, candidates)[2] < target_coverage:
            return trade_date, False

    for trade_date in reversed(trading_dates):
        candidates, _ = _target_codes(trade_date)
        if candidates and _coverage(trade_date, candidates, True)[2] < target_coverage:
            return trade_date, True
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--dates", help="Comma-separated trade dates YYYY-MM-DD")
    target_group.add_argument("--auto", action="store_true", help="Repair the newest audited gap")
    parser.add_argument("--limit", type=int, help="Optional cap for smoke testing")
    parser.add_argument("--request-budget", type=int, default=1200, help="Per-run cap used by --auto")
    parser.add_argument("--target-coverage", type=float, default=0.99)
    parser.add_argument("--require-participants", action="store_true")
    args = parser.parse_args()

    init_db()
    if args.auto:
        selected = _auto_target(args.target_coverage)
        if selected is None:
            logger.info("AUTO_COMPLETE no aggregate or participant gaps remain")
            return 0
        selected_date, selected_participant_mode = selected
        dates = [selected_date]
        require_participants = selected_participant_mode
        limit = args.request_budget
        logger.info(
            "AUTO_SELECT date=%s mode=%s request_budget=%d",
            selected_date,
            "participant" if require_participants else "aggregate",
            limit,
        )
    else:
        dates = [d.strip() for d in (args.dates or "").split(",") if d.strip()]
        require_participants = args.require_participants
        limit = args.limit
    for d in dates:
        date.fromisoformat(d)

    if not _acquire_lock():
        return 1
    try:
        rc = 0
        for d in dates:
            rc = backfill_date(d, limit, args.target_coverage, require_participants)
            if rc != 0:
                if args.auto:
                    logger.info("AUTO_BUDGET_EXHAUSTED date=%s; next run will resume", d)
                    return 0
                return rc
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
