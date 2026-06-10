#!/usr/bin/env python3
"""Scrape Webb-site CCASS pnotes for placing agents (vendors)."""
import json, os, re, requests, time
from datetime import datetime, timedelta

BASE = "http://119.246.139.86:8080/Webb-site/ccass/pnotes_daily.asp"
p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
F = 'data/placements_enriched.json'

# Get date range from our data
dates = set()
for x in p:
    if not x.get('placing_agent') and any(k in x.get('method','') for k in ['配售','供股','先舊後新']):
        try:
            dd, mm, yyyy = x['date'].split('/')
            dates.add(f'{yyyy}-{mm}-{dd}')
        except:
            pass

dates = sorted(dates)
print(f'{len(dates)} unique dates to check')

found = 0
for d in dates:
    url = f'{BASE}?d={d}'
    try:
        resp = requests.get(url, timeout=15)
        html = resp.text
    except Exception as e:
        print(f'{d}: request failed ({e})')
        continue
    
    # Parse table rows
    rows = re.findall(r'<tr>\s*<td[^>]*>\d+</td>(.*?)</tr>', html, re.DOTALL)
    
    for row_html in rows:
        # Extract cells
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
        if len(cells) < 7:
            continue
        
        # Clean cell text
        clean_cells = []
        for c in cells:
            c = re.sub(r'<[^>]+>', '', c).strip()
            c = re.sub(r'\s+', ' ', c)
            clean_cells.append(c)
        
        if len(clean_cells) < 10:
            continue
        
        # Parse: [stock_link, name, type, note_date, ?, price, discount, shares, mkt_price, change, vendor]
        # Stock code is usually in cell[0] as number
        stock_code = re.search(r'(\d{4,5})', clean_cells[0])
        if not stock_code:
            continue
        code = stock_code.group(1).zfill(5)
        
        # Vendor is usually last cell
        vendor = clean_cells[-1].strip()
        if not vendor or vendor in ['-', '—', '']:
            continue
        if vendor.startswith('http') or vendor.startswith('&'):
            continue
        
        # Stock name
        name = re.sub(r'<[^>]+>', '', cells[1] if len(cells) > 1 else '').strip()
        name = re.sub(r'\s+', ' ', name)
        
        # Convert date: cells[3] is usually "d/m/yyyy"
        note_date = clean_cells[3] if len(clean_cells) > 3 else ''
        date_match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', note_date)
        if date_match:
            dd2, mm2, yyyy2 = date_match.groups()
            web_date = f'{yyyy2}-{mm2.zfill(2)}-{dd2.zfill(2)}'
        else:
            web_date = d
        
        # Match against our data
        for i, x in enumerate(p):
            if x.get('placing_agent'):
                continue
            if x['code'] != code:
                continue
            # Match by date
            try:
                dd3, mm3, yyyy3 = x['date'].split('/')
                ev_date = f'{yyyy3}-{mm3}-{dd3}'
            except:
                continue
            
            if ev_date != web_date and ev_date != d:
                # Try ±1 day tolerance
                d1 = datetime.strptime(ev_date, '%Y-%m-%d')
                d2 = datetime.strptime(web_date, '%Y-%m-%d')
                if abs((d1-d2).days) > 1:
                    continue
            
            if any(k in x.get('method','') for k in ['配售','供股','先舊後新']):
                if '代價發行' not in x.get('method',''):
                    p[i]['placing_agent'] = vendor
                    found += 1
                    print(f'{code} {name} → {vendor}')
                    break  # Only match first event

    time.sleep(0.3)  # Rate limit

# Save
tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)
wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nDone: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
