#!/usr/bin/env python3
"""Smart agent extraction from HKEX PDFs — wider context, better patterns."""
import json, os, re, sys, time
from urllib.request import urlopen, Request
import pymupdf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PLACEMENTS_FILE = os.path.join(DATA_DIR, "placements_enriched.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Common HK placing agents (from known data + industry knowledge)
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
    "Theia Securities", "VB Securities", "Astrum Capital",
    "Daokou Capital", "Constance Capital", "Nice Capital",
    "Wealth Link", "Tiger Securities", "Faith Securities",
    "TF Securities", "SFG Securities", "Get Nice",
    "China Galaxy", "Haitong", "CITIC Securities",
    "CMB International", "CCB International", "BOCOM International",
    "ICBC International", "ABC International", "CEB International",
    "GF Securities", "Huatai", "CICC", "UBS", "Goldman Sachs",
    "JPMorgan", "Credit Suisse", "Deutsche Bank", "Nomura",
    "Mizuho", "Daiwa", "CLSA", "Phillip Securities",
    "Bright Smart", "Emperor Securities", "Sun Hung Kai",
    "Yue Xiu", "Shanghai Pudong", "Shenwan Hongyuan",
    "Soochow Securities", "Everbright", "Orient Securities",
    "China Merchants", "Ping An", "Futu", "Tiger Brokers",
    "Vickers", "Quam", "South China", "Core Pacific",
    "Celestial", "Optima", "RaffAello", "Amasse",
    "Maxa", "Frontier", "Alpha", "Sigma", "Delta",
]

def extract_agent(text, stock_name, stock_code):
    """Extract placing agent from PDF text using multiple strategies."""
    
    # Strategy 1: Direct "Placing Agent\nCompany Name" pattern
    for pat in [r'Placing\s+Agent\s*\n+([A-Z][A-Za-z\s&.,()\-]{6,80})',
                r'配售代理\s*\n+([A-Z][A-Za-z\s&.,()\-]{6,80})',
                r'Sole\s+Placing\s+Agent\s*\n+([A-Z][A-Za-z\s&.,()\-]{6,80})',
                r'Placing\s+Agent\s*\n+\s*([^\n]{6,80})']:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            name = m.group(1).strip()
            # Clean up
            name = re.sub(r'\s+', ' ', name)
            if len(name) > 6 and name != stock_name and 'Hong Kong Exchanges' not in name:
                return name
    
    # Strategy 2: "Sole Overall Coordinator, Sole Placing Agent and Capital Market Intermediary\nName"
    for pat in [r'Sole\s+Overall\s+Coordinator.*?\n+([A-Z][A-Za-z\s&.,()\-]{6,80})',
                r'Capital\s+Market\s+Intermediary\s*\n+([A-Z][A-Za-z\s&.,()\-]{6,80})']:
        m = re.search(pat, text, re.MULTILINE | re.DOTALL)
        if m:
            name = m.group(1).strip()
            name = re.sub(r'\s+', ' ', name)
            if len(name) > 6 and name != stock_name:
                return name
    
    # Strategy 3: Known agent names in the PDF
    text_lower = text.lower()
    for agent in KNOWN_AGENTS:
        if agent.lower() in text_lower:
            # Verify it's not just mentioned as a random company
            # Find the full name with suffix
            pat = re.escape(agent) + r'[\s\w]{0,30}'
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                full = m.group(0).strip()
                # Clean trailing punctuation
                full = re.sub(r'[,;.]$', '', full)
                if len(full) < 60:
                    return full
    
    # Strategy 4: Company name near "Placing Agent" within 300 chars
    for m in re.finditer(r'(?:P|p)lacing\s+(?:A|a)gent|配售代理', text):
        context = text[m.start()-50:m.end()+300]
        # Find company-like names in context
        companies = re.findall(
            r'([A-Z][A-Za-z\s&.,()\-]{6,60}?\s(?:Limited|LIMITED|Ltd\.?|Inc\.?|'
            r'Securities|Capital|Finance|Financial|International|Partners|Asia|Group))',
            context)
        for c in companies:
            c = c.strip()
            if c != stock_name and len(c) > 8:
                return c
    
    # Strategy 5: Chinese company names near "配售代理"
    for m in re.finditer(r'配售代理', text):
        context = text[m.start()-50:m.end()+200]
        companies = re.findall(
            r'([^\n\r，,]{2,30}(?:證券|金融|資本|融資|企業|集團|控股|銀行)'
            r'(?:有限公司|股份有限公司)?)',
            context)
        for c in companies:
            c = c.strip()
            if c != stock_name and len(c) > 4:
                return c
    
    return None


def main():
    print("Loading placements...", flush=True)
    with open(PLACEMENTS_FILE, encoding='utf-8') as f:
        placements = json.load(f)

    NEEDS_AGENT_KW = ['配售', '供股', '先舊後新']
    needs = [p for p in placements
             if not p.get('placing_agent')
             and any(kw in p.get('method', '') for kw in NEEDS_AGENT_KW)
             and p.get('pdf_url')]  # Only process those with PDF URLs

    print(f"Events with PDF but no agent: {len(needs)}")
    
    found = 0
    for i, p in enumerate(needs):
        code = p['code']
        name = p['name']
        pdf_url = p['pdf_url']
        
        print(f"[{i+1}/{len(needs)}] {code} {name}", end=' ', flush=True)
        
        try:
            resp = urlopen(Request(pdf_url, headers={"User-Agent": UA}), timeout=25)
            pdf_bytes = resp.read()
            if len(pdf_bytes) < 100:
                print("✗ (small PDF)")
                continue
        except Exception as e:
            print(f"✗ (download: {e})")
            continue
        
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype='pdf')
            # Read all pages
            full_text = ''
            for pg in range(min(doc.page_count, 15)):
                full_text += doc[pg].get_text()
            doc.close()
        except Exception:
            print("✗ (parse)")
            continue
        
        agent = extract_agent(full_text, name, code)
        
        if agent:
            # Verify agent is not the stock itself
            if name and len(name) > 3 and name in agent:
                print(f"✗ (self-match: {agent})")
                continue
            # Verify agent looks like a financial institution
            if not any(kw in agent.lower() for kw in 
                       ['securities', 'capital', 'finance', 'bank', 'asia', 
                        '證券', '金融', '資本', '銀行', 'international',
                        'partners', 'group', 'limited', 'ltd', 'inc']):
                print(f"✗ (not financial: {agent})")
                continue
            
            # Update the placement
            for pl in placements:
                if pl['code'] == code and pl['date'] == p['date']:
                    pl['placing_agent'] = agent
                    break
            found += 1
            print(f"→ {agent}")
        else:
            print("✗")
        
        time.sleep(0.3)
        
        if (i + 1) % 10 == 0:
            with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(placements, f, ensure_ascii=False, indent=2)
            print(f"  [Saved: {found} new]")
    
    with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(placements, f, ensure_ascii=False, indent=2)
    
    total = sum(1 for p in placements if p.get('placing_agent'))
    print(f"\nDone: {found} new, {total}/{len(placements)} have agents")


if __name__ == '__main__':
    main()
