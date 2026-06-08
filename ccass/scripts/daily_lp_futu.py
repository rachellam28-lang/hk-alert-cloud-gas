"""Daily: fetch ALL market data from Futu OpenD — lp, mc, hi52, lo52, pe, vol, chg, vr.
Run after HK market close (~5pm HKT). Requires Futu gateway on 127.0.0.1:11111.
"""
import json, time, math
from pathlib import Path
from futu import OpenQuoteContext, RET_OK

ROOT = Path(__file__).parent.parent.parent  # ccass-debug/
PRICES = ROOT / "data" / "stock_prices.json"
CCASS = ROOT / "ccass.json"

prices = json.loads(PRICES.read_text(encoding='utf-8'))
codes = sorted(k for k,v in prices.items() if v.get('yo'))
print(f"Daily Futu update for {len(codes)} stocks...")

q = OpenQuoteContext('127.0.0.1', 11111)
BATCH = 200
counts = {'lp':0,'mc':0,'hi52':0,'lo52':0,'pe':0,'vol':0,'chg':0,'vr':0}

for i in range(0, len(codes), BATCH):
    batch = codes[i:i+BATCH]
    syms = [f"HK.{c}" for c in batch]
    try:
        ret, data = q.get_market_snapshot(syms)
        if ret == RET_OK and data is not None and len(data) > 0:
            for _, row in data.iterrows():
                code = row.get('code','').replace('HK.','')
                e = prices.get(code, {})
                changed = False

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
                            counts[our_key[:2] if our_key != 'prev_close' else 'chg'] += 1
                            changed = True

                # chg = (lp - prev_close) / prev_close * 100
                if e.get('lp') and e.get('prev_close') and e['prev_close'] > 0:
                    c = round((e['lp'] - e['prev_close']) / e['prev_close'] * 100, 2)
                    if e.get('chg') != c:
                        e['chg'] = c
                        counts['chg'] += 1

                if changed:
                    prices[code] = e
    except Exception as ex:
        print(f"  Batch {i} error: {ex}")

    if (i // BATCH) % 10 == 0:
        print(f"  {min(i+BATCH, len(codes))}/{len(codes)} lp={counts['lp']} mc={counts['mc']}")
    time.sleep(0.3)

q.close()

# Compute derived fields
for code, e in prices.items():
    if e.get('lp') and e.get('hi52') and e.get('lo52') and e['hi52'] > e['lo52']:
        e['p52'] = round((e['lp'] - e['lo52']) / (e['hi52'] - e['lo52']) * 100, 1)
    if e.get('lp') and e.get('py') and e['py'] > 0:
        e['py_pct'] = round((e['lp'] - e['py']) / e['py'] * 100, 2)

def sanitize(obj):
    if isinstance(obj, dict): return {k: sanitize(v) for k,v in obj.items()}
    if isinstance(obj, list): return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
    return obj

prices = sanitize(prices)
PRICES.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding='utf-8')

# Update ccass.json
ccass = json.loads(CCASS.read_text(encoding='utf-8'))
for s in ccass['stocks']:
    code = s['c']
    e = prices.get(code, {})
    for k in ['lp','mc','hi52','lo52','pe','vol','vr','chg','p52','py_pct']:
        if e.get(k) is not None:
            s[k] = e[k]

ccass['stocks'] = sanitize(ccass['stocks'])
tmp = CCASS.with_suffix('.tmp')
tmp.write_text(json.dumps(ccass, ensure_ascii=False, indent=2), encoding='utf-8')
tmp.replace(CCASS)

print(f"Done: {counts}")
