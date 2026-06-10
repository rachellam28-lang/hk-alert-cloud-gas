#!/usr/bin/env python3
"""Search Webb-site by stock code — fixed row parsing."""
import json, os, re, requests, time

p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
F = 'data/placements_enriched.json'

# First: rollback the garbage matches from previous run
for x in p:
    a = x.get('placing_agent', '')
    if a and re.match(r'^\d+', a) and ('W' in a or '萬' in a):
        x['placing_agent'] = None

missing = [x for i, x in enumerate(p) if not x.get('placing_agent')]
# Add index for writing back
for i, x in enumerate(p):
    x['_idx'] = i

print(f'{len(missing)} codes to search')

found = 0
for idx, x in enumerate(missing):
    code = x['code']
    url = f'http://119.246.139.86:8080/Webb-site/ccass/pnotes_daily.asp?s={code}'
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = 'utf-8'
        html = resp.text
    except:
        continue
    
    # Parse per-row: find all <tr> blocks
    rows = re.findall(r'<tr>(.*?)</tr>', html, re.DOTALL)
    for row_html in rows:
        # Get all colHide3 cells in THIS row
        col3 = re.findall(r'<td class="colHide3">([^<]*)</td>', row_html)
        if not col3:
            continue
        
        # Vendor is the LAST colHide3 in the row
        vendor = col3[-1].strip()
        if not vendor or vendor in ['-', '—', '', ' ', '&nbsp;']:
            continue
        if re.match(r'^\d+', vendor):
            continue  # Skip share amounts
        
        # Clean
        vendor = re.sub(r'\s*[（(][^)）]*[）)]\s*$', '', vendor).strip()
        vendor = re.sub(r'&nbsp;', '', vendor).strip()
        
        if len(vendor) < 3:
            continue
        
        # Multi-agent: take first
        if '、' in vendor:
            parts = [p.strip() for p in vendor.split('、') if len(p.strip()) > 3]
            vendor = parts[0] if parts else vendor
        
        # Get note date from same row
        dates_in_row = re.findall(r'(\d{1,2})/(\d{1,2})/(\d{4})', row_html)
        
        p[x['_idx']]['placing_agent'] = vendor
        found += 1
        
        if found <= 15 or vendor not in ['46800W', '2500W']:
            date_str = f' ({dates_in_row[0][0]}/{dates_in_row[0][1]}/{dates_in_row[0][2]})' if dates_in_row else ''
            print(f'{code} {x["name"]}{date_str} → {vendor}')
        break  # Only first matching row
    
    if (idx + 1) % 30 == 0:
        print(f'  [{idx+1}/{len(missing)}] found={found}')
    time.sleep(0.15)

# Clean up _idx
for x in p:
    x.pop('_idx', None)

tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)

wa = sum(1 for x in p if x.get('placing_agent'))
real = sum(1 for x in p if x.get('placing_agent') and x['placing_agent'] != '[代價發行]')
print(f'\nFound: {found} new')
print(f'Total: {wa}/402 ({wa/402*100:.1f}%) | Real agents: {real} | Missing: {402-wa}')
