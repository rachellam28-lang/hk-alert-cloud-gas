"""Daily: fetch ALL market data from Futu OpenD — lp, mc, hi52, lo52, pe, vol, chg, vr.
Run after HK market close (~5pm HKT). Requires Futu gateway.
"""
import json, sys, time, math
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # holdings-debug/
PRICES = ROOT / "data" / "stock_prices.json"
HOLDINGS = ROOT / "holdings.json"
SUSPENDED = ROOT / "data" / "suspended_stocks.json"
sys.path.insert(0, str(ROOT / "scripts"))
from futu_env import ensure_futu_quote_backend_or_die


FUTU_HOST, FUTU_PORT = ensure_futu_quote_backend_or_die(ROOT)

prices = json.loads(PRICES.read_text(encoding='utf-8'))
codes = sorted(k for k,v in prices.items() if v.get('yo'))
print(f"Daily Futu update for {len(codes)} stocks...")
print(f"Using FutuOpenD {FUTU_HOST}:{FUTU_PORT}")

from futu import OpenQuoteContext, RET_OK

q = OpenQuoteContext(FUTU_HOST, FUTU_PORT)
BATCH = 200
counts = {'lp':0,'mc':0,'hi52':0,'lo52':0,'pe':0,'vol':0,'chg':0,'vr':0}
suspended: dict[str, str] = {}
COUNT_KEY = {
    'last_price': 'lp',
    'total_market_val': 'mc',
    'highest52weeks_price': 'hi52',
    'lowest52weeks_price': 'lo52',
    'pe_ratio': 'pe',
    'volume': 'vol',
    'prev_close_price': 'chg',
    'volume_ratio': 'vr',
}

for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    syms = [f"HK.{c}" for c in batch]
    try:
        ret, data = q.get_market_snapshot(syms)
        if ret == RET_OK and data is not None and len(data) > 0:
            seen: set[str] = set()
            for _, row in data.iterrows():
                code = row.get('code','').replace('HK.','')
                seen.add(code)
                e = prices.get(code, {})
                changed = False
                lp_seen = False

                for futu_key, our_key, scale in [
                    ('last_price','lp',1), ('total_market_val','mc',1e8),
                    ('highest52weeks_price','hi52',1), ('lowest52weeks_price','lo52',1),
                    ('pe_ratio','pe',1), ('volume','vol',1),
                    ('prev_close_price','prev_close',1), ('volume_ratio','vr',1),
                ]:
                    val = row.get(futu_key)
                    if val is not None and (not isinstance(val, float) or (not math.isnan(val) and val > 0)):
                        if scale != 1: val = round(float(val) / scale, 2)
                        else: val = round(float(val), 3) if futu_key != 'pe_ratio' else round(float(val), 2)
                        if e.get(our_key) != val:
                            e[our_key] = val
                            counts[COUNT_KEY[futu_key]] += 1
                            changed = True
                        if our_key == 'lp':
                            lp_seen = True

                # chg = (lp - prev_close) / prev_close * 100
                if e.get('lp') and e.get('prev_close') and e['prev_close'] > 0:
                    c = round((e['lp'] - e['prev_close']) / e['prev_close'] * 100, 2)
                    if e.get('chg') != c:
                        e['chg'] = c
                        counts['chg'] += 1

                if changed:
                    prices[code] = e
                if not lp_seen or not e.get('lp') or (e.get('vol') is not None and e.get('vol') == 0):
                    suspended.setdefault(code, 'no_price_or_zero_volume')

            for code in batch:
                if code not in seen:
                    suspended.setdefault(code, 'missing_snapshot')
    except Exception as ex:
        print(f"  Batch {i} error: {ex}")
        for code in batch:
            suspended.setdefault(code, 'batch_error')

    if (i // BATCH) % 10 == 0:
        print(f"  {min(i+BATCH, len(codes))}/{len(codes)} lp={counts['lp']} mc={counts['mc']}")
    time.sleep(0.3)

q.close()

# Compute derived fields
for code, e in prices.items():
    if e.get('lp') and e.get('hi52') and e.get('lo52') and e['hi52'] > e['lo52']:
        e['p52'] = round((e['lp'] - e['lo52']) / (e['hi52'] - e['lo52']) * 100, 1)
    effective_py = e.get('apy', e.get('py'))
    if e.get('lp') and effective_py and effective_py > 0:
        e['py_pct'] = round((e['lp'] - effective_py) / effective_py * 100, 2)
        if e.get('apy'):
            e['apy_pct'] = e['py_pct']

def sanitize(obj):
    if isinstance(obj, dict): return {k: sanitize(v) for k,v in obj.items()}
    if isinstance(obj, list): return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
    return obj

prices = sanitize(prices)
PRICES.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding='utf-8')
SUSPENDED.write_text(json.dumps(suspended, ensure_ascii=False, indent=2), encoding='utf-8')

# Update holdings.json
holdings = json.loads(HOLDINGS.read_text(encoding='utf-8'))
for s in holdings['stocks']:
    code = s['c']
    e = prices.get(code, {})
    effective_py = e.get('apy', e.get('py'))
    if effective_py is not None:
        s['py'] = effective_py
    for k in ['lp','mc','hi52','lo52','pe','vol','vr','chg','p52','py_pct']:
        if e.get(k) is not None:
            s[k] = e[k]

holdings['stocks'] = sanitize(holdings['stocks'])
tmp = HOLDINGS.with_suffix('.tmp')
tmp.write_text(json.dumps(holdings, ensure_ascii=False, indent=2), encoding='utf-8')
tmp.replace(HOLDINGS)

print(f"Done: {counts}")
print(f"Suspended: {len(suspended)}")
