#!/usr/bin/env python3
"""v9: Targeted OCR — find Placing Agent pages, OCR only those."""
import json, os, re, requests, pymupdf, numpy as np, easyocr, sys, time

reader = easyocr.Reader(['en', 'ch_sim'], gpu=False)
p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
F = 'data/placements_enriched.json'
UA = 'Mozilla/5.0'

KNOWN = sorted(set([
    'Morgan Stanley Asia Limited', 'Goldman Sachs (Asia) L.L.C.',
    'J.P. Morgan Securities (Asia Pacific) Limited', 'J.P. Morgan',
    'UBS AG', 'UBS Securities Asia Limited',
    'Citigroup Global Markets Asia Limited',
    'Credit Suisse (Hong Kong) Limited', 'Deutsche Bank AG',
    'Jefferies Hong Kong Limited', 'Nomura International (Hong Kong) Limited',
    'Daiwa Capital Markets Hong Kong Limited', 'CLSA Limited',
    'Mizuho Securities Asia Limited',
    'CITIC Securities (Hong Kong) Limited', 'CICC Hong Kong Securities Limited',
    'Guotai Junan Securities (Hong Kong) Limited', 'Guotai Junan Securities',
    'Haitong International Securities Company Limited',
    'China Galaxy International Securities (Hong Kong) Co., Limited',
    'Huatai Financial Holdings (Hong Kong) Limited',
    'GF Securities (Hong Kong) Brokerage Limited',
    'CMB International Capital Limited', 'CCB International Capital Limited',
    'BOCOM International Securities Limited', 'ICBC International Securities Limited',
    'ABC International Securities Limited',
    'China Everbright Securities (HK) Limited',
    'Shenwan Hongyuan Securities (H.K.) Limited', 'Shenwan Hongyuan Capital (H.K.) Limited',
    'Ping An Securities Limited', 'Soochow Securities (Hong Kong) Limited',
    'China Merchants Securities (HK) Co., Limited',
    'CEB International Capital Limited', 'SPDB International Securities Limited',
    'Orient Securities (Hong Kong) Limited',
    'Dongxing Securities (Hong Kong) Company Limited',
    'KGI Asia Limited', 'Sun Hung Kai International Limited',
    'Phillip Securities (Hong Kong) Limited', 'Emperor Securities Limited',
    'Bright Smart Securities International (H.K.) Limited',
    'Get Nice Securities Limited', 'South China Securities Limited',
    'Core Pacific-Yamaichi International (H.K.) Limited',
    'Celestial Securities Limited', 'Yue Xiu Securities Company Limited',
    'Quam Securities Limited', 'Kingston Securities Limited',
    'First Shanghai Securities Limited', 'Cheong Lee Securities Limited',
    'Grand China Securities Limited', 'Aristo Securities Limited',
    'Advent Securities Limited', 'Wanhai Securities Limited',
    'Patrons Securities Limited', 'Black Marble Securities Limited',
    'Roofer Securities Limited', 'Gransing Securities Co., Limited',
    'SFGHK Limited', 'Guoyuan Securities Brokerage (Hong Kong) Limited',
    'Suncorp Securities Limited', 'Uzen Securities Limited',
    'CNI Securities Limited', 'Pinestone Securities Limited',
    'Zijing Capital Limited', 'Kingkey Securities Limited',
    'Tiger Faith Securities Limited', 'China Demeter Securities Limited',
    'Direct Profit Securities Limited', 'Jakota Securities Group Limited',
    'Theia Securities Limited', 'Astrum Capital Management Limited',
    'DaoKou Securities Limited', 'Constance Capital Limited',
    'Central Wealth Securities Investment Limited',
    'Step Wide Investment Limited', 'TFI Securities Limited',
    'DL Securities (HK) Limited', 'Monmonkey Group Securities Limited',
    'Somerley Capital Limited', 'Funderstone Securities Limited',
    'GEO Securities Limited', 'Cheer Union Securities Limited',
    'Lego Securities Limited', 'Grand Moore Capital Limited',
    'Maxa Securities Limited', 'Optima Capital Limited',
    'RaffAello Securities (HK) Limited', 'Amasse Capital Limited',
    'Frontier Capital Limited', 'VB Securities Limited',
    'Runderstone Securities Limited', 'MORTON SECURITIES LIMITED',
    'Rifa Securities Limited', 'Yuet Sheung International Securities Limited',
    'Mont Avenir Capital Limited', 'Arta Asset Management Limited',
    'Ruibang Securities Limited', 'Alpha Financial Group Limited',
    'Glory Sun Securities Limited', 'I WIN Securities Limited',
    'Tengard Capital Limited', 'Caida Securities Limited',
    'Giraffe Securities Limited', 'United Securities Limited',
    'Nova Capital Limited', 'DDM Capital Limited',
    'Amber Securities Limited', 'Hooray Securities Limited',
    'Fosun International Securities Limited', 'Reliance Securities Limited',
    'SBI China Capital Financial Services Limited',
    'Prudential Brokerage Limited', 'CNM Securities Limited',
    'Vickers Ballas Securities Limited', 'BOCI Securities Limited',
    'Eddid Securities and Futures Limited', 'Taiping Securities (HK) Co., Limited',
    'Zhongtai International Securities Limited',
    'CES Capital International (Hong Kong) Co., Limited',
    'Opus Capital Limited', 'Platinum Securities Company Limited',
    'MIB Securities (Hong Kong) Limited', 'UOB Kay Hian (Hong Kong) Limited',
    'CGS International Securities Hong Kong Limited',
    'CMBC Securities Company Limited',
    'Futu Securities International (Hong Kong) Limited',
    'BOCI Asia Limited', 'Sigma Capital Management Limited',
    'Marshall Wace Asia Limited', 'Bailian Capital Limited',
    'Fulbright Securities Limited', 'Infinium Capital Limited',
    'REDSUN Capital Limited', 'Pulse Wealth Limited',
    'Kaiser Securities Limited', 'SHK HK Limited',
    'VMS Securities Limited', 'Opulence Capital Limited',
    'Edmond Securities Limited', 'Zion Securities Limited',
    'Huajin Securities (International) Limited',
    'Golden Mountain Securities Limited', 'Yuehai Securities Limited',
    'Kingsway Financial Services Group Limited',
    'BNP Paribas Securities (Asia) Limited',
    'DBS Asia Capital Limited', 'Macquarie Capital Limited',
    'ING Securities Limited', 'Barclays Capital Asia Limited',
    'Bank of China (Hong Kong) Limited',
    'HSBC Broking Securities (Asia) Limited',
    'Standard Chartered Securities (Hong Kong) Limited',
    'Dah Sing Securities Limited', 'BofA Securities',
    'Merrill Lynch (Asia Pacific) Limited',
    'Osiris Securities Limited', 'Commerzbank AG',
]), key=len, reverse=True)

# Remove existing to avoid duplicates
KNOWN = [k for k in KNOWN if not any(g in k.lower() for g in ['hong kong exch','stock exch','reference is made'])]

needs = [(i, x) for i, x in enumerate(p) if not x.get('placing_agent') and x.get('pdf_url')]
print(f'{len(needs)} PDFs to OCR')

s = requests.Session()
s.headers.update({'User-Agent': UA})
found = 0

for idx, (orig_i, x) in enumerate(needs):
    code = x['code']
    name = x['name']
    url = x['pdf_url']
    
    print(f'[{idx+1}/{len(needs)}] {code} {name}', end=' ', flush=True)
    
    try:
        resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
    except:
        print('✗')
        continue
    
    text = ' '.join(doc[pg].get_text() for pg in range(doc.page_count))
    tl = text.lower()
    agent = None
    
    # 1. Text match first (fast)
    for kn in KNOWN:
        if kn.lower() in tl:
            if name and len(name) > 3 and name in kn: continue
            agent = kn
            break
    
    # 2. Find "Placing Agent" pages and OCR them
    if not agent:
        agent_pages = set()
        for pg in range(doc.page_count):
            pt = doc[pg].get_text().lower()
            if 'placing agent' in pt or 'placing agents' in pt:
                agent_pages.add(pg)
        
        # Always include first 2 pages
        agent_pages.update([0, 1])
        agent_pages = sorted(agent_pages)[:5]  # Max 5 pages
        
        for pg_num in agent_pages:
            try:
                page = doc[pg_num]
                mat = pymupdf.Matrix(3, 3)
                pix = page.get_pixmap(matrix=mat)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4: img = img[:, :, :3]
                lines = reader.readtext(img, detail=0, paragraph=False)
                ot = ' '.join(lines)
                
                # Search known agents in OCR
                for kn in KNOWN:
                    if kn.lower() in ot.lower():
                        if name and len(name) > 3 and name in kn: continue
                        agent = kn
                        break
                
                # Search for pattern: "X Securities Limited" in OCR
                if not agent:
                    for m in re.finditer(r'([A-Z][A-Za-z\s&.,]{5,40}(?:Securities|Capital|Finance|Bank)\s+(?:Limited|Ltd|Co\.|Company))', ot):
                        candidate = m.group(1).strip()
                        candidate = re.sub(r'\s+', ' ', candidate)
                        if 10 < len(candidate) < 70 and name not in candidate:
                            if not any(g in candidate.lower() for g in ['hong kong exch','stock exch','securities and futures','securities ordinance']):
                                agent = candidate
                                break
                
                if agent: break
            except:
                pass
    
    doc.close()
    
    if agent:
        p[orig_i]['placing_agent'] = agent
        found += 1
        print(f'→ {agent[:55]}')
    else:
        print('✗')
    
    if (idx + 1) % 20 == 0:
        tmp = F + '.tmp'
        json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        os.replace(tmp, F)
        print(f'  [Saved: {found}]')
    
    sys.stdout.flush()

tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nDone: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
