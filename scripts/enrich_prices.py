#!/usr/bin/env python3
"""Batch price enrichment — fixed parser for batch mode output"""
import json, subprocess, re
from datetime import datetime

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    placements = json.load(f)

all_codes = sorted(set(p['code'] for p in placements))
print(f"Total unique stocks: {len(all_codes)}")

BATCH_SIZE = 15
batches = [all_codes[i:i+BATCH_SIZE] for i in range(0, len(all_codes), BATCH_SIZE)]
print(f"Batches: {len(batches)}")

price_cache = {}
WESTOCK = 'westock-data-clawhub.cmd'

for bi, batch in enumerate(batches):
    codes_str = ','.join(f'hk{c}' for c in batch)
    try:
        result = subprocess.run(
            [WESTOCK, 'kline', codes_str, '--period', 'day', '--limit', '200'],
            capture_output=True, timeout=90
        )
        text = None
        for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try: text = result.stdout.decode(enc); break
            except: continue
        if not text: continue
        
        for line in text.split('\n'):
            line = line.strip()
            if not line.startswith('|') or '---' in line or 'symbol' in line.lower():
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) < 5: continue
            
            # Batch mode: parts[0]=hkXXXXX, parts[1]=date, parts[3]=close(last)
            code_match = re.match(r'hk(\d{5})', parts[0])
            if not code_match: continue
            code = code_match.group(1)
            date_str = parts[1]
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_str): continue
            
            try:
                close_val = float(parts[3].replace(',', ''))
                if code not in price_cache:
                    price_cache[code] = []
                price_cache[code].append({'date': date_str, 'close': close_val})
            except: pass
        
    except Exception as e:
        pass
    
    if (bi+1) % 5 == 0:
        print(f"  [{bi+1}/{len(batches)}] {len(price_cache)} stocks")

# Sort klines by date
for code in price_cache:
    price_cache[code].sort(key=lambda k: k['date'])

print(f"\nKlines: {len(price_cache)}/{len(all_codes)} stocks, {sum(len(v) for v in price_cache.values())} total rows")

# Apply
enriched = 0
for p in placements:
    code = p['code']
    if code not in price_cache: continue
    event_date = datetime.strptime(p['date_parsed'], '%Y-%m-%d')
    klines = price_cache[code]
    event_str = event_date.strftime('%Y-%m-%d')
    
    prices_before = [k['close'] for k in klines if k['date'] <= event_str and k['close'] > 0]
    if prices_before:
        p['market_price'] = prices_before[-1]
        if p['price_num'] > 0 and p['market_price'] > 0:
            p['discount_pct'] = round((p['price_num'] / p['market_price'] - 1) * 100, 1)
        enriched += 1

print(f"Enriched {enriched} events with market prices")

with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(placements, f, ensure_ascii=False, indent=2)
print("Saved")
