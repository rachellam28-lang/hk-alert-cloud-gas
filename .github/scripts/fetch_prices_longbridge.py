"""Fetch stock prices via Longbridge API for GitHub Actions."""
import json, os, sys, time
from pathlib import Path

PROJ = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJ / 'ccass'))

from longbridge.openapi import Config, QuoteContext

def main():
    token = os.environ.get('LONGBRIDGE_ACCESS_TOKEN', '')
    if not token:
        print('ERROR: LONGBRIDGE_ACCESS_TOKEN not set', file=sys.stderr)
        sys.exit(1)

    config = Config.from_env()
    ctx = QuoteContext(config)

    import sqlite3
    db_path = PROJ / 'ccass' / 'ccass.db'
    db = sqlite3.connect(str(db_path))
    codes = [r[0] for r in db.execute(
        'SELECT DISTINCT stock_code FROM ccass_daily ORDER BY stock_code'
    ).fetchall()]
    db.close()
    print(f'Active stocks: {len(codes)}')

    groups = []
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        symbols = [f'{c}.HK' for c in batch]
        try:
            resp = ctx.quote(symbols)
            for j, q in enumerate(resp):
                code = batch[j].zfill(5)
                chg_pct = 0
                if q and q.last_done and q.prev_close and q.prev_close > 0:
                    chg_pct = round((q.last_done - q.prev_close) / q.prev_close * 100, 2)
                groups.append({
                    'code': code,
                    'latestPrice': q.last_done if q else None,
                    'prevClose': q.prev_close if q else None,
                    'changePercent': chg_pct if q else None,
                    'volume': q.volume if q else None,
                    'turnover': q.turnover if q else None,
                })
        except Exception as e:
            print(f'Batch {i}-{i+batch_size}: {e}', file=sys.stderr)
            for code in batch:
                groups.append({'code': code.zfill(5)})
        time.sleep(1)
        if (i // batch_size) % 10 == 0:
            print(f'Progress: {i+len(batch)}/{len(codes)}')

    out = {'ok': True, 'groups': groups, 'count': len(groups)}
    out_path = PROJ / 'data' / 'prices.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'Written {len(groups)} stocks to {out_path}')

if __name__ == '__main__':
    main()
