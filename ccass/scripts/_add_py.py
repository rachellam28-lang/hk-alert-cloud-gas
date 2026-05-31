"""Add 2025 year-open prices to existing stock_prices.json cache."""
import json, yfinance as yf, time, sys
from pathlib import Path

CACHE_PATH = str(Path(__file__).parent.parent / "data" / "stock_prices.json")

cache = json.load(open(CACHE_PATH, encoding='utf-8'))

def to_sym(c): return f"{int(c):04d}.HK"
codes = [c for c in sorted(cache.keys()) if not cache[c].get('py')]
print(f"Need py: {len(codes)}")

BATCH = 50
added = 0
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    syms = [to_sym(c) for c in batch]
    try:
        py_hist = yf.download(syms, start='2025-01-01', end='2025-01-10', progress=False, auto_adjust=False)
        for c, sym in zip(batch, syms):
            if sym in py_hist.columns.get_level_values(1):
                col = py_hist.xs(sym, axis=1, level=1)['Open']
                v = float(col.iloc[0])
                if v == v:
                    cache[c]['py'] = round(v, 3)
                    if cache[c].get('lp') and cache[c]['py'] > 0:
                        cache[c]['py_pct'] = round((cache[c]['lp']-cache[c]['py'])/cache[c]['py']*100, 2)
                    added += 1
    except Exception as e:
        print(f"  Batch {i}: {e}")
    if i % 500 == 0:
        json.dump(cache, open(CACHE_PATH,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f"  {min(i+BATCH, len(codes))}/{len(codes)} — {added}")
    time.sleep(0.8)

json.dump(cache, open(CACHE_PATH,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"Done: {added} added py")
