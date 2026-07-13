"""Fetch REAL data from Futu: lp (latest price) + yo (2026 year-open).
Prerequisite: Futu OpenD running at FUTU_HOST:FUTU_PORT from repo .env.
"""
import json, time, math, sys
from pathlib import Path
from futu import OpenQuoteContext, KLType, RET_OK

ROOT = Path(__file__).parent.parent.parent  # holdings-debug/
HOLDINGS = ROOT / "holdings.json"
PRICES = ROOT / "data" / "stock_prices.json"
sys.path.insert(0, str(ROOT / "scripts"))
from futu_env import ensure_futu_quote_backend_or_die


def sanitize(obj):
    if isinstance(obj, dict):
        return {key: sanitize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [sanitize(value) for value in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def save_prices():
    PRICES.write_text(
        json.dumps(sanitize(prices), ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8',
    )

# Load
prices = json.loads(PRICES.read_text(encoding='utf-8'))
holdings = json.loads(HOLDINGS.read_text(encoding='utf-8'))
codes = sorted(k for k,v in prices.items() if v.get('yo'))  # only active stocks
print(f"Total active stocks: {len(codes)}")

FUTU_HOST, FUTU_PORT = ensure_futu_quote_backend_or_die(ROOT)
q = OpenQuoteContext(FUTU_HOST, FUTU_PORT)
updated_lp = 0
updated_yo = 0
failed = 0

# === PHASE 1: Latest prices via get_market_snapshot ===
print("\n--- Phase 1: Latest prices ---")
BATCH = 200
for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    syms = [f"HK.{c}" for c in batch]
    try:
        ret, data = q.get_market_snapshot(syms)
        if ret == RET_OK and data is not None and len(data) > 0:
            for _, row in data.iterrows():
                code = row.get('code', '').replace('HK.', '')
                lp = row.get('last_price')
                if lp is not None and lp > 0:
                    prices[code]['lp'] = round(float(lp), 3)
                    updated_lp += 1
    except Exception as e:
        print(f"  Batch {i} error: {e}")
        failed += len(batch)
    
    if (i // BATCH) % 5 == 0:
        print(f"  {min(i+BATCH, len(codes))}/{len(codes)} updated={updated_lp}")
    time.sleep(0.3)

# Save checkpoint
save_prices()

# === PHASE 2: 2026 year-open via request_history_kline ===
print("\n--- Phase 2: 2026 year-open ---")
with open(ROOT / 'py_yoyo_futu.log', 'w') as log:
    for i, code in enumerate(codes):
        sym = f'HK.{code}'
        try:
            ret, data, page = q.request_history_kline(sym, start='2026-01-02', end='2026-01-02', ktype=KLType.K_DAY)
            if ret == 0 and len(data) > 0:
                yo = round(float(data['open'].iloc[0]), 3)
                prices[code]['yo'] = yo
                updated_yo += 1
            else:
                log.write(f'{code}: FAIL ret={ret}\n')
        except Exception as e:
            log.write(f'{code}: EXCEPTION {e}\n')
        
        if (i+1) % 500 == 0:
            print(f"  {i+1}/{len(codes)} updated={updated_yo}")
            save_prices()
        time.sleep(0.3)

q.close()

# Final save
save_prices()

# === Update holdings.json ===
print("\n--- Updating holdings.json ---")
for s in holdings['stocks']:
    code = s['c']
    if code in prices:
        p = prices[code]
        if p.get('lp') is not None:
            s['lp'] = p['lp']
        if p.get('yo') is not None:
            s['yo'] = p['yo']
        # Recompute yo_pct (not stored in holdings.json, computed client-side)
        # Recompute p52 if hi52/lo52 available
        if s.get('p52') is None and s.get('lp') and s.get('hi52') and s.get('lo52'):
            hi, lo, lp = s['hi52'], s['lo52'], s['lp']
            if hi > lo:
                s['p52'] = round((lp - lo) / (hi - lo) * 100, 1)
        # py_pct
        if prices[code].get('py_pct') is not None:
            s['py_pct'] = prices[code]['py_pct']

holdings['stocks'] = sanitize(holdings['stocks'])

tmp = HOLDINGS.with_suffix('.tmp')
tmp.write_text(json.dumps(holdings, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
tmp.replace(HOLDINGS)

# Verify
for code in ['00700','00005','01808','09988','00001']:
    p = prices.get(code, {})
    s = next((x for x in holdings['stocks'] if x['c']==code), {})
    print(f"  {code}: lp={p.get('lp')}, yo={p.get('yo')}, py={p.get('py')}, py_pct={p.get('py_pct')}%")

print(f"\nDone! lp={updated_lp}, yo={updated_yo}, failed={failed}")
