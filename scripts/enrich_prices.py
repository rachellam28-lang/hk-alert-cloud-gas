"""
Compute enrichment fields from existing DB stock_prices table,
and fill market caps from cache. Then save to stock_prices.json.
"""
import sqlite3, json, math
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).parent.parent
DB = ROOT / "ccass" / "ccass.db"
PRICES_JSON = ROOT / "data" / "stock_prices.json"
MC_CACHE = ROOT / "ccass" / "cache" / "market_caps.json"

db = sqlite3.connect(str(DB))
db.row_factory = sqlite3.Row

# Get active stock codes from latest day
latest_date = db.execute("SELECT MAX(trade_date) FROM ccass_daily").fetchone()[0]
print(f"Latest CCASS date: {latest_date}")

codes = [r[0] for r in db.execute(
    "SELECT DISTINCT stock_code FROM ccass_daily WHERE trade_date=? ORDER BY stock_code",
    (latest_date,)
).fetchall()]
print(f"Active stocks: {len(codes)}")

def safe(v):
    if v is None: return None
    try:
        f = float(v)
        return round(f, 4) if not (math.isnan(f) or math.isinf(f)) else None
    except: return None

# Load existing prices
price_map = {}
if PRICES_JSON.exists():
    price_map = json.loads(PRICES_JSON.read_text(encoding='utf-8'))

# Load market caps
mc_map = {}
if MC_CACHE.exists():
    try:
        mc_data = json.loads(MC_CACHE.read_text(encoding='utf-8'))
        if isinstance(mc_data, list):
            for item in mc_data:
                mc_map[item['stock_code']] = item.get('market_cap')
        elif isinstance(mc_data, dict):
            mc_map = mc_data
    except: pass

# For each stock, compute from DB
stats = {'updated': 0, 'new': 0, 'mc_hit': 0, 'mc_miss': 0, 'p52_done': 0, 'avgvol_done': 0, 'chg_done': 0}
cutoff_52w = (date.today() - timedelta(days=365)).isoformat()

for i, code in enumerate(codes):
    entry = price_map.get(code, {})
    is_new = code not in price_map
    
    # Get latest 2 price rows from DB
    rows = db.execute(
        "SELECT close, high, low, volume, price_date FROM stock_prices WHERE stock_code=? ORDER BY price_date DESC LIMIT 2",
        (code,)
    ).fetchall()
    
    if not rows:
        price_map[code] = entry
        continue
    
    # Latest price
    if not entry.get('lp'):
        entry['lp'] = safe(rows[0]['close'])
    # Volume
    if not entry.get('vol'):
        entry['vol'] = safe(rows[0]['volume'])
    # Today change %
    if not entry.get('chg') and len(rows) >= 2 and rows[1]['close'] and rows[0]['close']:
        entry['chg'] = safe((rows[0]['close'] / rows[1]['close'] - 1) * 100)
        stats['chg_done'] += 1
    
    # 52-week high/low from DB
    if not (entry.get('hi52') and entry.get('lo52')):
        hilo = db.execute(
            "SELECT MAX(high) as hi, MIN(low) as lo FROM stock_prices WHERE stock_code=? AND price_date >= ?",
            (code, cutoff_52w)
        ).fetchone()
        if hilo and hilo['hi']:
            entry['hi52'] = safe(hilo['hi'])
            entry['lo52'] = safe(hilo['lo'])
            if entry.get('lp') and entry['hi52'] and entry['lo52'] and entry['hi52'] > entry['lo52']:
                entry['p52'] = safe((entry['lp'] - entry['lo52']) / (entry['hi52'] - entry['lo52']) * 100)
                stats['p52_done'] += 1
    
    # Average volume (20-day)
    if not entry.get('avg_vol'):
        avg = db.execute(
            "SELECT AVG(volume) as avg_vol FROM stock_prices WHERE stock_code=? AND price_date >= ?",
            (code, (date.today() - timedelta(days=30)).isoformat())
        ).fetchone()
        if avg and avg['avg_vol']:
            entry['avg_vol'] = safe(avg['avg_vol'])
            stats['avgvol_done'] += 1
    
    # Market cap from cache
    if not entry.get('mc'):
        mc = mc_map.get(code)
        if mc is not None:
            entry['mc'] = mc
            stats['mc_hit'] += 1
        else:
            stats['mc_miss'] += 1
    
    price_map[code] = entry
    if is_new: stats['new'] += 1
    else: stats['updated'] += 1
    
    if (i+1) % 500 == 0:
        print(f"  {i+1}/{len(codes)}...")

# Save
PRICES_JSON.parent.mkdir(parents=True, exist_ok=True)
PRICES_JSON.write_text(json.dumps(price_map, ensure_ascii=False))

print(f"\nSaved {len(price_map)} stocks to stock_prices.json")
print(f"  New: {stats['new']}, Updated: {stats['updated']}")
print(f"  P52 filled: {stats['p52_done']}")
print(f"  avgVol filled: {stats['avgvol_done']}")
print(f"  chg filled: {stats['chg_done']}")
print(f"  MC hit: {stats['mc_hit']}, MC miss: {stats['mc_miss']}")

# Verify a few
for c in ['00001', '00005', '00700', '09988']:
    e = price_map.get(c, {})
    fields = {k: e.get(k) for k in ['lp', 'chg', 'vol', 'hi52', 'lo52', 'p52', 'avg_vol', 'mc']}
    print(f"  {c}: {fields}")
