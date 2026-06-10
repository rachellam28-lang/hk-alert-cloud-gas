#!/usr/bin/env python3
"""v8: Chase prior announcements for completion events."""
import json, os, re, requests, pymupdf, sys
sys.path.insert(0, '/tmp/hkex-filing-scraper/src')
from hkex_scraper.api import fetch_chunk_via_api

p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
F = 'data/placements_enriched.json'
UA = 'Mozilla/5.0'

NEEDS_KW = ['配售', '供股', '先舊後新']
SKIP_KW = ['代價發行']
needs = [(i, x) for i, x in enumerate(p)
         if not x.get('placing_agent')
         and any(k in x.get('method', '') for k in NEEDS_KW)
         and not any(k in x.get('method', '') for k in SKIP_KW)]

print(f'{len(needs)} events to process')

s = requests.Session()
s.headers.update({'User-Agent': UA})

# Agent extraction patterns
def extract_agent(text, name=''):
    """Extract placing agent from PDF text."""
    # Pattern 1: "Placing Agent\nNAME"
    for m in re.finditer(r'Placing\s+Agent\s*\n?\s*([A-Z][A-Za-z\s&.,()\-]{8,60}?(?:Limited|Ltd|Securities|Capital|Finance|Bank|Asia|International|Group|Partners)\b)', text):
        agent = re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(agent) > 8 and name not in agent and 'hong kong exch' not in agent.lower():
            return agent
    
    # Pattern 2: "Sole/Joint Placing Agent/Coordinator"
    for m in re.finditer(r'(?:Sole|Joint)\s+(?:Placing\s+Agent|Global\s+Coordinator|Bookrunner|Lead\s+Manager)[\s\n]*:?\s*([A-Z][A-Za-z\s&.,()\-]{8,60}?(?:Limited|Ltd|Securities|Capital|Finance|Bank|Asia|International|Group|Partners)\b)', text):
        agent = re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(agent) > 8 and name not in agent:
            return agent
    
    # Pattern 3: "appointed X as placing agent"
    for m in re.finditer(r'(?:appointed|appoint|engage)\s+(?:the\s+)?([A-Z][A-Za-z\s&.,()\-]{8,60}?(?:Limited|Ltd|Securities|Capital|Finance|Bank|Asia|International|Group|Partners)\b)\s+as\s+(?:the\s+)?(?:placing\s+agent|sole\s+placing\s+agent)', text, re.I):
        agent = re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(agent) > 8 and name not in agent:
            return agent
    
    # Pattern 4: Multi-agent format "BofA Securities   CICC   J.P. Morgan"
    for m in re.finditer(r'(?:Overall\s+Coordinators?|Placing\s+Agents?|Joint\s+Bookrunners?|Joint\s+Lead\s+Managers?)[\s\n,]*:?\s*([A-Z][A-Za-z\s&.,()\-.]{15,120})', text):
        agent_text = m.group(1).strip()
        # Check if it contains known securities firms
        if any(kw in agent_text.lower() for kw in ['securities', 'capital', 'bank', 'morgan', 'goldman', 'ubs', 'citi', 'bofa', 'cicc', 'j.p.']):
            return re.sub(r'\s{2,}', ', ', agent_text).strip()
    
    return None

found = 0
for idx, (orig_i, x) in enumerate(needs):
    code = x['code']
    name = x['name']
    date_str = x['date']
    url = x.get('pdf_url')
    agent = None

    # Step 1: Try current PDF first (full text)
    if url:
        try:
            resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
            doc = pymupdf.open(stream=resp.content, filetype='pdf')
            text = ' '.join(doc[pg].get_text() for pg in range(doc.page_count))
            doc.close()
            agent = extract_agent(text, name)
        except:
            pass

    # Step 2: If no agent AND text mentions "Completion" or "Reference is made" → chase prior announcement
    if not agent and url:
        try:
            resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
            doc = pymupdf.open(stream=resp.content, filetype='pdf')
            text = ' '.join(doc[pg].get_text() for pg in range(min(5, doc.page_count)))
            doc.close()
            
            tl = text.lower()
            is_completion = any(kw in tl for kw in ['completion of placing', 'completion of the placing',
                                                       'supplemental announcement', 'update on'])
            has_ref = 'reference is made to the announcement' in tl
            
            if is_completion or has_ref:
                # Search for prior announcement
                dd, mm, yyyy = date_str.split('/')
                # Search a window: current date ± 14 days
                from datetime import datetime, timedelta
                curr_date = datetime(int(yyyy), int(mm), int(dd))
                
                for days_back in range(1, 15):
                    prior_date = curr_date - timedelta(days=days_back)
                    pd_str = prior_date.strftime('%Y%m%d')
                    try:
                        filings = fetch_chunk_via_api(s, pd_str, pd_str, max_records=3000)
                        sf = [f for f in filings if f['stockCode'] == code or f['stockCode'] == code.lstrip('0')]
                        pk = ['PLACING', 'PLACEMENT', 'RIGHTS', 'MANDATE', '配售', '供股', 'SUBSCRIPTION']
                        pf = [f for f in sf if any(k in f['title'].upper() for k in pk)
                              and 'COMPLETION' not in f['title'].upper()
                              and 'SUPPLEMENT' not in f['title'].upper()]
                        if pf:
                            prior_url = pf[0]['link']
                            try:
                                resp2 = requests.get(prior_url, headers={'User-Agent': UA}, timeout=20)
                                doc2 = pymupdf.open(stream=resp2.content, filetype='pdf')
                                text2 = ' '.join(doc2[pg].get_text() for pg in range(doc2.page_count))
                                doc2.close()
                                agent = extract_agent(text2, name)
                                if agent:
                                    break
                            except:
                                pass
                    except:
                        pass
        except:
            pass

    if agent:
        p[orig_i]['placing_agent'] = agent
        found += 1
        print(f'[{idx+1}/{len(needs)}] {code} {name} → {agent[:55]}')
    
    if (idx + 1) % 20 == 0:
        tmp = F + '.tmp'
        json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        os.replace(tmp, F)
        wa = sum(1 for x in p if x.get('placing_agent'))
        print(f'  [Saved: {found} total: {wa}/402]')
    elif (idx + 1) % 5 == 0:
        print(f'  [{idx+1}/{len(needs)}] progress...')

tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nFINAL: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
