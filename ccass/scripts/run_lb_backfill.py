#!/usr/bin/env python
"""Simple Longbridge backfill runner — loads token from .env, then runs backfill."""
import os, sys, time, sqlite3, subprocess
from datetime import date, datetime
from pathlib import Path

# Load token from .env (the approach that works)
ENV_PATH = Path(__file__).resolve().parent.parent.parent / '.env'
if not ENV_PATH.exists():
    ENV_PATH = Path.home() / 'Desktop' / 'automatic' / 'ccass-debug' / '.env'

token = None
with open(ENV_PATH) as f:
    for line in f:
        line = line.strip()
        if line.startswith('LONGBRIDGE_ACCESS_TOKEN='):
            token = line.split('=', 1)[1]
            break
if not token:
    print("FATAL: Cannot find LONGBRIDGE_ACCESS_TOKEN", flush=True)
    sys.exit(1)

os.environ['LONGBRIDGE_ACCESS_TOKEN'] = token
os.environ['CCASS_PROVIDER'] = 'longbridge'

# Now import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.longbridge_provider import scrape_stock
from src.scraper import save_snapshot

DB_PATH = Path(__file__).resolve().parent / 'ccass.db'
CALL_DELAY = 1.0 / 8

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def all_stock_codes():
    for i in range(1, 10000):
        yield str(i).zfill(5)

def backfill_date(target_date):
    date_str = target_date.strftime('%Y-%m-%d')
    log(f"START backfill {date_str}")

    scraped = empty = failed = total = 0
    t_start = time.time()

    for code in all_stock_codes():
        total += 1
        t_call = time.time()

        try:
            snap = scrape_stock(code, target_date)
        except Exception as e:
            if failed < 5:
                log(f"ERR {code}: {e}")
            failed += 1
            elapsed = time.time() - t_call
            if elapsed < CALL_DELAY:
                time.sleep(CALL_DELAY - elapsed)
            continue

        if snap is None or not snap.holdings:
            empty += 1
        else:
            try:
                save_snapshot(snap)
                scraped += 1
            except Exception as e:
                if failed < 5:
                    log(f"DB_ERR {code}: {e}")
                failed += 1

        elapsed = time.time() - t_call
        if elapsed < CALL_DELAY:
            time.sleep(CALL_DELAY - elapsed)

        if total % 500 == 0:
            t_elapsed = time.time() - t_start
            log(f"Progress: s={scraped}/{total}({100*scraped/total:.1f}%) e={empty} f={failed} rate={total/t_elapsed:.1f}/s")

    elapsed_total = time.time() - t_start
    log(f"DONE {date_str}: scraped={scraped} empty={empty} failed={failed} in {elapsed_total:.0f}s")

    db = sqlite3.connect(str(DB_PATH))
    row = db.execute("SELECT COUNT(*) FROM ccass_daily WHERE trade_date=?", (date_str,)).fetchone()
    log(f"DB: {row[0]} stocks for {date_str}")
    db.close()

    fail_pct = 100 * failed / total if total > 0 else 0
    return {'date': date_str, 'scraped': scraped, 'empty': empty, 'failed': failed, 'total': total, 'fail_pct': fail_pct}

if __name__ == '__main__':
    dates = [date.fromisoformat(d) for d in sys.argv[1:]]
    log(f"Backfilling {len(dates)} dates: {sys.argv[1:]}")

    all_stats = []
    for i, dt in enumerate(dates):
        log(f"=== Date {i+1}/{len(dates)}: {dt} ===")
        stats = backfill_date(dt)
        all_stats.append(stats)

    print("\n" + "="*60, flush=True)
    print("SUMMARY", flush=True)
    print("="*60, flush=True)
    for s in all_stats:
        flag = " !HIGH_FAIL" if s['fail_pct'] > 10 else ""
        print(f"  {s['date']}: s={s['scraped']} e={s['empty']} f={s['failed']} fail={s['fail_pct']:.1f}%{flag}", flush=True)
    print("="*60, flush=True)
