#!/bin/bash
# Fetch HK fund flow for top stocks by market cap
# Usage: bash fetch_fundflow.sh

PROJECT_DIR="C:/Users/Administrator/Desktop/automatic/ccass-debug"
TEMP_DIR="C:/Users/Administrator/AppData/Local/Temp/fundflow"
BATCH_SIZE=30
TOP_N=500

rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

echo "=== Step 1: Get top $TOP_N stocks by market cap ==="
python -c "
import json
with open(r'$PROJECT_DIR/holdings.json') as f:
    data = json.load(f)

# Sort by market cap (mc) descending, take top N
stocks = sorted(data['stocks'], key=lambda s: s.get('mc') or 0, reverse=True)
top = stocks[:$TOP_N]
codes = [s['c'] for s in top]
print(f'Top stock: {top[0][\"c\"]} {top[0][\"n\"]} mc={top[0].get(\"mc\")}')

# Write codes to file
with open(r'$TEMP_DIR/codes.txt', 'w') as f:
    f.write('\n'.join(codes))
print(f'Written {len(codes)} codes')
"

TOTAL=$(wc -l < "$TEMP_DIR/codes.txt")
BATCHES=$(( (TOTAL + BATCH_SIZE - 1) / BATCH_SIZE ))
echo "Batches: $BATCHES × $BATCH_SIZE"

echo ""
echo "=== Step 2: Fetch hkfund in batches ==="

BATCH_CODES=()
BATCH_NUM=0

while IFS= read -r code; do
    BATCH_CODES+=("$code")
    if [ ${#BATCH_CODES[@]} -ge $BATCH_SIZE ]; then
        BATCH_NUM=$((BATCH_NUM + 1))
        CODE_STR=""
        for c in "${BATCH_CODES[@]}"; do
            [ -n "$CODE_STR" ] && CODE_STR="$CODE_STR,"
            CODE_STR="${CODE_STR}hk${c}"
        done
        echo -n "[$BATCH_NUM/$BATCHES] "
        npx -y westock-data-clawhub@1.0.4 hkfund "$CODE_STR" > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
        echo "OK"
        BATCH_CODES=()
        sleep 1
    fi
done < "$TEMP_DIR/codes.txt"

# Remaining
if [ ${#BATCH_CODES[@]} -gt 0 ]; then
    BATCH_NUM=$((BATCH_NUM + 1))
    CODE_STR=""
    for c in "${BATCH_CODES[@]}"; do
        [ -n "$CODE_STR" ] && CODE_STR="$CODE_STR,"
        CODE_STR="${CODE_STR}hk${c}"
    done
    echo -n "[$BATCH_NUM/$BATCHES] "
    npx -y westock-data-clawhub@1.0.4 hkfund "$CODE_STR" > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
    echo "OK"
fi

echo ""
echo "=== Step 3: Parse and save fundflow.json ==="
python -c "
import json, re, os, glob

project_dir = r'$PROJECT_DIR'
temp_dir = r'$TEMP_DIR'

# Parse all batch files
fundflow = {}

batch_files = sorted(glob.glob(os.path.join(temp_dir, 'batch_*.txt')))
print(f'Parsing {len(batch_files)} files...')

for bf in batch_files:
    with open(bf) as f:
        text = f.read()
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('[Batch]') or line.startswith('| ---') or line.startswith('| symbol |'):
            continue
        
        cols = [c.strip() for c in line.split('|')]
        if len(cols) < 18:
            continue
        
        sym_match = re.match(r'hk(\d{5})', cols[1]) if len(cols) > 1 else None
        if not sym_match:
            continue
        
        code = sym_match.group(1)
        try:
            # Parse LgtHoldInfo JSON (batch mode: cols[6])
            lgt_raw = cols[6] if len(cols) > 6 else '{}'
            lgt = {}
            try:
                lgt = json.loads(lgt_raw)
            except:
                pass
            
            entry = {
                'date': cols[5] if cols[5] != '-' else '',
                'main_in': float(cols[8]) if cols[8] and cols[8] != '-' else 0,
                'main_out': float(cols[10]) if cols[10] and cols[10] != '-' else 0,
                'main_net': float(cols[9]) if cols[9] and cols[9] != '-' else 0,
                'retail_in': float(cols[12]) if cols[12] and cols[12] != '-' else 0,
                'retail_out': float(cols[14]) if cols[14] and cols[14] != '-' else 0,
                'retail_net': float(cols[13]) if cols[13] and cols[13] != '-' else 0,
                'total_net': float(cols[19]) if cols[19] and cols[19] != '-' else 0,
                'short_amount': float(cols[16]) if cols[16] and cols[16] != '-' else 0,
                'short_ratio': float(cols[17]) if cols[17] and cols[17] != '-' else 0,
                'short_shares': float(cols[18]) if cols[18] and cols[18] != '-' else 0,
                'lgt_hold_ratio': float(lgt.get('LgtHoldRatio', 0)) if lgt else 0,
                'lgt_cap_chg_daily': float(lgt.get('LgtCapChgDaily', 0)) if lgt else 0,
                'lgt_share_chg_daily': float(lgt.get('LgtShareChgDaily', 0)) if lgt else 0,
            }
            fundflow[code] = entry
        except (ValueError, IndexError) as e:
            continue

print(f'Parsed {len(fundflow)} stocks')

# Sort lists for the dashboard
ranked_main_in = sorted(fundflow.items(), key=lambda x: x[1].get('main_net', 0), reverse=True)
ranked_main_out = sorted(fundflow.items(), key=lambda x: x[1].get('main_net', 0))
ranked_short = sorted(fundflow.items(), key=lambda x: x[1].get('short_ratio', 0), reverse=True)
ranked_sb = sorted(fundflow.items(), key=lambda x: abs(x[1].get('lgt_cap_chg_daily', 0)), reverse=True)

output = {
    'updated': fundflow.get(list(fundflow.keys())[0], {}).get('date', '') if fundflow else '',
    'top_main_in': [{'c': c, 'main_net': d['main_net'], 'main_in': d['main_in'], 'main_out': d['main_out'], 'total_net': d['total_net']} for c, d in ranked_main_in[:20]],
    'top_main_out': [{'c': c, 'main_net': d['main_net'], 'main_in': d['main_in'], 'main_out': d['main_out'], 'total_net': d['total_net']} for c, d in ranked_main_out[:20]],
    'top_short': [{'c': c, 'short_ratio': d['short_ratio'], 'short_amount': d['short_amount']} for c, d in ranked_short[:20]],
    'top_southbound': [{'c': c, 'lgt_hold_ratio': d['lgt_hold_ratio'], 'lgt_cap_chg_daily': d['lgt_cap_chg_daily'], 'lgt_share_chg_daily': d['lgt_share_chg_daily']} for c, d in ranked_sb[:20]],
    'all': fundflow
}

outfile = os.path.join(project_dir, 'data', 'fundflow.json')
os.makedirs(os.path.dirname(outfile), exist_ok=True)
with open(outfile, 'w') as f:
    json.dump(output, f, ensure_ascii=False)
print(f'Saved to {outfile}')
print(f'Top main_in: {[(c,d[\"main_net\"]) for c,d in ranked_main_in[:5]]}')
print(f'Top short: {[(c,d[\"short_ratio\"]) for c,d in ranked_short[:5]]}')
"

echo ""
echo "=== Done! ==="
