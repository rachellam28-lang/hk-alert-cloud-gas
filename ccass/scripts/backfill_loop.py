"""Sequential backfill wrapper — one date at a time, skip if >=2500 stocks, commit after each."""
from __future__ import annotations

import subprocess
import sys
import os
from datetime import date
from pathlib import Path

from src.db import get_conn, DB_PATH
from src.trading_calendar import is_trading_day
from src.logger import setup_logger

logger = setup_logger("backfill_loop")

# Dates to backfill, newest first (user preference)
DATES = [
    "2026-05-28",  # today
    "2026-05-27",
    "2026-05-26",  # partial (677)
    "2026-05-20",
    "2026-05-15",  # partial (2456)
    "2026-05-13",
    "2026-05-12",
    "2026-05-11",
    "2026-05-08",
    "2026-05-07",
    "2026-05-06",
]

REPO_ROOT = Path(__file__).parent.parent.parent  # ccass-debug/
MIN_STOCKS = 2500


def check_existing(d: str) -> int:
    """Return stock count for date, 0 if none."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM ccass_daily WHERE trade_date = ?", (d,)
        ).fetchone()
        return row[0] if row else 0


def run_one_date(d: str) -> bool:
    """Run backfill for one date via scripts.backfill. Returns True on success."""
    logger.info("=== Backfilling %s ===", d)
    # Clear .pyc first
    pyc_dirs = [
        REPO_ROOT / "ccass" / "src" / "__pycache__",
        REPO_ROOT / "ccass" / "scripts" / "__pycache__",
    ]
    for p in pyc_dirs:
        if p.exists():
            for f in p.glob("*.pyc"):
                f.unlink()

    # Remove stale lock if it exists (backfill.py handles its own locking)
    import tempfile
    lock_file = os.path.join(tempfile.gettempdir(), "ccass_backfill.lock")
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                import ctypes
                k = ctypes.windll.kernel32
                h = k.OpenProcess(0x0400, False, old_pid)
                if not h:
                    logger.warning("Removing stale lock from dead PID %d", old_pid)
                    os.remove(lock_file)
                else:
                    k.CloseHandle(h)
                    logger.warning("Lock held by PID %d (alive), removing anyway for backfill_loop", old_pid)
                    os.remove(lock_file)
        except (ValueError, OSError):
            os.remove(lock_file)

    cmd = [sys.executable, "-u", "-m", "scripts.backfill", "--start", d, "--end", d]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT / "ccass"),
        capture_output=False,
        timeout=28800,  # 8h max per date
    )
    if result.returncode == 0:
        logger.info("Backfill %s OK (rc=0)", d)
        return True
    else:
        logger.error("Backfill %s FAILED (rc=%d)", d, result.returncode)
        return False


def commit_and_push(d: str) -> bool:
    """Commit ccass.json and ccass.db.gz, push to git."""
    ccass_json = REPO_ROOT / "ccass.json"
    db_gz = REPO_ROOT / "ccass" / "ccass.db.gz"

    if not ccass_json.exists():
        logger.error("ccass.json not found — nothing to commit")
        return False

    # gzip the DB
    import gzip, shutil
    db_path = REPO_ROOT / "ccass" / "ccass.db"
    if db_path.exists():
        with open(db_path, "rb") as f_in:
            with gzip.open(str(db_gz), "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        logger.info("DB compressed: %s -> %s", db_path.stat().st_size, db_gz.stat().st_size)

    # Stage and commit
    subprocess.run(["git", "add", str(ccass_json), str(db_gz)], cwd=str(REPO_ROOT), check=True)
    msg = f"chore: backfill {d} — ccass data update"
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    if result.returncode != 0 and "nothing to commit" not in result.stderr + result.stdout:
        logger.error("Git commit failed: %s", result.stderr)
        return False

    # Push
    result = subprocess.run(
        ["git", "push"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info("Pushed %s to git", d)
        return True
    else:
        logger.error("Git push failed: %s", result.stderr)
        return False


def main():
    logger.info("=== CCASS Backfill Loop ===")
    logger.info("Dates to process: %d", len(DATES))

    results = []
    for i, d in enumerate(DATES, 1):
        # Check if already done
        existing = check_existing(d)
        if existing >= MIN_STOCKS:
            logger.info("[%d/%d] %s: SKIP (already %d stocks)", i, len(DATES), d, existing)
            results.append((d, "SKIP", existing))
            continue

        # Check trading day
        dt = date.fromisoformat(d)
        if not is_trading_day(dt):
            logger.info("[%d/%d] %s: SKIP (non-trading day)", i, len(DATES), d)
            results.append((d, "NON_TRADING", 0))
            continue

        logger.info("[%d/%d] %s: STARTING (existing: %d)", i, len(DATES), d, existing)
        ok = run_one_date(d)

        if ok:
            new_count = check_existing(d)
            logger.info("[%d/%d] %s: DONE (%d stocks)", i, len(DATES), d, new_count)
            results.append((d, "OK", new_count))

            # Commit and push immediately
            pushed = commit_and_push(d)
            if not pushed:
                logger.warning("Commit/push failed for %s — continuing anyway", d)
        else:
            logger.error("[%d/%d] %s: FAILED", i, len(DATES), d)
            results.append((d, "FAILED", check_existing(d)))
            # Don't stop — continue with next date

    # Final summary
    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE — SUMMARY")
    print("=" * 60)
    for d, status, cnt in results:
        print(f"  {d}: {status} ({cnt} stocks)")
    print("=" * 60)


if __name__ == "__main__":
    main()
