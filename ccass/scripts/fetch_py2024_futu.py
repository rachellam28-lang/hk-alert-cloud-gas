"""Fetch 2024 year-open prices via Futu OpenD."""
import json, time, sys
from pathlib import Path
from futu import *

ROOT = Path(__file__).resolve().parent.parent.parent
PRICES_PATH = ROOT / "data" / "stock_prices.json"
HOLDINGS_PATH = ROOT / "holdings.json"
sys.path.insert(0, str(ROOT / "scripts"))
from futu_env import ensure_futu_quote_backend_or_die

# Load existing prices
prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
holdings = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
codes = sorted(k for k,v in prices.items() if v.get('yo') and v.get('py') is None)  # only fill missing PY

print(f'Fetching 2024 year-open for {len(codes)} stocks via Futu...')

FUTU_HOST, FUTU_PORT = ensure_futu_quote_backend_or_die(ROOT)
q = OpenQuoteContext(FUTU_HOST, FUTU_PORT)
updated = 0
failed = 0

with open('py2024_futu.log', 'w') as log:
    for i, code in enumerate(codes):
        sym = f'HK.{code}'
        try:
            ret, data, page = q.request_history_kline(sym, start='2024-01-02', end='2024-01-02', ktype=KLType.K_DAY)
            if ret == 0 and len(data) > 0:
                py = round(float(data['open'].iloc[0]), 3)
                prices[code]['py'] = py
                if prices[code].get('lp') and py > 0:
                    prices[code]['py_pct'] = round((prices[code]['lp'] - py) / py * 100, 2)
                updated += 1
            else:
                failed += 1
                log.write(f'{code}: FAIL ret={ret}\n')
        except Exception as e:
            failed += 1
            log.write(f'{code}: EXCEPTION {e}\n')
        
        if (i+1) % 200 == 0:
            print(f'  {i+1}/{len(codes)} updated={updated} failed={failed}')
            # Save checkpoint
            tmp_prices = PRICES_PATH.with_suffix('.tmp')
            tmp_prices.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_prices.replace(PRICES_PATH)
        
        time.sleep(0.3)  # ~3 calls/sec to avoid rate limit

q.close()

# Final save
tmp_prices = PRICES_PATH.with_suffix('.tmp')
tmp_prices.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
tmp_prices.replace(PRICES_PATH)
print(f'Done: {updated} updated, {failed} failed')

# Update holdings.json
for s in holdings['stocks']:
    code = s['c']
    if code in prices:
        p = prices[code]
        if p.get('py') is not None:
            s['py'] = p['py']
            if p.get('py_pct') is not None:
                s['py_pct'] = p['py_pct']
        else:
            s.pop('py', None)
            s.pop('py_pct', None)

tmp_holdings = HOLDINGS_PATH.with_suffix('.tmp')
tmp_holdings.write_text(json.dumps(holdings, ensure_ascii=False, indent=2), encoding="utf-8")
tmp_holdings.replace(HOLDINGS_PATH)
print('holdings.json updated')

# Verify
for code in ['00700','00005','01808','00001','09988']:
    p = prices.get(code, {})
    print(f'{code}: py={p.get("py")}, py_pct={p.get("py_pct")}%')
