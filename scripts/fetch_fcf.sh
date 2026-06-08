#!/bin/bash
# Fetch Free Cash Flow for top stocks using westock finance (xjll = cash flow statement)
# Saves to ccass.json as 'fcf' field

PROJECT_DIR="C:/Users/Administrator/Desktop/automatic/ccass-debug"
TEMP_DIR="C:/Users/Administrator/AppData/Local/Temp/fcf_fill"
BATCH_SIZE=30
TOP_N=500

rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

echo "=== Step 1: Get top $TOP_N stocks by market cap ==="
python -c "
import json
with open(r'$PROJECT_DIR/ccass.json') as f:
    data = json.load(f)
stocks = sorted(data['stocks'], key=lambda s: s.get('mc') or 0, reverse=True)
top = stocks[:$TOP_N]
codes = [s['c'] for s in top]
with open(r'$TEMP_DIR/codes.txt', 'w') as f:
    f.write('\n'.join(codes))
print(f'{len(codes)} codes')
"

echo "=== Step 2: Fetch cash flow in batches ==="
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
        echo -n "[$BATCH_NUM] "
        npx -y westock-data-clawhub@1.0.4 finance "$CODE_STR" --type xjll --num 1 > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
        echo "OK"
        BATCH_CODES=()
        sleep 1
    fi
done < "$TEMP_DIR/codes.txt"
if [ ${#BATCH_CODES[@]} -gt 0 ]; then
    BATCH_NUM=$((BATCH_NUM + 1))
    CODE_STR=""
    for c in "${BATCH_CODES[@]}"; do
        [ -n "$CODE_STR" ] && CODE_STR="$CODE_STR,"
        CODE_STR="${CODE_STR}hk${c}"
    done
    echo -n "[$BATCH_NUM] "
    npx -y westock-data-clawhub@1.0.4 finance "$CODE_STR" --type xjll --num 1 > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
    echo "OK"
fi

echo "=== Step 3: Parse and compute FCF ==="
python -c "
import json, re, os, glob

project_dir = r'$PROJECT_DIR'
temp_dir = r'$TEMP_DIR'

with open(os.path.join(project_dir, 'ccass.json')) as f:
    data = json.load(f)

stock_map = {s['c']: s for s in data['stocks']}

batch_files = sorted(glob.glob(os.path.join(temp_dir, 'batch_*.txt')))
print(f'Parsing {len(batch_files)} files...')

fcf_data = {}
for bf in batch_files:
    with open(bf) as f:
        text = f.read()
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('[Batch]') or line.startswith('| ---') or line.startswith('| symbol'):
            continue
        
        cols = [c.strip() for c in line.split('|')]
        if len(cols) < 26:
            continue
        
        m = re.match(r'hk(\d{5})', cols[1]) if len(cols) > 1 else None
        if not m:
            continue
        
        code = m.group(1)
        try:
            cfo = float(cols[6]) if cols[6] and cols[6] != '-' else 0
            capex = float(cols[24]) if cols[24] and cols[24] != '-' else 0
            report = cols[25] if len(cols) > 25 else ''
            unit = cols[12] if len(cols) > 12 else '港元'
            
            # Only use annual reports
            if '年度' not in report and '年報' not in report:
                continue
            
            fcf = cfo - abs(capex)  # CapEx is usually negative or positive
            
            fcf_data[code] = {
                'cfo': cfo,
                'capex': abs(capex),
                'fcf': fcf,
                'unit': unit,
                'report': report.replace('年度报告', '年報')
            }
        except (ValueError, IndexError):
            continue

print(f'Parsed FCF for {len(fcf_data)} stocks')

# Write to ccass.json
updated = 0
for code, fcf in fcf_data.items():
    s = stock_map.get(code)
    if s:
        # Store FCF in billions for display
        fcf_b = fcf['fcf'] / 1e8
        s['fcf'] = round(fcf_b, 1)
        updated += 1

# Save
tmp = os.path.join(project_dir, 'ccass.json') + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, ensure_ascii=False)
os.replace(tmp, os.path.join(project_dir, 'ccass.json'))

# Also save detailed FCF file
with open(os.path.join(project_dir, 'data', 'fcf.json'), 'w') as f:
    json.dump(fcf_data, f, ensure_ascii=False)

print(f'Updated {updated} stocks in ccass.json')
print(f'Saved to data/fcf.json')

# Show top FCF
ranked = sorted(fcf_data.items(), key=lambda x: x[1]['fcf'], reverse=True)
for code, d in ranked[:10]:
    s = stock_map.get(code, {})
    print(f\"  {code} {s.get('n','?')}: FCF={d['fcf']/1e8:.0f}億 (CFO={d['cfo']/1e8:.0f}億 - CapEx={d['capex']/1e8:.0f}億)\")
"

echo "=== Done! ==="
