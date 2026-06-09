#!/usr/bin/env python
"""Longbridge HOLDINGS backfill — sequential, single-process, ~8 calls/sec.
Usage: HOLDINGS_PROVIDER=longbridge python -u scripts/lb_backfill.py 2026-06-04 2026-06-03 2026-06-02 2026-06-01
"""
import os, sys, time, sqlite3
from datetime import date, datetime
from pathlib import Path

os.environ['HOLDINGS_PROVIDER'] = 'longbridge'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.longbridge_provider import scrape_stock
from src.scraper import save_snapshot

DB_PATH = Path(__file__).resolve().parent.parent / 'holdings.db'
CALL_DELAY = 1.0 / 8  # ~8 calls/sec

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def all_stock_codes():
    for i in range(1, 10000):
        yield str(i).zfill(5)

def backfill_date(target_date):
    date_str = target_date.strftime('%Y-%m-%d')
    log(f"=== START backfill {date_str} ===")

    scraped = empty = failed = total = 0
    t_start = time.time()

    for code in all_stock_codes():
        total += 1
        t_call = time.time()

        try:
            snap = scrape_stock(code, target_date)
        except Exception as e:
            # First few failures: log them; after that, count silently
            if failed < 5:
                log(f"ERROR {code}: {e}")
            failed += 1
            time.sleep(CALL_DELAY)
            continue

        if snap is None or not snap.holdings:
            empty += 1
        else:
            try:
                save_snapshot(snap)
                scraped += 1
            except Exception as e:
                if failed < 5:
                    log(f"DB_ERROR {code}: {e}")
                failed += 1

        # Rate limit
        elapsed = time.time() - t_call
        if elapsed < CALL_DELAY:
            time.sleep(CALL_DELAY - elapsed)

        # Progress every 500
        if total % 500 == 0:
            t_elapsed = time.time() - t_start
            log(f"Progress: scraped={scraped}/{total} ({100*scraped/total:.1f}%) empty={empty} failed={failed} rate={total/t_elapsed:.1f}/s")

    elapsed_total = time.time() - t_start
    log(f"=== DONE {date_str}: scraped={scraped} empty={empty} failed={failed} in {elapsed_total:.0f}s ({elapsed_total/60:.0f}min) ===")

    # Verify
    db = sqlite3.connect(str(DB_PATH))
    row = db.execute("SELECT COUNT(*) FROM holdings_daily WHERE trade_date=?", (date_str,)).fetchone()
    log(f"DB count for {date_str}: {row[0]} stocks")
    db.close()

    fail_pct = 100 * failed / total if total > 0 else 0
    return {'date': date_str, 'scraped': scraped, 'empty': empty, 'failed': failed, 'total': total, 'fail_pct': fail_pct}

def main():
    if len(sys.argv) < 2:
        print("Usage: python -u scripts/lb_backfill.py YYYY-MM-DD [YYYY-MM-DD ...]")
        sys.exit(1)

    dates = [date.fromisoformat(d) for d in sys.argv[1:]]
    log(f"Backfilling {len(dates)} dates: {[str(d) for d in dates]}")

    all_stats = []
    for i, dt in enumerate(dates):
        log(f"=== Date {i+1}/{len(dates)}: {dt} ===")
        stats = backfill_date(dt)
        all_stats.append(stats)

    # Summary
    print("\n" + "="*60, flush=True)
    print("BACKFILL SUMMARY", flush=True)
    print("="*60, flush=True)
    for s in all_stats:
        flag = " ⚠️ >10% FAIL" if s['fail_pct'] > 10 else ""
        print(f"  {s['date']}: scraped={s['scraped']} empty={s['empty']} failed={s['failed']} fail_rate={s['fail_pct']:.1f}%{flag}", flush=True)
    print("="*60, flush=True)

if __name__ == '__main__':
    main()
