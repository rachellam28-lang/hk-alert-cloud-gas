#!/usr/bin/env python3
"""v11: Pattern-based extraction — find any 'X Securities/Capital Limited' near 'Placing Agent'"""
import json, os, re, requests, pymupdf, sys, time
sys.path.insert(0, '/tmp/hkex-filing-scraper/src')
from hkex_scraper.api import fetch_chunk_via_api

p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
F = 'data/placements_enriched.json'
UA = 'Mozilla/5.0'

NEEDS_KW = ['配售', '供股', '先舊後新']
needs = [(i, x) for i, x in enumerate(p)
         if not x.get('placing_agent')
         and any(k in x.get('method', '') for k in NEEDS_KW)]
print(f'{len(needs)} events to process')

s = requests.Session()
s.headers.update({'User-Agent': UA})
found = 0

# Patterns for extracting agent names from text
# Must contain a securities/capital/bank keyword
AGENT_RE = re.compile(
    r'(?:(?:Sole|Joint)\s+)?(?:Placing\s+Agent|Global\s+Coordinator|Bookrunner|Lead\s+Manager|Underwriter)s?\s*:?\s*'
    r'([A-Z][A-Za-z\s&.,()\-]{5,60}'
    r'(?:Securities|Capital|Finance|Bank|Asia|International|Group|Partners|Wealth|Asset\s+Management)'
    r'(?:\s+(?:Limited|Ltd|Co\.|Company|Corporation|Inc\.?|PLC|Group|Holdings|Partners))?)',
    re.IGNORECASE
)

# Also try the reverse: "appointed X as placing agent"
APPOINTED_RE = re.compile(
    r'(?:appointed|appoints?|engaged?|engages?)\s+'
    r'([A-Z][A-Za-z\s&.,()\-]{5,60}'
    r'(?:Securities|Capital|Finance|Bank|Asia|International|Group|Partners|Wealth|Asset\s+Management)'
    r'(?:\s+(?:Limited|Ltd|Co\.|Company|Corporation|Inc\.?|PLC|Group|Holdings|Partners))?)'
    r'\s+as\s+(?:the\s+)?(?:sole\s+)?(?:placing\s+agent|global\s+coordinator|bookrunner|lead\s+manager|underwriter)',
    re.IGNORECASE
)

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

    full_text = ' '.join(doc[pg].get_text() for pg in range(doc.page_count))
    doc.close()

    agent = None

    # Try pattern matches
    for m in AGENT_RE.finditer(full_text):
        candidate = m.group(1).strip()
        candidate = re.sub(r'\s+', ' ', candidate).strip('.,;: ')
        if 8 < len(candidate) < 70 and name not in candidate:
            # Common garbage filters
            cl = candidate.lower()
            if any(g in cl for g in ['hong kong exch', 'the stock exch', 'securities and futures',
                                       'howsoever', 'reliance', 'disclaim', 'pursuant',
                                       'reference is made', 'announcement', 'the board',
                                       'the company', 'the group', 'the placing', 'general mandate',
                                       'shareholder', 'placing agent to', 'of placing']):
                continue
            agent = candidate
            break

    if not agent:
        for m in APPOINTED_RE.finditer(full_text):
            candidate = m.group(1).strip()
            candidate = re.sub(r'\s+', ' ', candidate).strip('.,;: ')
            if 8 < len(candidate) < 70 and name not in candidate:
                cl = candidate.lower()
                if any(g in cl for g in ['hong kong exch', 'the stock exch', 'howsoever',
                                           'reliance', 'reference is made']):
                    continue
                agent = candidate
                break

    if agent:
        # Clean prefix garbage
        agent = re.sub(r'^(?:Sole|Joint)\s+(?:Placing\s+Agent|Global\s+Coordinator)\s+', '', agent, flags=re.I)
        agent = re.sub(r'^Placing\s+Agent\s+', '', agent, flags=re.I)
        agent = agent.strip()
        if 8 < len(agent) < 70:
            p[orig_i]['placing_agent'] = agent
            found += 1
            print(f'[{idx+1}/{len(needs)}] {code} {name} → {agent[:55]}')

    if (idx + 1) % 20 == 0:
        tmp = F + '.tmp'
        json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        os.replace(tmp, F)
        print(f'  [Saved: {found}]')

tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nDone: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
