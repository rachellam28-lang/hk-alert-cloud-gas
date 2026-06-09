"""
Refresh yfinance data in BATCHES for speed: prices, volume, 52wk hi/lo, PE, beta, suspended detection.
Saves: data/stock_prices.json + data/suspended_stocks.json
Run: python scripts/refresh_prices_and_suspended_fast.py

Strategy:
1. Fetch all ticker info in 1 batch download for price/volume/mcap
2. Fetch details (PE, beta, 52wk) in parallel thread pool for remaining
"""
import yfinance as yf
import sqlite3
import json
import time
import os
import sys
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "holdings.db"
SUSPENDED_PATH = PROJECT_ROOT / "data" / "suspended_stocks.json"
PRICES_PATH = PROJECT_ROOT / "data" / "stock_prices.json"

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ── Load existing ──
price_map = {}
if PRICES_PATH.exists():
    try:
        price_map = json.loads(PRICES_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass

# ── Get all active stocks ──
db = sqlite3.connect(str(DB_PATH))
rows = db.execute("""
    SELECT DISTINCT stock_code FROM holdings_daily 
    WHERE trade_date = (SELECT MAX(trade_date) FROM holdings_daily)
    ORDER BY stock_code
""").fetchall()
db.close()

all_codes = [row[0] for row in rows]
print(f"Fetching yfinance data for {len(all_codes)} stocks...")
sys.stdout.flush()

def safe_float(val):
    if val is None:
        return None
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    except (ValueError, TypeError):
        return None

def make_sym(code):
    return f'{int(code):04d}.HK'

# Step 1: Batch download latest prices + volume for all stocks
tickers = [make_sym(c) for c in all_codes]
print("Step 1: Batch downloading prices...")
sys.stdout.flush()

batch_data = None
suspended = {}
batch_attempt = 0

while batch_data is None and batch_attempt < 3:
    batch_attempt += 1
    try:
        # Split into chunks of 500 to avoid overwhelming yfinance
        all_dfs = []
        for chunk_start in range(0, len(tickers), 500):
            chunk = tickers[chunk_start:chunk_start+500]
            print(f"  Downloading chunk {chunk_start//500 + 1}/{math.ceil(len(tickers)/500)} ({len(chunk)} tickers)...")
            sys.stdout.flush()
            df = yf.download(chunk, period='5d', progress=False, threads=False)
            if not df.empty:
                all_dfs.append(df)
            time.sleep(2)
        if all_dfs:
            import pandas as pd
            batch_data = pd.concat(all_dfs)
        else:
            print("  WARNING: Empty download result")
            batch_data = None
    except Exception as e:
        print(f"  Batch download error: {e}")
        time.sleep(10)

if batch_data is None or batch_data.empty:
    print("FATAL: Could not download any price data. Using existing price_map only.")
else:
    # Process batch results
    last_close = batch_data['Close'].iloc[-1] if 'Close' in batch_data.columns else None
    last_vol = batch_data['Volume'].iloc[-1] if 'Volume' in batch_data.columns else None
    
    for code in all_codes:
        sym = make_sym(code)
        try:
            if sym in batch_data['Close'].columns:
                close_series = batch_data['Close'][sym].dropna()
                vol_series = batch_data['Volume'][sym].dropna()
                
                if len(close_series) == 0 or close_series.iloc[-1] <= 0:
                    suspended[code] = 'no_history'
                    continue
                
                # Check suspension by zero volume
                if len(vol_series) >= 3 and vol_series.sum() == 0:
                    suspended[code] = 'zero_vol_5d'
                    continue
                
                entry = price_map.get(code, {})
                is_new = code not in price_map
                entry['lp'] = safe_float(close_series.iloc[-1])
                entry['vol'] = safe_float(vol_series.iloc[-1]) if len(vol_series) > 0 else None
                entry['chg'] = safe_float((close_series.iloc[-1] / close_series.iloc[-2] - 1) * 100) if len(close_series) >= 2 else None
                
                price_map[code] = entry
            else:
                suspended[code] = 'no_history'
        except Exception as e:
            suspended[code] = str(e)[:80]
    
    print(f"Step 1 done: {len(suspended)} suspended, {len(price_map)} in price_map")
    sys.stdout.flush()

# Step 2: Fetch detailed info (PE, beta, 52wk) for non-suspended stocks
active_codes = [c for c in all_codes if c not in suspended]
print(f"Step 2: Fetching details for {len(active_codes)} active stocks...")
sys.stdout.flush()

updated = 0
new_entries = 0

def fetch_details(code):
    try:
        sym = make_sym(code)
        t = yf.Ticker(sym)
        info = t.info
        entry = price_map.get(code, {})
        entry['hi52'] = safe_float(info.get('fiftyTwoWeekHigh'))
        entry['lo52'] = safe_float(info.get('fiftyTwoWeekLow'))
        entry['pe'] = safe_float(info.get('trailingPE'))
        entry['beta'] = safe_float(info.get('beta'))
        entry['avg_vol'] = safe_float(info.get('averageVolume'))
        if entry.get('hi52') and entry.get('lo52') and entry['hi52'] > entry['lo52'] and entry.get('lp'):
            entry['p52'] = safe_float((entry['lp'] - entry['lo52']) / (entry['hi52'] - entry['lo52']) * 100)
        entry['lp'] = entry.get('lp') or safe_float(info.get('regularMarketPrice'))
        entry['chg'] = entry.get('chg') or safe_float(info.get('regularMarketChangePercent'))
        entry['vol'] = entry.get('vol') or safe_float(info.get('regularMarketVolume'))
        return (code, entry, True)
    except Exception as e:
        err = str(e)[:80]
        return (code, price_map.get(code, {}), False)

# Thread pool with 5 workers
batch_completed = 0
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(fetch_details, c): c for c in active_codes}
    for future in as_completed(futures):
        try:
            code, entry, ok = future.result()
            if ok:
                was_new = code not in price_map
                price_map[code] = entry
                if was_new:
                    new_entries += 1
                else:
                    updated += 1
            else:
                # Keep existing entry
                pass
            batch_completed += 1
            if batch_completed % 100 == 0:
                print(f"  {batch_completed}/{len(active_codes)} — {len(suspended)} susp, {updated} upd, {new_entries} new...")
                sys.stdout.flush()
        except Exception:
            pass

# ── Save ──
os.makedirs(SUSPENDED_PATH.parent, exist_ok=True)
with open(SUSPENDED_PATH, 'w') as f:
    json.dump(suspended, f, ensure_ascii=False)
with open(PRICES_PATH, 'w') as f:
    json.dump(price_map, f, ensure_ascii=False)

print(f"\nDone!")
print(f"  Suspended: {len(suspended)}")
print(f"  Updated: {updated}")
print(f"  New: {new_entries}")
print(f"  Total in price_map: {len(price_map)}")
print(f"\nFields per stock: lp, chg, vol, hi52, lo52, p52, pe, beta, avg_vol")
sys.stdout.flush()
