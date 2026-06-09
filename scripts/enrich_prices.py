#!/usr/bin/env python3
"""Enrich placements with westock kline data - encoding-safe version"""
import json, subprocess, sys, os, re
from datetime import datetime

with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    placements = json.load(f)

code_amounts = {}
for p in placements:
    code = p['code']
    code_amounts[code] = code_amounts.get(code, 0) + p['amount_num']

top_codes = sorted(code_amounts.items(), key=lambda x: x[1], reverse=True)[:50]
print(f"Fetching kline for {len(top_codes)} stocks...")

WESTOCK = r'westock-data-clawhub.cmd'

price_cache = {}
for i, (code, amt) in enumerate(top_codes):
    try:
        result = subprocess.run(
            [WESTOCK, 'kline', f'hk{code}', '--period', 'day', '--limit', '200'],
            capture_output=True, timeout=30
        )
        # Try UTF-8 first, then GBK
        text = None
        for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try:
                text = result.stdout.decode(enc)
                break
            except:
                continue
        if not text:
            continue
        
        klines = []
        for line in text.split('\n'):
            line = line.strip()
            if not line.startswith('|') or '---' in line:
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 5 and re.match(r'\d{4}-\d{2}-\d{2}', parts[0]):
                try:
                    close_val = float(parts[4].replace(',', ''))
                    klines.append({'date': parts[0], 'close': close_val})
                except:
                    pass
        
        if klines:
            price_cache[code] = klines
            if (i+1) % 10 == 0:
                print(f"  [{i+1}/{len(top_codes)}] {code}: {len(klines)} days")
    except Exception as e:
        print(f"  [{i+1}] {code}: ERR {e}")

print(f"\nGot klines for {len(price_cache)} stocks")

# Apply market prices
enriched = 0
for p in placements:
    code = p['code']
    if code not in price_cache:
        continue
    event_date = datetime.strptime(p['date_parsed'], '%Y-%m-%d')
    klines = price_cache[code]
    
    # Pre-event price: close price 5 trading days before event
    event_str = event_date.strftime('%Y-%m-%d')
    prices_before = [k['close'] for k in klines if k['date'] <= event_str and k['close'] > 0]
    
    if prices_before:
        p['market_price'] = prices_before[-1]  # closest price before event
        
        # Also get price 5, 20, 60 days before for trend
        if len(prices_before) >= 5:
            p['price_5d_ago'] = prices_before[-5]
        if len(prices_before) >= 20:
            p['price_20d_ago'] = prices_before[-20]
        
        # Post-event price (closest after)
        prices_after = [k['close'] for k in klines if k['date'] > event_str and k['close'] > 0]
        if len(prices_after) >= 1:
            p['price_post'] = prices_after[0]
        if len(prices_after) >= 5:
            p['price_5d_post'] = prices_after[min(4, len(prices_after)-1)]
        if len(prices_after) >= 20:
            p['price_20d_post'] = prices_after[min(19, len(prices_after)-1)]
        
        # Discount calculation
        if p['price_num'] > 0 and p['market_price'] > 0:
            p['discount_pct'] = round((p['price_num'] / p['market_price'] - 1) * 100, 1)
        
        enriched += 1

print(f"Enriched {enriched} events with market prices")

with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(placements, f, ensure_ascii=False, indent=2)
print("Saved")
