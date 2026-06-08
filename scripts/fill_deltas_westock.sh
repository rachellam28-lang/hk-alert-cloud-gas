#!/bin/bash
# Batch fill d60/d120/yo using westock-data kline
# Usage: bash fill_deltas_westock.sh

set -e

CCASS_JSON="C:/Users/Administrator/Desktop/automatic/ccass-debug/ccass.json"
TEMP_DIR="C:/Users/Administrator/AppData/Local/Temp/westock_fill"
BATCH_SIZE=50
DELAY=2

mkdir -p "$TEMP_DIR"

echo "=== Step 1: Extract stock codes ==="
python -c "
import json
with open(r'$CCASS_JSON') as f:
    data = json.load(f)
codes = [s['c'] for s in data['stocks'] if s.get('d60') is None or s.get('d120') is None]
print(f'Need fill: {len(codes)} stocks')
# Write codes to file
with open(r'$TEMP_DIR/codes.txt', 'w') as f:
    f.write('\n'.join(codes))
print('Codes written to codes.txt')
"

TOTAL=$(wc -l < "$TEMP_DIR/codes.txt")
echo "Total: $TOTAL stocks"
BATCHES=$(( (TOTAL + BATCH_SIZE - 1) / BATCH_SIZE ))
echo "Batches: $BATCHES"

echo ""
echo "=== Step 2: Fetch kline in batches ==="

BATCH_NUM=0
PROCESSED=0

# Split into batches and process
while IFS= read -r line; do
    BATCH_CODES+=("$line")
    if [ ${#BATCH_CODES[@]} -ge $BATCH_SIZE ]; then
        BATCH_NUM=$((BATCH_NUM + 1))
        # Build comma-separated codes
        CODE_STR=""
        for c in "${BATCH_CODES[@]}"; do
            [ -n "$CODE_STR" ] && CODE_STR="$CODE_STR,"
            CODE_STR="${CODE_STR}hk${c}"
        done
        
        echo "[$BATCH_NUM/$BATCHES] ${#BATCH_CODES[@]} codes: ${BATCH_CODES[0]}...${BATCH_CODES[-1]}"
        
        npx -y westock-data-clawhub@1.0.4 kline "$CODE_STR" --period day --limit 200 > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
        
        # Check if successful
        if grep -q "success" "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>/dev/null; then
            echo "  OK"
        else
            echo "  FAILED"
        fi
        
        PROCESSED=$((PROCESSED + ${#BATCH_CODES[@]}))
        BATCH_CODES=()
        sleep $DELAY
    fi
done < "$TEMP_DIR/codes.txt"

# Process remaining
if [ ${#BATCH_CODES[@]} -gt 0 ]; then
    BATCH_NUM=$((BATCH_NUM + 1))
    CODE_STR=""
    for c in "${BATCH_CODES[@]}"; do
        [ -n "$CODE_STR" ] && CODE_STR="$CODE_STR,"
        CODE_STR="${CODE_STR}hk${c}"
    done
    echo "[$BATCH_NUM/$BATCHES] ${#BATCH_CODES[@]} codes (final)"
    npx -y westock-data-clawhub@1.0.4 kline "$CODE_STR" --period day --limit 200 > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
    PROCESSED=$((PROCESSED + ${#BATCH_CODES[@]}))
fi

echo ""
echo "=== Step 3: Parse and update ccass.json ==="
python -c "
import json, re, os, glob

temp_dir = r'$TEMP_DIR'
ccass_path = r'$CCASS_JSON'

# Load ccass
with open(ccass_path) as f:
    data = json.load(f)

stock_map = {s['c']: s for s in data['stocks']}

# Parse all batch files
batch_files = sorted(glob.glob(os.path.join(temp_dir, 'batch_*.txt')))
print(f'Parsing {len(batch_files)} batch files...')

filled = 0
failed = 0

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
    
    # Compute deltas for each stock
    for code, rows in result.items():
        s = stock_map.get(code)
        if not s or not rows:
            continue
        
        latest_close = rows[0]['close']
        if latest_close is None:
            continue
        
        # d5, d20, d60, d120
        for n, key in [(5, 'd5'), (20, 'd20'), (60, 'd60'), (120, 'd120')]:
            if s.get(key) is not None:
                continue  # already filled
            if len(rows) > n:
                past = rows[n]['close']
                if past and past != 0:
                    s[key] = round((latest_close - past) / past, 4)
        
        # yo: 2026 first trading day open
        if s.get('yo') is None or s.get('yo') == 0:
            d2026 = [r for r in rows if r['date'].startswith('2026')]
            if d2026:
                d2026.sort(key=lambda r: r['date'])
                yo_open = d2026[0]['open']
                if yo_open and yo_open > 0:
                    s['yo'] = yo_open
        
        filled += 1
    
    # Count failed (codes in batch but not in result)
    failed += len([c for c in stock_map if stock_map[c].get('d60') is None])

# Save
tmp = ccass_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, ensure_ascii=False)
os.replace(tmp, ccass_path)

# Stats
d60_done = sum(1 for s in data['stocks'] if s.get('d60') is not None)
d120_done = sum(1 for s in data['stocks'] if s.get('d120') is not None)
yo_done = sum(1 for s in data['stocks'] if s.get('yo') is not None and s.get('yo') != 0)
total = len(data['stocks'])
print(f'DONE. d60: {d60_done}/{total}, d120: {d120_done}/{total}, yo: {yo_done}/{total}')
print(f'Filled this run: {filled}')
print(f'File saved.')
"

# Cleanup
echo ""
echo "=== Temp files kept at: $TEMP_DIR ==="
echo "Done!"
