#!/usr/bin/env python3
"""Enrich placements with westock kline data for market price context"""
import json, subprocess, sys, os, re
from datetime import datetime

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    placements = json.load(f)

# Get unique codes sorted by total amount
code_amounts = {}
for p in placements:
    code = p['code']
    code_amounts[code] = code_amounts.get(code, 0) + p['amount_num']

top_codes = sorted(code_amounts.items(), key=lambda x: x[1], reverse=True)[:30]
codes_list = [c[0] for c in top_codes]

print(f"Fetching kline for {len(codes_list)} stocks...")

price_cache = {}
WESTOCK = r'C:\Users\Administrator\AppData\Roaming\npm\westock-data.cmd'

for i, code in enumerate(codes_list):
    try:
        cmd = f'"{WESTOCK}" kline hk{code} --period day --limit 200'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        text = result.stdout
        
        # westock-data outputs markdown table with | separator
        klines = []
        for line in text.split('\n'):
            line = line.strip()
            if not line.startswith('|') or '---' in line or 'date' in line.lower():
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 5:
                date_str = parts[0]
                try:
                    close_val = float(parts[4].replace(',', ''))
                    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                        klines.append({'date': date_str, 'close': close_val})
                except:
                    pass
        
        if klines:
            price_cache[code] = klines
            print(f"  [{i+1}/{len(codes_list)}] {code}: {len(klines)} days")
        else:
            print(f"  [{i+1}/{len(codes_list)}] {code}: NO KLINES (output: {text[:100]})")
    except Exception as e:
        print(f"  [{i+1}/{len(codes_list)}] {code}: ERROR {e}")

# Apply market prices
enriched = 0
for p in placements:
    code = p['code']
    if code not in price_cache:
        continue
    event_date = datetime.strptime(p['date_parsed'], '%Y-%m-%d')
    klines = price_cache[code]
    
    # Find closest close price before event date
    best_close = 0
    for k in klines:
        if k['date'] <= event_date.strftime('%Y-%m-%d') and k['close'] > 0:
            best_close = k['close']
    
    if best_close > 0:
        p['market_price'] = best_close
        if p['price_num'] > 0 and best_close > 0:
            p['discount_pct'] = round((p['price_num'] / best_close - 1) * 100, 1)
        enriched += 1

print(f"\nEnriched {enriched} events with market prices")

# Save
with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(placements, f, ensure_ascii=False, indent=2)
print("Saved")
