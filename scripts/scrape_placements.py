#!/usr/bin/env python3
"""Scrape etnet 配股集資 page for rights issues and placements"""
import re, json, sys
from urllib.request import urlopen, Request

all_rows = []
headers = {'User-Agent': 'Mozilla/5.0'}

for page in range(1, 11):
    url = f"https://www.etnet.com.hk/www/tc/stocks/ci_act_placing.php?page={page}"
    try:
        req = Request(url, headers=headers)
        html = urlopen(req, timeout=15).read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Page {page}: ERROR {e}", file=sys.stderr)
        continue
    
    # Extract all td contents
    tds = re.findall(r'<td[^>]*>(.*?)</td>', html, re.DOTALL)
    
    # Clean: remove HTML tags, &nbsp;, and whitespace
    cleaned = []
    for td in tds:
        text = re.sub(r'<[^>]+>', ' ', td).strip()
        text = text.replace('&nbsp;', '').strip()
        if text:
            cleaned.append(text)
    
    # Find where the data table starts (look for first date pattern dd/mm/yyyy)
    start = 0
    for i, c in enumerate(cleaned):
        if re.match(r'\d{2}/\d{2}/\d{4}', c):
            start = i
            break
    
    # Group into records of 9 fields
    data_slice = cleaned[start:]
    record_count = 0
    for i in range(0, len(data_slice) - 8, 9):
        row = {
            'date': data_slice[i],
            'code': data_slice[i+1],
            'name': data_slice[i+2],
            'shares': data_slice[i+3],
            'price': data_slice[i+4],
            'amount': data_slice[i+5],
            'type': data_slice[i+6],
            'pct_shares': data_slice[i+7],
            'method': data_slice[i+8],
        }
        # Validate: code should be 5 digits
        if not re.match(r'\d{5}', row['code']):
            break
        all_rows.append(row)
        record_count += 1
    
    print(f"Page {page}: {record_count} rows (total: {len(all_rows)})", file=sys.stderr)

outpath = 'data/placements.json'
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(all_rows, f, ensure_ascii=False, indent=2)

print(f"Saved {len(all_rows)} rows to {outpath}")

# Stats
rights = [r for r in all_rows if '供股' in r.get('method','')]
cb = [r for r in all_rows if '換股' in r.get('type','') or '債券' in r.get('type','')]
print(f"供股: {len(rights)}, CB: {len(cb)}, Total: {len(all_rows)}")
if all_rows:
    print(f"Date range: {all_rows[-1]['date']} to {all_rows[0]['date']}")
print(f"Unique stocks: {len(set(r['code'] for r in all_rows))}")
