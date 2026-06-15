#!/bin/bash
# Fetch 5-year Free Cash Flow trend using westock finance
# Saves to ccass.json as fcf5y array + latest fcf

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOLDINGS_JSON="$(cygpath -w "$PROJECT_DIR/holdings.json")"
PROJECT_DIR_WIN="$(cygpath -w "$PROJECT_DIR")"
TEMP_DIR="$(cygpath -w "$(mktemp -d)")"
BATCH_SIZE=20

mkdir -p "$TEMP_DIR"

echo "=== Step 1: Get all stock codes ==="
python -c "
import json
with open(r'$HOLDINGS_JSON') as f:
    data = json.load(f)
codes = [s['c'] for s in data['stocks']]
with open(r'$TEMP_DIR/codes.txt', 'w') as f:
    f.write('\n'.join(codes))
print(f'{len(codes)} codes')
"

echo "=== Step 2: Fetch 20 periods cash flow ==="
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
        npx -y westock-data-clawhub@1.0.4 finance "$CODE_STR" --type xjll --num 20 > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
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
    npx -y westock-data-clawhub@1.0.4 finance "$CODE_STR" --type xjll --num 20 > "$TEMP_DIR/batch_${BATCH_NUM}.txt" 2>&1
    echo "OK"
fi

echo "=== Step 3: Parse 5-year FCF trend ==="
python -c "
import json, re, os, glob

project_dir = r'$PROJECT_DIR_WIN'
temp_dir = r'$TEMP_DIR'

with open(os.path.join(project_dir, 'holdings.json')) as f:
    data = json.load(f)
stock_map = {s['c']: s for s in data['stocks']}

batch_files = sorted(glob.glob(os.path.join(temp_dir, 'batch_*.txt')))
print(f'Parsing {len(batch_files)} files...')

# Collect all annual reports per stock
annual_data = {}  # code -> [{year, cfo, capex, fcf}]

for bf in batch_files:
    with open(bf) as f:
        text = f.read()
    
    # Find column indices from header
    cfo_idx = 7  # default from earlier testing
    capex_idx = 25
    date_idx = 2
    report_idx = 26
    
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('| symbol |'):
            cols = [c.strip() for c in line.split('|')]
            for i, c in enumerate(cols):
                if c == 'CFO': cfo_idx = i
                if c == 'Purcapitalassents': capex_idx = i
                if c == 'EndDate' or c == '_date': date_idx = i
                if c == 'ReportType': report_idx = i
            break
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('[Batch]') or line.startswith('| ---') or line.startswith('| symbol'):
            continue
        cols = [c.strip() for c in line.split('|')]
        max_idx = max(cfo_idx, capex_idx, report_idx)
        if len(cols) <= max_idx:
            continue
        
        m = re.match(r'hk(\d{5})', cols[1]) if len(cols) > 1 else None
        if not m:
            continue
        code = m.group(1)
        
        report_type = cols[report_idx] if len(cols) > report_idx else ''
        if '年度' not in report_type:
            continue
        
        try:
            date_str = cols[date_idx] if len(cols) > date_idx else ''
            if not date_str.startswith('20'):
                continue
            year = int(date_str[:4])
            
            cfo_str = cols[cfo_idx] if len(cols) > cfo_idx else '-'
            capex_str = cols[capex_idx] if len(cols) > capex_idx else '-'
            if not cfo_str or cfo_str == '-' or cfo_str == '':
                continue
            
            cfo = float(cfo_str)
            capex = abs(float(capex_str)) if capex_str and capex_str != '-' else 0
            fcf = cfo - capex
            
            if code not in annual_data:
                annual_data[code] = []
            annual_data[code].append({'year': year, 'cfo': cfo, 'capex': capex, 'fcf': fcf})
        except:
            continue

# For each stock, take last 5 years, compute trend
updated = 0
for code, years in annual_data.items():
    s = stock_map.get(code)
    if not s:
        continue
    
    # Sort by year desc, take last 5
    years.sort(key=lambda x: -x['year'])
    last5 = years[:5]
    last5.sort(key=lambda x: x['year'])  # ascending for trend
    
    if len(last5) < 2:
        continue
    
    latest = last5[-1]['fcf']
    oldest = last5[0]['fcf']
    
    # Store 5-year data
    fcf5y = [{'y': y['year'], 'fcf': round(y['fcf']/1e8, 1), 'cfo': round(y['cfo']/1e8, 1), 'capex': round(y['capex']/1e8, 1)} for y in last5]
    s['fcf5y'] = fcf5y
    s['fcf'] = round(latest / 1e8, 1)
    
    # Trend: +1 growing, -1 declining, 0 flat (using first vs last)
    if oldest > 0 and latest / oldest > 1.1:
        s['fcf_trend'] = 1   # growing >10%
    elif oldest > 0 and latest / oldest < 0.9:
        s['fcf_trend'] = -1  # declining >10%
    else:
        s['fcf_trend'] = 0   # flat
    
    updated += 1

# Save
tmp = os.path.join(project_dir, 'holdings.json') + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, ensure_ascii=False)
os.replace(tmp, os.path.join(project_dir, 'holdings.json'))

print(f'Updated {updated} stocks with 5-year FCF trend')

# Show samples
for code in ['00700', '00005', '09988']:
    s = stock_map.get(code, {})
    fcf5y = s.get('fcf5y', [])
    if fcf5y:
        trend = '↗' if s.get('fcf_trend')==1 else ('↘' if s.get('fcf_trend')==-1 else '→')
        fcf_str = ' → '.join([f\"{y['y']}:{y['fcf']:.0f}億\" for y in fcf5y])
        print(f'{code} {s.get(\"n\",\"?\")} {trend}: {fcf_str}')
"
echo "Done!"
