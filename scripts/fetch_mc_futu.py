
"""Fetch market caps via Futu gateway for missing stocks."""
import json, time
from pathlib import Path
from futu import OpenQuoteContext, RET_OK, SubType, KLType
from futu_env import ensure_futu_quote_backend_or_die

ROOT = Path(__file__).parent.parent
MC_CACHE = ROOT / "ccass" / "cache" / "market_caps.json"
CCASS_JSON = ROOT / "ccass.json"

# Load existing market caps
mc_map = {}
if MC_CACHE.exists():
    try:
        data = json.loads(MC_CACHE.read_text(encoding='utf-8'))
        if isinstance(data, list):
            for item in data:
                mc_map[item['stock_code']] = item.get('market_cap')
        elif isinstance(data, dict):
            mc_map = data
    except: pass

# Load stock list from ccass.json
with open(CCASS_JSON) as f:
    ccass = json.load(f)
codes = sorted(set(s['c'] for s in ccass['stocks']))

# Find missing market caps
missing = [c for c in codes if c not in mc_map or mc_map[c] is None]
print(f"Total: {len(codes)}, have mc: {len(codes)-len(missing)}, missing: {len(missing)}")

if not missing:
    print("All done!")
    import sys; sys.exit(0)

# Connect to Futu
FUTU_HOST, FUTU_PORT = ensure_futu_quote_backend_or_die(ROOT)
quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
print("Connected to Futu gateway")

BATCH_SIZE = 200
fetched = 0
errors = 0

for i in range(0, len(missing), BATCH_SIZE):
    batch = missing[i:i+BATCH_SIZE]
    # Format codes for Futu: HK.00001
    symbols = [f"HK.{c}" for c in batch]
    
    try:
        ret, data = quote_ctx.get_market_snapshot(symbols)
        if ret == RET_OK and data is not None and len(data) > 0:
            for _, row in data.iterrows():
                code = row.get('code', '').replace('HK.', '')
                mc = row.get('total_market_val')
                if mc is not None and mc > 0:
                    mc_map[code] = round(float(mc) / 1e8, 2)  # Convert to 億
                    fetched += 1
                else:
                    mc_map[code] = None
                    errors += 1
        else:
            for c in batch:
                mc_map[c] = None
                errors += 1
    except Exception as e:
        print(f"  Batch error: {e}")
        for c in batch:
            mc_map[c] = None
            errors += 1
    
    progress = min(i + BATCH_SIZE, len(missing))
    print(f"  {progress}/{len(missing)} — fetched: {fetched}, errors: {errors}")
    time.sleep(0.3)

quote_ctx.close()

# Save
output = [{"stock_code": k, "market_cap": v} for k, v in sorted(mc_map.items())]
MC_CACHE.parent.mkdir(parents=True, exist_ok=True)
MC_CACHE.write_text(json.dumps(output, ensure_ascii=False))

mc_count = sum(1 for v in mc_map.values() if v is not None)
print(f"\nDone! {mc_count}/{len(mc_map)} stocks with market cap")
print(f"Fetched this run: {fetched}, errors: {errors}")
