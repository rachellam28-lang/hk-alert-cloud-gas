#!/usr/bin/env python3
"""Text-only PDF extraction for LLM analysis — no OCR, fast."""
import json, os, requests, pymupdf, sys
sys.path.insert(0, '/tmp/hkex-filing-scraper/src')
from hkex_scraper.api import fetch_chunk_via_api

p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
UA = 'Mozilla/5.0'

NEEDS_KW = ['配售', '供股', '先舊後新']
SKIP_KW = ['代價發行']
needs = [(i, x) for i, x in enumerate(p)
         if not x.get('placing_agent')
         and any(k in x.get('method', '') for k in NEEDS_KW)
         and not any(k in x.get('method', '') for k in SKIP_KW)]

print(f'{len(needs)} events to extract')

s = requests.Session()
s.headers.update({'User-Agent': UA})
extracts = []

for idx, (orig_i, x) in enumerate(needs):
    code = x['code']
    name = x['name']
    date_str = x['date']
    url = x.get('pdf_url')

    if not url:
        try:
            dd, mm, yyyy = date_str.split('/')
            filings = fetch_chunk_via_api(s, f'{yyyy}{mm}{dd}', f'{yyyy}{mm}{dd}', max_records=3000)
            sf = [f for f in filings if f['stockCode'] == code or f['stockCode'] == code.lstrip('0')]
            pk = ['PLACING', 'PLACEMENT', 'RIGHTS', 'MANDATE', '配售', '供股', 'SUBSCRIPTION']
            pf = [f for f in sf if any(k in f['title'].upper() for k in pk)]
            if pf:
                url = pf[0]['link']
        except:
            pass

    text = ''
    if url:
        try:
            resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
            doc = pymupdf.open(stream=resp.content, filetype='pdf')
            text = ' '.join(doc[pg].get_text() for pg in range(min(doc.page_count, 15)))
            doc.close()
        except:
            pass

    extracts.append({
        'idx': orig_i,
        'code': code,
        'name': name,
        'date': date_str,
        'method': x.get('method', ''),
        'text': text[:3000],
        'url': url or '',
    })
    
    status = 'ok' if text else 'no-text'
    if (idx + 1) % 50 == 0 or idx == len(needs) - 1:
        json.dump(extracts, open('data/extracts_for_llm.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'[{idx+1}/{len(needs)}] Saved {len(extracts)} extracts')
    elif (idx + 1) % 10 == 0:
        print(f'[{idx+1}/{len(needs)}] ...')
    elif (idx + 1) <= 5:
        print(f'[{idx+1}] {code} {name} {status}')

json.dump(extracts, open('data/extracts_for_llm.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\nDone: {len(extracts)} extracts saved')
print(f'With text: {sum(1 for e in extracts if e["text"])}')
print(f'No text: {sum(1 for e in extracts if not e["text"])}')
