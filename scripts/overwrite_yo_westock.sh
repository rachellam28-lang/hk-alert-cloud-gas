#!/bin/bash
# Overwrite ALL yo with westock real data
# Also retry missing d60/d120 stocks
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CCASS_JSON="$PROJECT_DIR/ccass.json"
TEMP_DIR="$(mktemp -d)"

echo "=== Parsing existing batch files to extract yo for ALL stocks ==="
python -c "
import json, re, os, glob

temp_dir = r'$TEMP_DIR'
ccass_path = r'$CCASS_JSON'

with open(ccass_path) as f:
    data = json.load(f)

stock_map = {s['c']: s for s in data['stocks']}

# Parse all batch files for yo
batch_files = sorted(glob.glob(os.path.join(temp_dir, 'batch_*.txt')))
print(f'Parsing {len(batch_files)} batch files...')

yo_updates = 0
d60_updates = 0
d120_updates = 0

for bf in batch_files:
    with open(bf) as f:
        text = f.read()
    
    result = {}
    current_code = None
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('[Batch]') or line.startswith('| ---') or line.startswith('| symbol |'):
            continue
        cols = [c.strip() for c in line.split('|')]
        if len(cols) < 7:
            continue
        sym_match = re.match(r'hk(\d{5})', cols[1]) if len(cols) > 1 else None
        if sym_match:
            current_code = sym_match.group(1)
            try:
                result.setdefault(current_code, []).append({
                    'date': cols[2],
                    'open': float(cols[3]) if cols[3] else None,
                    'close': float(cols[4]) if cols[4] else None,
                })
            except (ValueError, IndexError):
                continue
    
    for code, rows in result.items():
        s = stock_map.get(code)
        if not s or not rows:
            continue
        
        latest_close = rows[0]['close']
        if latest_close is None:
            continue
        
        # Overwrite yo with westock 2026 first trading day open
        d2026 = [r for r in rows if r['date'].startswith('2026')]
        if d2026:
            d2026.sort(key=lambda r: r['date'])
            yo_open = d2026[0]['open']
            if yo_open and yo_open > 0:
                old_yo = s.get('yo')
                s['yo'] = yo_open
                yo_updates += 1
                if old_yo and old_yo != yo_open:
                    pass  # replaced legacy value
        
        # Fill missing d60/d120
        for n, key in [(60, 'd60'), (120, 'd120')]:
            if s.get(key) is None and len(rows) > n:
                past = rows[n]['close']
                if past and past != 0:
                    s[key] = round((latest_close - past) / past, 4)
                    if key == 'd60': d60_updates += 1
                    else: d120_updates += 1

# Save
tmp = ccass_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, ensure_ascii=False)
os.replace(tmp, ccass_path)

# Stats
total = len(data['stocks'])
d60_ok = sum(1 for s in data['stocks'] if s.get('d60') is not None)
d120_ok = sum(1 for s in data['stocks'] if s.get('d120') is not None)
yo_ok = sum(1 for s in data['stocks'] if s.get('yo') is not None)
print(f'yo overwritten: {yo_updates}')
print(f'd60 new: {d60_updates}, d120 new: {d120_updates}')
print(f'Final: d60={d60_ok}/{total}, d120={d120_ok}/{total}, yo={yo_ok}/{total}')

# List still-missing
missing = [s for s in data['stocks'] if s.get('d60') is None]
if missing:
    print(f'\nStill missing d60: {len(missing)}')
    print('First 10:', [(s['c'], s['n']) for s in missing[:10]])
"

# Verify a few samples
echo ""
echo "=== Sample verification ==="
python -c "
import json
with open(r'$CCASS_JSON') as f:
    data = json.load(f)
stocks = {s['c']: s for s in data['stocks']}
for c in ['00700','00005','09988','00388','01808']:
    s = stocks.get(c)
    if s:
        print(f\"{c} {s['n']}: yo={s.get('yo')}, d60={s.get('d60')}, d120={s.get('d120')}\")
"

echo ""
echo "=== Done! ==="
