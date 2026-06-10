#!/usr/bin/env python3
"""FINAL: combine all known good agents + text match from PDFs."""
import json, os, re, requests, pymupdf

f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "placements_enriched.json")
p = json.load(open(f, encoding='utf-8'))
UA = 'Mozilla/5.0'

# === PHASE 1: Manually confirmed agents from OCR ===
OCR_CONFIRMED = {
    ('01277','03/06/2026'): 'CITIC Securities',
    ('01912','08/06/2026'): 'Grand Moore Capital Limited',
    ('01679','瑞斯康集團'): None,  # skip for now
    ('01384','滴普科技'): None,
}

# === PHASE 2: Known agent text matching from PDFs ===
KNOWN_AGENTS_LOWER = [s.lower() for s in [
    'KGI Asia Limited', 'Guotai Junan Securities', 'Macquarie Capital Limited',
    'BNP Paribas Securities', 'DBS Asia Capital', 'Morgan Stanley Asia',
    'First Shanghai Securities', 'Cheong Lee Securities', 'Kingkey Securities',
    'Grand China Securities', 'Aristo Securities', 'Advent Securities',
    'Wanhai Securities', 'Patrons Securities', 'Black Marble Securities',
    'Roofer Securities', 'Gransing Securities', 'SFGHK Limited',
    'Guoyuan Securities', 'Suncorp Securities', 'Fortune (HK) Securities',
    'Uzen Securities', 'CNI Securities', 'Pinestone Securities',
    'Zijing Capital', 'Kingston Securities', 'China Demeter Securities',
    'Direct Profit Enterprises', 'Jakota Securities', 'Theia Securities',
    'Astrum Capital', 'DaoKou Securities', 'Constance Capital',
    'Central Wealth Securities', 'Step Wide Investment', 'Tiger Faith Securities',
    'TFI Securities', 'CCB International Capital', 'CMB International Capital',
    'Haitong International', 'CITIC Securities', 'China Galaxy International',
    'GF Securities', 'Huatai', 'QUAM SECURITIES', 'Ruibang Securities',
    'DL Securities', 'Monmonkey Group', 'Somerley Capital', 'Funderstone Securities',
    'GEO Securities', 'BofA Securities', 'Dongxing Securities',
    'Cheer Union Securities', 'Lego Securities', 'Grand Moore Capital',
    'Maxa Securities', 'Optima Capital', 'RaffAello Capital', 'Amasse Capital',
    'Frontier Capital', 'VB Securities', 'Get Nice Securities',
    'Emperor Securities', 'Bright Smart Securities', 'Sun Hung Kai',
    'Phillip Securities', 'Celestial Securities', 'South China Securities',
    'Core Pacific', 'Yue Xiu Securities', 'Shenwan Hongyuan',
    'Soochow Securities', 'Everbright Securities', 'China Merchants Securities',
    'Ping An Securities', 'Vickers Securities', 'Nomura International',
    'CLSA Limited', 'Mizuho Securities', 'Daiwa Capital Markets',
    'Credit Suisse', 'Deutsche Bank', 'BOCOM International',
    'ICBC International', 'ABC International', 'CEB International',
    'CNM Securities', 'SBI Securities', 'Prudential Brokerage',
    'Shanghai Pudong', 'Orient Securities', 'Reliance Securities',
    'Fosun', 'Amber', 'Hooray', 'DDM', 'Tengard', 'Caida', 'Giraffe',
    'United', 'Nova', 'Alpha Financial', 'Glory Sun Securities',
    'I WIN SECURITIES', 'Runderstone Securities', 'MORTON SECURITIES',
    'Rifa Securities', 'Yuet Sheung International', 'Mont Avenir Capital',
    'Arta Asset Management',
]]

NEEDS_KW = ['配售', '供股', '先舊後新']
needs = [(i, x) for i, x in enumerate(p)
         if not x.get('placing_agent') and x.get('pdf_url')
         and any(kw in x.get('method', '') for kw in NEEDS_KW)]

print(f"Processing {len(needs)} PDFs...")
found = 0

for idx, (orig_i, x) in enumerate(needs):
    code = x['code']; name = x['name']; url = x['pdf_url']
    
    # Try text matching
    try:
        resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
    except:
        continue
    
    text = ''
    for pg in range(min(doc.page_count, 10)):
        text += doc[pg].get_text()
    doc.close()
    
    tl = text.lower()
    agent = None
    
    for ka in KNOWN_AGENTS_LOWER:
        if ka in tl:
            m = re.search(r'([A-Z][A-Za-z\s&.,()\'\-]{0,40}' + re.escape(ka) + r'[A-Za-z\s&.,()\'\-]{0,30})', text, re.I)
            if m:
                agent = m.group(1).strip()
                # Clean
                agent = re.sub(r'\s+', ' ', agent)
                agent = agent.split('\n')[0].strip()
                # Trim at common delimiters
                for delim in [' THE PLACING', ' The Placing', ' The Board', ' To the best',
                             ' PLACING OF', ' being the sole', ' as placing', ' Limited (',
                             ', being', ' Limited\n', ' Limited  ']:
                    idx2 = agent.lower().find(delim.lower())
                    if idx2 > 0:
                        agent = agent[:idx2].strip()
                if 8 < len(agent) < 70:
                    break
                else:
                    agent = None
    
    # Validate
    if agent:
        if name and len(name) > 3 and name in agent:
            continue
        if not any(kw in agent.lower() for kw in 
                   ['securities', 'capital', 'finance', 'bank', 'asia',
                    'international', 'partners', 'group', 'limited', 'ltd',
                    'investment', 'asset', 'management']):
            continue
        if len(agent) < 8 or len(agent) > 70:
            continue
        
        p[orig_i]['placing_agent'] = agent
        found += 1
        print(f"[{idx+1}/{len(needs)}] {code} {name} → {agent[:55]}")

# Also apply OCR confirmed
for (code, date_str), agent in OCR_CONFIRMED.items():
    if not agent:
        continue
    for x in p:
        if x['code'] == code and date_str in x['date']:
            if not x.get('placing_agent'):
                x['placing_agent'] = agent
                found += 1
                print(f"OCR: {code} {x['name']} → {agent}")

# Save
tmp = f + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, f)

total = sum(1 for x in p if x.get('placing_agent'))
print(f"\nDone: {found} new, {total}/402")
needs_with = [x for x in p if x.get('placing_agent') and any(kw in x.get('method','') for kw in NEEDS_KW)]
all_needs = [x for x in p if any(kw in x.get('method','') for kw in NEEDS_KW)]
print(f"Placement/rights: {len(needs_with)}/{len(all_needs)} ({len(needs_with)/len(all_needs)*100:.0f}%)")
