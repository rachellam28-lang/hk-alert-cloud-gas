#!/usr/bin/env python3
"""Scrape Webb-site CCASS pnotes for ALL dates, match against all CCASS events."""
import json, os, re, requests, time, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

BASE = "http://119.246.139.86:8080/Webb-site/ccass/pnotes_daily.asp"
F = 'data/placements_enriched.json'

# Load placements
p = json.load(open(F, encoding='utf-8'))

# Also check CCASS events DB
db = sqlite3.connect('ccass/holdings.db')
db.row_factory = sqlite3.Row

print("=== Step 1: Scrape Webb-site for ALL available dates ===")

# Try date range: last 2 years
start_date = datetime(2024, 6, 1)
end_date = datetime(2026, 6, 10)
current = start_date

vendor_map = defaultdict(list)  # (date, code) -> [vendors]
dates_with_data = 0
total_records = 0

while current <= end_date:
    d = current.strftime('%Y-%m-%d')
    url = f'{BASE}?d={d}'
    try:
        resp = requests.get(url, timeout=15)
        resp.encoding = 'utf-8'
        html = resp.text
    except:
        current += timedelta(days=1)
        continue
    
    # Skip if no table
    if '<table' not in html:
        current += timedelta(days=1)
        continue
    
    rows = re.findall(r'<tr>\s*<td[^>]*>\d+</td>(.*?)</tr>', html, re.DOTALL)
    if not rows:
        current += timedelta(days=1)
        continue
    
    dates_with_data += 1
    for row_html in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
        if len(cells) < 7:
            continue
        
        clean = []
        for c in cells:
            c = re.sub(r'<[^>]+>', '', c).strip()
            c = re.sub(r'\s+', ' ', c)
            clean.append(c)
        
        if len(clean) < 10:
            continue
        
        # Extract stock code
        code_match = re.search(r'(\d{4,5})', clean[0])
        if not code_match:
            continue
        code = code_match.group(1).zfill(5)
        
        # Vendor (last cell)
        vendor = clean[-1].strip()
        if not vendor or vendor in ['-', '—', '', ' ']:
            continue
        
        # Clean vendor: remove trailing (notes)
        vendor = re.sub(r'\s*[（(][^)）]*[）)]\s*$', '', vendor).strip()
        
        # Note date
        note_date = clean[3] if len(clean) > 3 else ''
        date_match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', note_date)
        if date_match:
            dd2, mm2, yyyy2 = date_match.groups()
            web_date = f'{yyyy2}-{mm2.zfill(2)}-{dd2.zfill(2)}'
        else:
            web_date = d
        
        vendor_map[(web_date, code)].append(vendor)
        total_records += 1
    
    if dates_with_data % 30 == 0:
        print(f'  {d}: {dates_with_data} dates with data, {total_records} records')
    
    current += timedelta(days=1)
    time.sleep(0.15)

print(f'\nScraped: {dates_with_data} dates, {total_records} total records')
print(f'Unique (date,code) pairs: {len(vendor_map)}')

# Save vendor map
json.dump({f'{d}|{c}': v for (d,c), v in vendor_map.items()}, 
          open('data/webb_vendors.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

print("\n=== Step 2: Match against placements_enriched.json ===")
found = 0
for i, x in enumerate(p):
    if x.get('placing_agent'):
        continue
    code = x['code']
    try:
        dd, mm, yyyy = x['date'].split('/')
        ev_date = f'{yyyy}-{mm}-{dd}'
    except:
        continue
    
    # Check exact date + ±1 day
    for offset in [0, -1, 1]:
        check_date = (datetime.strptime(ev_date, '%Y-%m-%d') + timedelta(days=offset)).strftime('%Y-%m-%d')
        key = (check_date, code)
        if key in vendor_map and vendor_map[key]:
            # Take first vendor
            vendor = vendor_map[key][0]
            # Skip if it's just the company name
            if x['name'] and len(x['name']) > 3 and x['name'] in vendor:
                continue
            p[i]['placing_agent'] = vendor
            found += 1
            print(f'  {code} {x["name"]} → {vendor[:50]}')
            break

# Save
tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nNew from Webb: {found}')
print(f'Total agents: {wa}/402 ({wa/402*100:.1f}%)')

# Also check if there are CCASS events NOT in placements
print("\n=== Step 3: Cross-check CCASS events DB ===")
db_events = db.execute('SELECT * FROM ccass_events').fetchall()
print(f'CCASS events in DB: {len(db_events)}')

# Check which codes have events in DB but not in placements
db_codes = set(str(r['stock_code']).zfill(5) for r in db_events if r['stock_code'])
p_codes = set(x['code'] for x in p)
new_codes = db_codes - p_codes
if new_codes:
    print(f'Codes in DB but not in placements: {len(new_codes)}')
    for c in sorted(new_codes)[:10]:
        print(f'  {c}')
