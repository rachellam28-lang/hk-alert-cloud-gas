#!/usr/bin/env python3
"""LLM-assisted agent extraction: download PDFs, extract text, look for known agents."""
import json, os, re, sys, time
import requests, pymupdf
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PLACEMENTS_FILE = os.path.join(DATA_DIR, "placements_enriched.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Known placing agents from our existing data + HK market knowledge
KNOWN_AGENTS = {
    # From our data
    "KGI Asia Limited": "KGI Asia",
    "Guotai Junan Securities": "Guotai Junan",
    "Macquarie Capital Limited": "Macquarie Capital",
    "BNP Paribas Securities": "BNP Paribas",
    "DBS Asia Capital": "DBS Asia",
    "Morgan Stanley Asia": "Morgan Stanley",
    "First Shanghai Securities": "First Shanghai",
    "Cheong Lee Securities": "Cheong Lee",
    "Kingkey Securities": "Kingkey",
    "Grand China Securities": "Grand China",
    "Aristo Securities": "Aristo",
    "Advent Securities": "Advent",
    "Wanhai Securities": "Wanhai",
    "Patrons Securities": "Patrons",
    "Black Marble Securities": "Black Marble",
    "Roofer Securities": "Roofer",
    "Gransing Securities": "Gransing",
    "SFGHK Limited": "SFGHK",
    "Guoyuan Securities": "Guoyuan",
    "Suncorp Securities": "Suncorp",
    "Fortune (HK) Securities": "Fortune HK",
    "Uzen Securities": "Uzen",
    "CNI Securities": "CNI",
    "Pinestone Securities": "Pinestone",
    "Zijing Capital": "Zijing",
    "Kingston Securities": "Kingston",
    "China Demeter Securities": "China Demeter",
    "Direct Profit Enterprises": "Direct Profit",
    "Jakota Securities": "Jakota",
    "Theia Securities": "Theia",
    "Astrum Capital": "Astrum",
    "DaoKou Securities": "DaoKou",
    "Constance Capital": "Constance",
    "Central Wealth Securities": "Central Wealth",
    "Step Wide Investment": "Step Wide",
    "Tiger Faith Securities": "Tiger Faith",
    "TFI Securities": "TFI",
    "CCB International Capital": "CCB International",
    "CMB International Capital": "CMB International",
    "Haitong International": "Haitong",
    "CITIC Securities": "CITIC",
    "China Galaxy International": "China Galaxy",
    "GF Securities": "GF Securities",
    "Huatai Financial": "Huatai",
    "CICC": "CICC",
    "QUAM SECURITIES": "Quam",
    "Ruibang Securities": "Ruibang",
    "Yuet Sheung International": "Yuet Sheung",
    "Mont Avenir Capital": "Mont Avenir",
    "Somerley Capital": "Somerley",
    "Arta Asset Management": "Arta Asset",
    "Monmonkey Group Securities": "Monmonkey",
    "Funderstone Securities": "Funderstone",
    "DL Securities (HK)": "DL Securities",
    # Additional HK agents
    "Alpha Financial Group": "Alpha Financial",
    "Optima Capital": "Optima",
    "RaffAello Capital": "RaffAello",
    "Amasse Capital": "Amasse",
    "Maxa Capital": "Maxa",
    "Frontier Capital": "Frontier",
    "VB Securities": "VB Securities",
    "Get Nice Securities": "Get Nice",
    "Emperor Securities": "Emperor",
    "Bright Smart Securities": "Bright Smart",
    "Sun Hung Kai": "Sun Hung Kai",
    "Phillip Securities": "Phillip",
    "Celestial Securities": "Celestial",
    "South China Securities": "South China",
    "Core Pacific": "Core Pacific",
    "Yue Xiu Securities": "Yue Xiu",
    "Shenwan Hongyuan": "Shenwan Hongyuan",
    "Soochow Securities": "Soochow",
    "Everbright Securities": "Everbright",
    "China Merchants Securities": "China Merchants",
    "Ping An Securities": "Ping An",
    "Vickers Securities": "Vickers",
    "UBS Securities": "UBS",
    "Goldman Sachs": "Goldman Sachs",
    "J.P. Morgan": "JPMorgan",
    "Nomura International": "Nomura",
    "CLSA Limited": "CLSA",
    "Mizuho Securities": "Mizuho",
}


def find_agent_in_text(text, stock_name):
    """Find placing agent using known agent name matching."""
    text_lower = text.lower()
    
    # Strategy 1: Known agent names
    for full_name, short_name in KNOWN_AGENTS.items():
        # Search for the short form (more reliable)
        if short_name.lower() in text_lower:
            # Find the full match
            m = re.search(
                r'([A-Z][A-Za-z\s&.,()\'\-]{0,60}?' + re.escape(short_name) + r'[A-Za-z\s&.,()\'\-]{0,40})',
                text, re.IGNORECASE
            )
            if m:
                candidate = m.group(1).strip()
                # Clean up
                candidate = candidate.split('\n')[0].strip()
                if len(candidate) > 6 and len(candidate) < 70:
                    # Must not be the stock itself
                    if stock_name and len(stock_name) > 3 and stock_name.lower() in candidate.lower():
                        continue
                    return candidate
    
    # Strategy 2: "Placing Agent\nName" pattern
    m = re.search(
        r'(?:Placing|PLACING)\s+Agent\s*\n+([A-Z][A-Za-z\s&.,()\'\-]{8,70})',
        text, re.MULTILINE
    )
    if m:
        name = re.sub(r'\s+', ' ', m.group(1).strip())
        if len(name) > 8 and 'Hong Kong Exchanges' not in name and 'The Stock Exchange' not in name:
            if any(kw in name.lower() for kw in ['securities', 'capital', 'finance', 'bank', 'asia', 'international', 'partners', 'group', 'limited']):
                return name
    
    # Strategy 3: "Sole Placing Agent" context
    m = re.search(r'Sole\s+Overall\s+Coordinator.*?\n+([A-Z][A-Za-z\s&.,()\'\-]{8,70})', text, re.DOTALL)
    if m:
        name = re.sub(r'\s+', ' ', m.group(1).strip())
        if len(name) > 8 and name != stock_name:
            if any(kw in name.lower() for kw in ['securities', 'capital', 'finance', 'bank', 'asia', 'international', 'partners', 'group', 'limited']):
                return name
    
    return None


def main():
    print("Loading placements...", flush=True)
    with open(PLACEMENTS_FILE, encoding='utf-8') as f:
        placements = json.load(f)
    
    NEEDS_KW = ['配售', '供股', '先舊後新']
    needs = [p for p in placements
             if not p.get('placing_agent')
             and p.get('pdf_url')
             and any(kw in p.get('method', '') for kw in NEEDS_KW)]
    
    print(f"Events with PDF but no agent: {len(needs)}")
    
    found = 0
    failed = []
    
    for i, p in enumerate(needs):
        code = p['code']
        name = p['name']
        date_str = p['date']
        pdf_url = p['pdf_url']
        
        print(f"[{i+1}/{len(needs)}] {code} {name}", end=' ', flush=True)
        
        # Download PDF
        try:
            resp = requests.get(pdf_url, headers={"User-Agent": UA}, timeout=25)
            resp.raise_for_status()
            pdf_bytes = resp.content
        except Exception as e:
            print(f"✗ download")
            failed.append((code, name, date_str, f"download:{e}"))
            continue
        
        if len(pdf_bytes) < 100:
            print("✗ empty")
            continue
        
        # Extract text
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype='pdf')
            full_text = ''
            for pg in range(min(doc.page_count, 15)):
                full_text += doc[pg].get_text()
            doc.close()
        except Exception:
            print("✗ parse")
            continue
        
        if not full_text.strip():
            print("✗ no text")
            continue
        
        # Find agent
        agent = find_agent_in_text(full_text, name)
        
        if agent:
            # Clean trailing junk
            for delim in [' THE PLACING', ' The Placing', '\nThe Placing', ' Placing On',
                         ' The Company', ' To the best', ' To facilitate',
                         ' The Board', ' PLACING OF', ' being the sole',
                         ' as placing agent', ' Independent Financial',
                         ' as agent', ', being', ' Limited\n', ' Limited ']:
                idx = agent.lower().find(delim.lower())
                if idx > 0:
                    agent = agent[:idx].strip()
            
            # Verify
            if len(agent) < 6 or len(agent) > 70:
                print(f"✗ bad length: {len(agent)}")
                continue
            
            # Save
            for pl in placements:
                if pl['code'] == code and pl['date'] == date_str:
                    pl['placing_agent'] = agent
                    break
            found += 1
            print(f"→ {agent}")
        else:
            print("✗")
        
        if (i + 1) % 20 == 0:
            with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(placements, f, ensure_ascii=False, indent=2)
            print(f"  [Saved: {found}]")
        
        time.sleep(0.15)
    
    with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(placements, f, ensure_ascii=False, indent=2)
    
    total = sum(1 for p in placements if p.get('placing_agent'))
    print(f"\nDone: {found} new, {total}/{len(placements)} have agents")
    
    if failed:
        print(f"\nFailed ({len(failed)}):")
        for code, name, date, reason in failed[:10]:
            print(f"  {code} {name} ({date}): {reason}")


if __name__ == '__main__':
    main()
