#!/usr/bin/env python3
"""Extract placing agents using proven hkex-filing-scraper API."""
import json, os, re, sys, time
from datetime import datetime, date
from collections import defaultdict

# Add hkex-filing-scraper to path
HKEX_SCRAPER = "/tmp/hkex-filing-scraper/src"
if os.path.isdir(HKEX_SCRAPER):
    sys.path.insert(0, HKEX_SCRAPER)

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

from hkex_scraper.api import fetch_chunk_via_api, HKEX_BASE_URL

try:
    import pymupdf
except ImportError:
    print("pip install PyMuPDF")
    sys.exit(1)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PLACEMENTS_FILE = os.path.join(DATA_DIR, "placements_enriched.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

PLACEMENT_KW = ['PLACING', 'PLACEMENT', 'RIGHTS ISSUE', 'SUBSCRIPTION',
                '配售', '供股', '認購', 'MANDATE', 'TOP-UP', 'OPEN OFFER']

KNOWN_AGENTS = [
    "KGI Asia", "Macquarie Capital", "Guotai Junan", "BNP Paribas",
    "DBS Asia Capital", "Morgan Stanley", "First Shanghai", "Cheong Lee",
    "Kingkey Securities", "Grand China Securities", "Aristo Securities",
    "Advent Securities", "Wanhai Securities", "Patrons Securities",
    "Black Marble", "Roofer Securities", "Gransing Securities",
    "SFGHK", "Guoyuan Securities", "Suncorp Securities",
    "Fortune (HK) Securities", "Uzen Securities", "CNI Securities",
    "Pinestone Securities", "Zijing Capital", "Kingston Securities",
    "China Demeter", "Direct Profit", "Jakota Securities",
    "Theia Securities", "Astrum Capital", "DaoKou Securities",
    "Constance Capital", "Central Wealth", "Step Wide",
    "Tiger Faith", "TFI Securities", "CCB International",
    "CMB International", "Haitong", "CITIC Securities",
    "China Galaxy", "GF Securities", "Huatai", "CICC",
    "UBS", "Goldman Sachs", "JPMorgan", "Nomura", "CLSA",
    "Phillip Securities", "Bright Smart", "Emperor Securities",
    "Sun Hung Kai", "Shenwan Hongyuan", "Soochow Securities",
    "China Merchants", "Ping An", "Futu", "Vickers", "Quam",
    "Ruibang", "DL Securities", "Monmonkey", "Somerley",
    "VB Securities", "Get Nice",
]


def extract_agent(pdf_url, stock_name):
    """Download PDF and extract placing agent."""
    try:
        resp = requests.get(pdf_url, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception:
        return None
    if len(pdf_bytes) < 100:
        return None
    
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype='pdf')
        text = ''
        for pg in range(min(doc.page_count, 15)):
            text += doc[pg].get_text()
        doc.close()
    except Exception:
        return None
    if not text.strip():
        return None
    
    # Pre-filter: remove disclaimer sections that cause false positives
    disclaimer_start = text.find('Hong Kong Exchanges and Clearing Limited')
    if disclaimer_start >= 0:
        # Find end of disclaimer (usually after 2-3 paragraphs)
        end1 = text.find('\n\n', disclaimer_start + 100)
        end2 = text.find('\n\n', end1 + 10) if end1 > 0 else -1
        end3 = text.find('\n\n', end2 + 10) if end2 > 0 else -1
        if end3 > 0:
            text = text[:disclaimer_start] + text[end3:]
    
    # Strategy 1: "Placing Agent\nName"
    for pat in [
        r'(?:Placing|PLACING)\s+Agent\s*\n+([A-Z][A-Za-z\s&.,()\'\-]{6,80})',
        r'配售代理\s*\n+([A-Z][A-Za-z\s&.,()\'\-]{6,80})',
    ]:
        m = re.search(pat, text)
        if m:
            name = re.sub(r'\s+', ' ', m.group(1).strip())
            if len(name) > 8 and name != stock_name and 'Hong Kong Exchanges' not in name:
                if any(kw in name.lower() for kw in 
                       ['securities', 'capital', 'finance', 'bank', 'asia',
                        'international', 'partners', 'group', 'limited']):
                    return name
    
    # Strategy 2: Known agents
    for agent in KNOWN_AGENTS:
        if agent.lower() in text.lower():
            m = re.search(re.escape(agent) + r'[\s\w,.]{0,30}', text, re.I)
            if m:
                full = m.group(0).strip().rstrip(',.')
                if len(full) < 60:
                    return full
    
    # Strategy 3: "Sole Placing Agent" context
    for m in re.finditer(r'Sole\s+Placing\s+Agent|Sole\s+Overall\s+Coordinator', text, re.I):
        ctx = text[m.start():m.end()+400]
        companies = re.findall(
            r'([A-Z][A-Za-z\s&.,()\'\-]{8,60}?\s(?:Limited|LIMITED|Ltd\.?|Inc\.?|'
            r'Securities|Capital|Finance|Financial|International|Partners|Asia|Group))', ctx)
        for c in companies:
            c = c.strip()
            if c != stock_name and len(c) > 6:
                return c
    
    # Strategy 4: Chinese names near 配售代理
    for m in re.finditer(r'配售代理', text):
        ctx = text[m.start():m.end()+200]
        companies = re.findall(
            r'([^\n\r，,]{2,30}(?:證券|金融|資本|融資|企業|集團|控股|銀行)'
            r'(?:有限公司|股份有限公司)?)', ctx)
        for c in companies:
            if c != stock_name and len(c) > 4:
                return c
    
    return None


def main():
    print("Loading placements...", flush=True)
    with open(PLACEMENTS_FILE, encoding='utf-8') as f:
        placements = json.load(f)
    
    NEEDS_KW = ['配售', '供股', '先舊後新']
    needs = [p for p in placements
             if not p.get('placing_agent')
             and any(kw in p.get('method', '') for kw in NEEDS_KW)]
    
    # Group by date for efficient API calls
    by_date = defaultdict(list)
    for p in needs:
        by_date[p['date']].append(p)
    
    print(f"Need agents: {len(needs)} events across {len(by_date)} dates")
    
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    
    found = 0
    processed = 0
    
    # Only process dates that still have unprocessed events
    for date_str, events in sorted(by_date.items()):
        # Skip dates where ALL events already have agents
        pending = [e for e in events if not e.get('placing_agent')]
        if not pending:
            continue
        try:
            dd, mm, yyyy = date_str.split('/')
            api_date = f"{yyyy}{mm}{dd}"
        except:
            continue
        
        # Fetch ALL filings for this date (much faster than per-stock)
        print(f"\n{date_str}: fetching filings...", end=' ', flush=True)
        try:
            all_filings = fetch_chunk_via_api(session, api_date, api_date, max_records=3000)
        except Exception as e:
            print(f"API error: {e}")
            time.sleep(1)
            continue
        
        print(f"{len(all_filings)} total")
        
        # Build lookup by stock code
        filings_by_code = defaultdict(list)
        for f in all_filings:
            filings_by_code[f['stockCode']].append(f)
            # Also index by stripped code
            stripped = f['stockCode'].lstrip('0') or '0'
            if stripped != f['stockCode']:
                filings_by_code[stripped].append(f)
        
        for p in events:
            processed += 1
            code = p['code']
            name = p['name']
            code_stripped = code.lstrip('0') or '0'
            
            stock_filings = filings_by_code.get(code, []) + filings_by_code.get(code_stripped, [])
            
            # Filter placement-related
            placement_filings = [f for f in stock_filings 
                               if any(kw in f['title'].upper() for kw in PLACEMENT_KW)]
            
            if not placement_filings:
                # Try without filtering
                placement_filings = stock_filings[:3]
            
            print(f"  [{processed}/{len(needs)}] {code} {name}", end=' ', flush=True)
            
            if not placement_filings:
                print("no filings")
                continue
            
            agent = None
            for f in placement_filings[:3]:
                pdf_url = f['link']
                if not pdf_url or not pdf_url.endswith('.pdf'):
                    continue
                agent = extract_agent(pdf_url, name)
                if agent:
                    break
                time.sleep(0.15)
            
            if agent:
                for pl in placements:
                    if pl['code'] == code and pl['date'] == date_str:
                        pl['placing_agent'] = agent
                        if placement_filings:
                            pl['pdf_url'] = placement_filings[0]['link']
                        break
                found += 1
                print(f"→ {agent}")
            else:
                print("✗")
            
            time.sleep(0.2)
        
        # Save after each date
        with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(placements, f, ensure_ascii=False, indent=2)
        print(f"  [Saved: {found} new]")
        
        time.sleep(0.5)  # Rate limit between dates
    
    total = sum(1 for p in placements if p.get('placing_agent'))
    print(f"\nDone: {found} new, {total}/{len(placements)} have agents")


if __name__ == '__main__':
    main()
