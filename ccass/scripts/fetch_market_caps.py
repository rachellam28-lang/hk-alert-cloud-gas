"""Fetch HK market caps — slow & steady, resumable."""
import json, time, sys, sqlite3
from pathlib import Path
import yfinance as yf

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_PATH = PROJECT_ROOT / "cache" / "market_caps.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load cache
cache = {}
if CACHE_PATH.exists():
    try:
        for item in json.loads(CACHE_PATH.read_text(encoding='utf-8')):
            v = item['market_cap']
            cache[item['stock_code']] = v
    except: pass

# Get codes
db = sqlite3.connect(str(PROJECT_ROOT / "holdings.db"))
codes = [r[0] for r in db.execute("SELECT stock_code FROM stock_universe ORDER BY stock_code").fetchall()]
db.close()

# Only fetch missing/null
missing = [c for c in codes if c not in cache or cache[c] is None]
done = sum(1 for v in cache.values() if v is not None)
print(f"Total: {len(codes)}, have mc: {done}, to fetch: {len(missing)}", flush=True)

if not missing:
    print("All done!", flush=True)
    sys.exit(0)

errors = 0
for idx, c in enumerate(missing):
    n = int(c)
    sym = f"{n:04d}.HK" if n < 10000 else f"{c}.HK"
    try:
        t = yf.Ticker(sym)
        info = t.get_info()
        mc = info.get('marketCap')
        cache[c] = round(mc / 1e8, 2) if (mc is not None and mc > 0) else None
    except Exception as e:
        cache[c] = None
        errors += 1
    
    # Save every 50 stocks
    if (idx + 1) % 50 == 0 or idx == len(missing) - 1:
        output = [{"stock_code": k, "market_cap": v} for k, v in cache.items()]
        CACHE_PATH.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
        mc_count = sum(1 for v in cache.values() if v is not None)
        pct = (idx + 1) / len(missing) * 100
        print(f"  {idx+1}/{len(missing)} ({pct:.0f}%) — {mc_count} with mc, {errors} err", flush=True)
    
    time.sleep(0.5)  # Slow to avoid rate limits

mc_final = sum(1 for v in cache.values() if v is not None)
print(f"\nDone! {mc_final} stocks with market cap ({errors} errors)", flush=True)
