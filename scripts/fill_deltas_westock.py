#!/usr/bin/env python3
"""
Fill d5/d20/d60/d120/yo in ccass.json using westock-data kline.
Batch-fetches 200-day kline for all stocks, computes price deltas.
"""

import json
import subprocess
import sys
import time
import re
from pathlib import Path

CCASS_JSON = Path(r'C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass.json')
BATCH_SIZE = 20  # stocks per npx call
DELAY = 2  # seconds between batches
KLINE_DAYS = 200

def load_ccass():
    with open(CCASS_JSON) as f:
        return json.load(f)

def save_ccass(data):
    tmp = str(CCASS_JSON) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False)
    Path(tmp).replace(CCASS_JSON)

def fetch_batch_kline(codes):
    """Fetch kline for a batch of stock codes. Returns raw stdout text."""
    code_str = ','.join(f'hk{code}' for code in codes)
    cmd = f'npx -y westock-data-clawhub@1.0.4 kline {code_str} --period day --limit {KLINE_DAYS}'
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, shell=True)
        return r.stdout
    except subprocess.TimeoutExpired:
        print(f'  TIMEOUT batch: {len(codes)} codes')
        return ''
    except Exception as e:
        print(f'  ERROR batch: {e}')
        return ''

def parse_batch_output(text):
    """Parse westock batch kline output into dict[code] -> list of {date, open, close}."""
    result = {}
    current_code = None
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('[Batch]') or line.startswith('| ---'):
            continue
        if line.startswith('| symbol |'):
            continue
        
        # Data row: | hk00700 | 2026-06-08 | 447.80 | 446.40 | ...
        cols = [c.strip() for c in line.split('|')]
        if len(cols) < 6:
            continue
        
        # Check if first col is a stock symbol
        sym_match = re.match(r'hk(\d{5})', cols[1]) if len(cols) > 1 else None
        if sym_match:
            current_code = sym_match.group(1)
            # cols: ['', 'hk00700', 'date', 'open', 'last', 'high', 'low', ...]
            try:
                row = {
                    'date': cols[2],
                    'open': float(cols[3]) if cols[3] else None,
                    'close': float(cols[4]) if cols[4] else None,
                }
                if row['close'] is not None:
                    if current_code not in result:
                        result[current_code] = []
                    result[current_code].append(row)
            except (ValueError, IndexError):
                continue
    
    return result

def compute_deltas(kline_rows):
    """From kline rows (newest first), compute d5, d20, d60, d120, yo."""
    if not kline_rows:
        return None
    
    latest_close = kline_rows[0]['close']
    
    deltas = {}
    
    # d5, d20, d60, d120: compare latest close vs close N trading days ago
    for n, key in [(5, 'd5'), (20, 'd20'), (60, 'd60'), (120, 'd120')]:
        if len(kline_rows) > n:
            past_close = kline_rows[n]['close']
            if past_close and past_close != 0:
                deltas[key] = round((latest_close - past_close) / past_close, 4)
            else:
                deltas[key] = None
        else:
            deltas[key] = None
    
    # yo: 2026 first trading day open
    rows_2026 = [r for r in kline_rows if r['date'].startswith('2026')]
    if rows_2026:
        rows_2026.sort(key=lambda r: r['date'])
        yo_open = rows_2026[0]['open']
        deltas['yo'] = yo_open if yo_open else None
        # yo_pct
        if yo_open and yo_open != 0:
            deltas['yo_pct'] = round((latest_close - yo_open) / yo_open, 4)
        else:
            deltas['yo_pct'] = None
    else:
        deltas['yo'] = None
        deltas['yo_pct'] = None
    
    return deltas

def main():
    print('Loading ccass.json...')
    data = load_ccass()
    stocks = data.get('stocks', [])
    
    if not stocks:
        print('No stocks in ccass.json!')
        return
    
    # Get all codes
    all_codes = [s['c'] for s in stocks]
    print(f'Total stocks: {len(all_codes)}')
    
    # Check which need filling
    needs_fill = []
    for s in stocks:
        if s.get('d60') is None or s.get('d120') is None:
            needs_fill.append(s['c'])
    
    print(f'Need d60/d120 fill: {len(needs_fill)}')
    
    if not needs_fill:
        print('Nothing to fill!')
        return
    
    # Build code -> stock map for quick update
    stock_map = {s['c']: s for s in stocks}
    
    # Process in batches
    total_batches = (len(needs_fill) + BATCH_SIZE - 1) // BATCH_SIZE
    processed = 0
    filled = 0
    failed = 0
    
    for i in range(0, len(needs_fill), BATCH_SIZE):
        batch = needs_fill[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f'\nBatch {batch_num}/{total_batches} ({len(batch)} codes): {batch[0]}...{batch[-1]}')
        
        text = fetch_batch_kline(batch)
        if not text:
            failed += len(batch)
            continue
        
        parsed = parse_batch_output(text)
        print(f'  Parsed: {len(parsed)} stocks')
        
        for code in batch:
            processed += 1
            if code in parsed and parsed[code]:
                deltas = compute_deltas(parsed[code])
                if deltas:
                    s = stock_map[code]
                    for k, v in deltas.items():
                        s[k] = v
                    filled += 1
                else:
                    failed += 1
            else:
                failed += 1
        
        # Save progress every 5 batches
        if batch_num % 5 == 0:
            print(f'  Saving progress... ({filled} filled, {failed} failed)')
            save_ccass(data)
        
        time.sleep(DELAY)
    
    # Final save
    print(f'\n=== FINAL ===')
    print(f'Processed: {processed}, Filled: {filled}, Failed: {failed}')
    save_ccass(data)
    print('Saved!')

if __name__ == '__main__':
    main()
