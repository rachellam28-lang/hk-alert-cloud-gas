#!/usr/bin/env python3
"""Full-text extraction + agent name search."""
import json, os, requests, pymupdf, re, sys
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

print(f'{len(needs)} events')

s = requests.Session()
s.headers.update({'User-Agent': UA})
found = 0

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
                x['pdf_url'] = url
        except:
            pass

    if not url:
        continue

    try:
        resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
    except:
        continue

    # Get ALL text from ALL pages
    full_text = ' '.join(doc[pg].get_text() for pg in range(doc.page_count))
    doc.close()

    # Search for agent name patterns
    # Pattern: "Placing Agent\nNAME" or "Placing Agent  NAME"
    agent = None
    
    # Look for "Placing Agent" followed by an uppercase name
    for m in re.finditer(r'Placing\s+Agent\s*\n?\s*([A-Z][A-Za-z\s&.,()\-]{8,60}?(?:Limited|Ltd|Securities|Capital|Finance|Bank|Asia|International|Group|Partners)\b)', full_text):
        candidate = m.group(1).strip()
        # Clean up
        candidate = re.sub(r'\s+', ' ', candidate)
        if len(candidate) > 8 and name not in candidate and 'hong kong exch' not in candidate.lower():
            agent = candidate
            break
    
    # Look for "Sole Placing Agent" or "Sole Global Coordinator" 
    if not agent:
        for m in re.finditer(r'(?:Sole|Joint)\s+(?:Placing\s+Agent|Global\s+Coordinator|Bookrunner|Lead\s+Manager)[\s\n]*:?\s*([A-Z][A-Za-z\s&.,()\-]{8,60}?(?:Limited|Ltd|Securities|Capital|Finance|Bank|Asia|International|Group|Partners)\b)', full_text):
            candidate = m.group(1).strip()
            candidate = re.sub(r'\s+', ' ', candidate)
            if len(candidate) > 8 and name not in candidate:
                agent = candidate
                break
    
    # Look for "appointed X as placing agent"
    if not agent:
        for m in re.finditer(r'(?:appointed|appoint|engage)\s+(?:the\s+)?([A-Z][A-Za-z\s&.,()\-]{8,60}?(?:Limited|Ltd|Securities|Capital|Finance|Bank|Asia|International|Group|Partners)\b)\s+as\s+(?:the\s+)?(?:placing\s+agent|sole\s+placing\s+agent)', full_text, re.I):
            candidate = m.group(1).strip()
            candidate = re.sub(r'\s+', ' ', candidate)
            if len(candidate) > 8 and name not in candidate:
                agent = candidate
                break

    if agent:
        p[orig_i]['placing_agent'] = agent
        found += 1
        print(f'[{idx+1}/{len(needs)}] {code} {name} → {agent[:60]}')
    
    if (idx + 1) % 30 == 0:
        tmp = 'data/placements_enriched.json.tmp'
        json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        os.replace(tmp, 'data/placements_enriched.json')
        print(f'  [Saved: {found}]')

tmp = 'data/placements_enriched.json.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, 'data/placements_enriched.json')

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nDone: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
