#!/usr/bin/env python3
"""Enrich placements data with price & shareholder info, build analysis page"""
import json, re, subprocess, sys, os
from datetime import datetime, timedelta

# Load placements
with open('data/placements.json', 'r', encoding='utf-8') as f:
    placements = json.load(f)

print(f"Loaded {len(placements)} events")

# ---- Phase 1: Basic enrichment ----
# Parse amounts to numeric for sorting
def parse_amount(s):
    """Parse HK amount string to float (HKD)"""
    s = s.replace('HKD', '').replace('USD', '').replace('RMB', '').replace(' ', '').strip()
    if s == '--' or not s:
        return 0
    multipliers = {'億': 1e8, '千萬': 1e7, '百萬': 1e6, '萬': 1e4}
    for unit, mult in multipliers.items():
        if unit in s:
            try:
                return float(s.replace(unit, '')) * mult
            except:
                return 0
    try:
        return float(s)
    except:
        return 0

def parse_pct(s):
    try:
        return float(s)
    except:
        return 0

def parse_price(s):
    """Parse price like 'HKD 0.190' or '--'"""
    s = s.replace('HKD', '').replace('USD', '').replace('RMB', '').strip()
    if s == '--' or not s:
        return 0
    try:
        return float(s)
    except:
        return 0

# Categorize by method
def categorize(method):
    if '供股' in method:
        return '供股'
    if '配售/發行' in method:
        return '配售'
    if '代價發行' in method:
        return '代價發行'
    if '先舊後新' in method:
        return '先舊後新'
    return '其他'

def extract_purpose(method):
    """Extract purpose from method string"""
    m = re.search(r'\((.+?)\)', method)
    if m:
        return m.group(1)[:80]
    return ''

def extract_ratio(method):
    """Extract ratio like 二供一 from rights issues"""
    m = re.search(r'([一二三四五六七八九十]+供[一二三四五六七八九十]+)', method)
    if m:
        return m.group(1)
    m = re.search(r'(\d+供\d+)', method)
    if m:
        return m.group(1)
    return ''

# Enrich
for p in placements:
    p['amount_num'] = parse_amount(p['amount'])
    p['price_num'] = parse_price(p['price'])
    p['pct_num'] = parse_pct(p['pct_shares'])
    p['category'] = categorize(p['method'])
    p['purpose'] = extract_purpose(p['method'])
    p['ratio'] = extract_ratio(p['method'])
    p['date_parsed'] = datetime.strptime(p['date'], '%d/%m/%Y')

# Sort by date desc
placements.sort(key=lambda x: x['date_parsed'], reverse=True)

# ---- Phase 2: Get price data for top stocks ----
# Get unique stock codes, prioritize by amount
top_stocks = sorted(set(p['code'] for p in placements if p['amount_num'] > 5e7), 
                    key=lambda c: sum(p['amount_num'] for p in placements if p['code'] == c), 
                    reverse=True)[:50]
print(f"Getting price data for {len(top_stocks)} top stocks...")

price_cache = {}
for code in top_stocks[:30]:  # Limit to 30 to avoid rate limits
    try:
        result = subprocess.run(
            ['npx', 'westock-data-clawhub', 'kline', f'hk{code}', '--period', 'day', '--limit', '200'],
            capture_output=True, text=True, timeout=30, cwd=os.getcwd()
        )
        # Parse the kline output
        text = result.stdout
        # Look for table data
        klines = []
        for line in text.split('\n'):
            parts = line.strip().split('|')
            if len(parts) >= 6:
                try:
                    date_str = parts[0].strip()
                    close_str = parts[4].strip() if len(parts) > 4 else ''
                    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                        klines.append({'date': date_str, 'close': float(close_str) if close_str else 0})
                except:
                    pass
        if klines:
            price_cache[code] = klines
            print(f"  {code}: {len(klines)} kline points")
    except Exception as e:
        print(f"  {code}: ERROR {e}")

# Enrich with market price at event date
def get_market_price(code, event_date, cache):
    if code not in cache:
        return 0
    klines = cache[code]
    # Find closest date before or on event date
    event_str = event_date.strftime('%Y-%m-%d')
    best = 0
    for k in klines:
        if k['date'] <= event_str and k['close'] > 0:
            best = k['close']
    return best

for p in placements:
    p['market_price'] = get_market_price(p['code'], p['date_parsed'], price_cache)
    if p['market_price'] > 0 and p['price_num'] > 0:
        p['discount_pct'] = round((p['price_num'] / p['market_price'] - 1) * 100, 1)
    else:
        p['discount_pct'] = None

# ---- Phase 3: Summary stats ----
cats = {}
for p in placements:
    cats[p['category']] = cats.get(p['category'], 0) + 1

total_amount = sum(p['amount_num'] for p in placements) / 1e8

print(f"\n===== SUMMARY =====")
print(f"Total events: {len(placements)}")
print(f"Categories: {cats}")
print(f"Total raised: {total_amount:.0f} 億 HKD")
print(f"Unique stocks: {len(set(p['code'] for p in placements))}")
print(f"Stocks with price data: {len(price_cache)}")

# Save enriched data
with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    # Convert datetime to string for JSON
    out = []
    for p in placements:
        p2 = dict(p)
        p2['date_parsed'] = p['date_parsed'].strftime('%Y-%m-%d')
        out.append(p2)
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\nSaved enriched data to data/placements_enriched.json")
