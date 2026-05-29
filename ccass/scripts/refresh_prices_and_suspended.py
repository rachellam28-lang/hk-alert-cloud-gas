"""
Refresh yfinance data: prices, volume, 52wk hi/lo, PE, beta, suspended detection.
Saves: data/stock_prices.json + data/suspended_stocks.json
Run: python scripts/refresh_prices_and_suspended.py
"""
import yfinance as yf, sqlite3, json, time, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "ccass.db"
SUSPENDED_PATH = PROJECT_ROOT / "data" / "suspended_stocks.json"
PRICES_PATH = PROJECT_ROOT / "data" / "stock_prices.json"

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
    SELECT DISTINCT stock_code FROM ccass_daily 
    WHERE trade_date = (SELECT MAX(trade_date) FROM ccass_daily)
    ORDER BY stock_code
""").fetchall()
db.close()

all_codes = [row[0] for row in rows]
print(f"Fetching yfinance data for {len(all_codes)} stocks...")

suspended = {}
updated = 0
new_entries = 0

def safe_float(val):
    """Safely convert to rounded float or None."""
    if val is None:
        return None
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return None

for i, code in enumerate(all_codes):
    try:
        sym = f'{int(code):04d}.HK'
        t = yf.Ticker(sym)
        info = t.info
        hist = t.history(period='5d')
        
        # ── Suspension check ──
        is_suspended = False
        if len(hist) == 0:
            is_suspended = True
            suspended[code] = 'no_history'
        elif info.get('quoteType') == 'MUTUALFUND' and info.get('regularMarketPrice') is None:
            if hist['Volume'].sum() == 0 and len(hist) >= 3:
                is_suspended = True
                suspended[code] = 'zero_vol_5d'
        elif hist['Volume'].sum() == 0 and len(hist) >= 3:
            is_suspended = True
            suspended[code] = 'zero_vol_5d'
        
        # ── Fetch all yfinance fields ──
        if not is_suspended:
            try:
                lp = t.fast_info.last_price
                if lp and lp > 0:
                    entry = price_map.get(code, {})
                    is_new = code not in price_map
                    
                    # All yfinance fields (compact keys)
                    entry['lp'] = safe_float(lp)
                    entry['chg'] = safe_float(info.get('regularMarketChangePercent'))
                    entry['vol'] = safe_float(info.get('regularMarketVolume'))
                    entry['hi52'] = safe_float(info.get('fiftyTwoWeekHigh'))
                    entry['lo52'] = safe_float(info.get('fiftyTwoWeekLow'))
                    entry['pe'] = safe_float(info.get('trailingPE'))
                    entry['beta'] = safe_float(info.get('beta'))
                    entry['avg_vol'] = safe_float(info.get('averageVolume'))
                    
                    # Compute 52wk position % (how close to high)
                    if entry['hi52'] and entry['lo52'] and entry['hi52'] > entry['lo52']:
                        entry['p52'] = safe_float(
                            (entry['lp'] - entry['lo52']) / (entry['hi52'] - entry['lo52']) * 100
                        )
                    
                    price_map[code] = entry
                    if is_new:
                        new_entries += 1
                    else:
                        updated += 1
            except Exception:
                pass
            
    except Exception as e:
        err = str(e)[:80]
        if 'delisted' in err.lower() or 'no price data' in err.lower():
            suspended[code] = 'delisted'
    
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(all_codes)} — {len(suspended)} susp, {updated} upd, {new_entries} new...")
        time.sleep(1)

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
