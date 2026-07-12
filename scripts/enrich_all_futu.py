"""
Fetch ALL available market data from Futu gateway:
mc, hi52, lo52, pe, vol → compute p52, and enrich holdings.json.
"""
import json, time, sys
from pathlib import Path
from futu import OpenQuoteContext, RET_OK
from futu_env import ensure_futu_quote_backend_or_die

ROOT = Path(__file__).parent.parent
CACHE = ROOT / "ccass" / "cache" / "enrich_futu.json"
CCASS_JSON = ROOT / "holdings.json"

# Load existing cache
cache = {}
if CACHE.exists():
    try:
        cache = json.loads(CACHE.read_text(encoding='utf-8'))
    except:
        pass

# Load holdings.json
with open(CCASS_JSON) as f:
    ccass = json.load(f)

codes = sorted(set(s['c'] for s in ccass['stocks']))
print(f"Total stocks: {len(codes)}")

# Find which need enrichment
needed = []
for c in codes:
    entry = cache.get(c, {})
    # Fetch if ANY field is missing
    if any(entry.get(f) is None for f in ['mc', 'hi52', 'lo52', 'pe', 'vol']):
        # But skip if we have ALL and they're non-null
        if c not in cache:
            needed.append(c)
        else:
            e = cache[c]
            missing = [f for f in ['mc','hi52','lo52','pe','vol'] if e.get(f) is None]
            if missing:
                needed.append(c)
            # Also refetch if mc was just filled but other fields missing
            elif not all(e.get(f) is not None for f in ['hi52','lo52','pe','vol']):
                needed.append(c)

# Deduplicate
needed = sorted(set(needed))
print(f"Need data for: {len(needed)} stocks")

if not needed:
    print("All done!")
    sys.exit(0)

# Connect to Futu
FUTU_HOST, FUTU_PORT = ensure_futu_quote_backend_or_die(ROOT)
quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
print("Connected to Futu gateway")

BATCH_SIZE = 200
fetched = 0
errors = 0
filled = {'mc': 0, 'hi52': 0, 'lo52': 0, 'pe': 0, 'vol': 0}

for i in range(0, len(needed), BATCH_SIZE):
    batch = needed[i:i+BATCH_SIZE]
    symbols = [f"HK.{c}" for c in batch]

    try:
        ret, data = quote_ctx.get_market_snapshot(symbols)
        if ret == RET_OK and data is not None and len(data) > 0:
            for _, row in data.iterrows():
                code = row.get('code', '').replace('HK.', '')
                entry = cache.get(code, {})

                # Market cap
                mc = row.get('total_market_val')
                if mc is not None and mc > 0 and entry.get('mc') is None:
                    entry['mc'] = round(float(mc) / 1e8, 2)
                    filled['mc'] += 1

                # 52-week high
                hi = row.get('highest52weeks_price')
                if hi is not None and hi > 0 and entry.get('hi52') is None:
                    entry['hi52'] = round(float(hi), 4)
                    filled['hi52'] += 1

                # 52-week low
                lo = row.get('lowest52weeks_price')
                if lo is not None and lo > 0 and entry.get('lo52') is None:
                    entry['lo52'] = round(float(lo), 4)
                    filled['lo52'] += 1

                # PE ratio
                pe = row.get('pe_ratio')
                if pe is not None and pe > 0 and entry.get('pe') is None:
                    entry['pe'] = round(float(pe), 2)
                    filled['pe'] += 1

                # Volume
                vol = row.get('volume')
                if vol is not None and vol > 0 and entry.get('vol') is None:
                    entry['vol'] = round(float(vol), 2)
                    filled['vol'] += 1

                cache[code] = entry
                fetched += 1
        else:
            errors += len(batch)
    except Exception as e:
        print(f"  Batch error: {e}")
        errors += len(batch)

    progress = min(i + BATCH_SIZE, len(needed))
    print(f"  {progress}/{len(needed)} — filled: {filled}")

    if i + BATCH_SIZE < len(needed):
        time.sleep(0.3)

quote_ctx.close()

# Save cache
CACHE.parent.mkdir(parents=True, exist_ok=True)
CACHE.write_text(json.dumps(cache, ensure_ascii=False))

# Now enrich holdings.json
for s in ccass['stocks']:
    c = s['c']
    entry = cache.get(c, {})

    if s.get('mc') is None and entry.get('mc') is not None:
        s['mc'] = entry['mc']
    if s.get('hi52') is None and entry.get('hi52') is not None:
        s['hi52'] = entry['hi52']
    if s.get('lo52') is None and entry.get('lo52') is not None:
        s['lo52'] = entry['lo52']
    if s.get('pe') is None and entry.get('pe') is not None:
        s['pe'] = entry['pe']
    if s.get('vol') is None and entry.get('vol') is not None:
        s['vol'] = entry['vol']

    # Compute p52 = (lp - lo52) / (hi52 - lo52) * 100
    if s.get('p52') is None and s.get('lp') is not None:
        hi = s.get('hi52')
        lo = s.get('lo52')
        lp = s.get('lp')
        if hi and lo and hi > lo:
            s['p52'] = round((lp - lo) / (hi - lo) * 100, 1)

    # Compute vr = vol / avg_vol (if both available)
    if s.get('vr') is None:
        vol = s.get('vol')
        avg = s.get('avg_vol')
        if vol and avg and avg > 0:
            s['vr'] = round(vol / avg, 2)

# Sanitize NaN
import math
def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj

ccass['stocks'] = sanitize(ccass['stocks'])

# Save
tmp = CCASS_JSON.with_suffix('.tmp')
tmp.write_text(json.dumps(ccass, ensure_ascii=False, indent=2), encoding='utf-8')
tmp.replace(CCASS_JSON)

# Stats
stocks = ccass['stocks']
total = len(stocks)
for f in ['mc','hi52','lo52','p52','pe','vol','vr']:
    nulls = sum(1 for s in stocks if s.get(f) is None)
    has = total - nulls
    print(f"  {f}: {has}/{total} ({100*has/total:.0f}%)")

print(f"\nDone! Fetched: {fetched}, errors: {errors}")
print(f"Filled: {filled}")
