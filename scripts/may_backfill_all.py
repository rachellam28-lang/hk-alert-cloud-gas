"""Orchestrate May 2026 backfill — fill partials first, then missing dates.
After each day: regenerate ccass.json + commit to git.
"""
import os, sys, subprocess, time
from datetime import date, datetime
from pathlib import Path

PROJECT = Path(__file__).parent.parent  # ccass-debug/
CCASS_DIR = PROJECT / "ccass"
REPO_DIR = PROJECT  # ccass-debug is the git repo

# ── Missing May dates ──
# 05-06: partial (1889/2776) → fill_missing
# 05-07, 05-08, 05-11, 05-12, 05-13, 05-29: completely missing → full backfill
FILL_MISSING_DATES = ["2026-05-06"]
FULL_BACKFILL_DATES = ["2026-05-07", "2026-05-08", "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-29"]

LOG_FILE = PROJECT / "logs" / f"may_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run_fill_missing(target_date):
    """Run fill_missing.py for a single date (only scrapes missing stocks)."""
    log(f"=== fill_missing {target_date} ===")
    result = subprocess.run(
        [sys.executable, "-u", "-m", "scripts.fill_missing", target_date],
        cwd=str(CCASS_DIR),
        capture_output=True, text=True, timeout=14400,  # 4h max
    )
    log(f"STDOUT: {result.stdout[-2000:]}")
    if result.stderr:
        log(f"STDERR: {result.stderr[-1000:]}")
    log(f"fill_missing {target_date}: rc={result.returncode}")
    return result.returncode == 0

def run_backfill_date(target_date):
    """Run backfill for a single date using run_daily()."""
    log(f"=== backfill {target_date} ===")
    result = subprocess.run(
        [sys.executable, "-u", "-c", f"""
import sys
sys.path.insert(0, '.')
from src.runner import run_daily
from src.db import init_db
from datetime import date
init_db()
rc = run_daily(target_date=date.fromisoformat('{target_date}'), skip_alerts=True, query_date_override=date.fromisoformat('{target_date}'))
sys.exit(rc)
"""],
        cwd=str(CCASS_DIR),
        capture_output=True, text=True, timeout=25200,  # 7h max per date
    )
    log(f"STDOUT: {result.stdout[-2000:]}")
    if result.stderr:
        log(f"STDERR: {result.stderr[-1000:]}")
    log(f"backfill {target_date}: rc={result.returncode}")
    return result.returncode == 0

def check_stock_count(target_date):
    """Return number of stocks scraped for this date."""
    import sqlite3
    db = sqlite3.connect(str(CCASS_DIR / "holdings.db"))
    count = db.execute(
        "SELECT COUNT(DISTINCT stock_code) FROM ccass_daily WHERE trade_date=?",
        (target_date,)
    ).fetchone()[0]
    db.close()
    return count

def regenerate_ccass_json():
    """Regenerate ccass.json from DB."""
    log("Regenerating ccass.json...")
    result = subprocess.run(
        [sys.executable, "-u", "-c", """
import sys
sys.path.insert(0, '.')
from src.runner import run_daily
run_daily(skip_scrape=True, skip_alerts=True)
"""],
        cwd=str(CCASS_DIR),
        capture_output=True, text=True, timeout=600,
    )
    log(f"ccass.json regeneration: rc={result.returncode}")

def commit_and_push(target_date):
    """Stage ccass.json, commit, and push to git."""
    log(f"Committing ccass.json (date: {target_date})...")
    # Check if ccass.json was generated
    ccass_json = REPO_DIR / "ccass.json"
    if not ccass_json.exists():
        log("ERROR: ccass.json not found!")
        return False
    
    result = subprocess.run(
        ["git", "add", "ccass.json"],
        cwd=str(REPO_DIR),
        capture_output=True, text=True, timeout=30,
    )
    # Check if there are changes to commit
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "ccass.json"],
        cwd=str(REPO_DIR),
        capture_output=True, timeout=30,
    )
    if diff_result.returncode == 0:
        log("No changes to ccass.json, skipping commit")
        return True
    
    result = subprocess.run(
        ["git", "commit", "-m", f"chore: backfill CCASS data for {target_date}"],
        cwd=str(REPO_DIR),
        capture_output=True, text=True, timeout=30,
    )
    log(f"git commit: {result.stdout.strip()} {result.stderr.strip()}")
    
    result = subprocess.run(
        ["git", "push"],
        cwd=str(REPO_DIR),
        capture_output=True, text=True, timeout=60,
    )
    log(f"git push: {result.stdout.strip()} {result.stderr.strip()}")
    return result.returncode == 0

def main():
    log("=" * 60)
    log("May 2026 Backfill Orchestrator")
    log(f"Log: {LOG_FILE}")
    log("=" * 60)
    
    os.makedirs(PROJECT / "logs", exist_ok=True)
    
    all_dates = FILL_MISSING_DATES + FULL_BACKFILL_DATES
    log(f"Plan: {len(FILL_MISSING_DATES)} fill_missing + {len(FULL_BACKFILL_DATES)} full backfill = {len(all_dates)} dates total")
    
    results = {}
    start_time = time.time()
    
    for i, target_date in enumerate(all_dates, 1):
        log(f"\n{'='*40}")
        log(f"Date {i}/{len(all_dates)}: {target_date}")
        log(f"Elapsed: {(time.time()-start_time)/3600:.1f}h")
        log(f"{'='*40}")
        
        before_count = check_stock_count(target_date)
        log(f"Stocks before: {before_count}")
        
        if before_count >= 2500:
            log(f"SKIP: Already has {before_count} stocks (≥2500), skipping")
            results[target_date] = {"status": "skip", "count": before_count}
            continue
        
        if target_date in FILL_MISSING_DATES:
            ok = run_fill_missing(target_date)
        else:
            ok = run_backfill_date(target_date)
        
        after_count = check_stock_count(target_date)
        new_stocks = after_count - before_count
        log(f"Stocks after: {after_count} (+{new_stocks})")
        
        results[target_date] = {
            "status": "ok" if ok else "fail",
            "count": after_count,
            "new": new_stocks,
        }
        
        # Regenerate ccass.json and commit after each date
        regenerate_ccass_json()
        commit_and_push(target_date)
    
    # ── Final report ──
    elapsed_h = (time.time() - start_time) / 3600
    log(f"\n{'='*60}")
    log(f"BACKFILL COMPLETE — {elapsed_h:.1f}h elapsed")
    log(f"{'='*60}")
    for d, r in results.items():
        status_icon = "✅" if r["status"] == "ok" else ("⏭️" if r["status"] == "skip" else "❌")
        log(f"  {status_icon} {d}: {r['count']} stocks ({r['status']})")
    
    total_ok = sum(1 for r in results.values() if r["status"] in ("ok", "skip"))
    total_fail = sum(1 for r in results.values() if r["status"] == "fail")
    log(f"\nSummary: {total_ok} OK, {total_fail} failed out of {len(results)}")
    log(f"Full log: {LOG_FILE}")

if __name__ == "__main__":
    main()
