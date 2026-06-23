import time, sqlite3

DB = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass\ccass.db"
TARGET = "2026-06-17"
MIN_COUNT = 2500

t0 = time.time()
cnt = 0
for i in range(50):
    time.sleep(180)
    try:
        with sqlite3.connect(DB, timeout=5) as db:
            cnt = db.execute('SELECT COUNT(*) FROM ccass_daily WHERE trade_date=?', (TARGET,)).fetchone()[0]
            last = db.execute('SELECT stock_code FROM ccass_daily WHERE trade_date=? ORDER BY scraped_at DESC LIMIT 1', (TARGET,)).fetchone()
        last_code = last[0] if last else 'N/A'
        elapsed = (time.time() - t0) / 60
        print(f"[{elapsed:.0f}min] {cnt} stocks, last={last_code}", flush=True)
        if cnt >= MIN_COUNT:
            print(f"DONE: {cnt} stocks >= {MIN_COUNT}", flush=True)
            break
    except Exception as e:
        print(f"ERR: {e}", flush=True)
        time.sleep(10)
print(f"FINAL: {cnt} stocks for {TARGET}", flush=True)
