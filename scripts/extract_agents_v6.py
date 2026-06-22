#!/usr/bin/env python3
"""v6: Direct known-name matching — Mistral OCR primary, EasyOCR fallback."""
import json, os, re, requests, pymupdf, numpy as np, easyocr, sys, time
sys.path.insert(0, '/tmp/hkex-filing-scraper/src')
from hkex_scraper.api import fetch_chunk_via_api

# ── Mistral OCR (primary) ──
_script_dir = os.path.dirname(os.path.abspath(__file__))
_mistral_path = os.path.join(_script_dir, '..', 'ccass', 'src')
if _mistral_path not in sys.path:
    sys.path.insert(0, _mistral_path)
try:
    from mistral_ocr import ocr_for_agent_extraction
    _MISTRAL_OK = True
except Exception as e:
    print(f'[init] Mistral OCR unavailable: {e}')
    _MISTRAL_OK = False

# ── EasyOCR (fallback) ──
reader = easyocr.Reader(['en', 'ch_sim'], gpu=False)
p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
F = 'data/placements_enriched.json'
UA = 'Mozilla/5.0'

KNOWN = sorted(set([
    # Major international
    'Morgan Stanley Asia Limited', 'Morgan Stanley & Co. International plc',
    'Goldman Sachs (Asia) L.L.C.', 'J.P. Morgan Securities (Asia Pacific) Limited',
    'UBS AG', 'UBS Securities Asia Limited',
    'Citigroup Global Markets Asia Limited',
    'Credit Suisse (Hong Kong) Limited',
    'Deutsche Bank AG',
    'Merrill Lynch (Asia Pacific) Limited',
    'Jefferies Hong Kong Limited',
    'Nomura International (Hong Kong) Limited',
    'Daiwa Capital Markets Hong Kong Limited',
    'CLSA Limited',
    'Mizuho Securities Asia Limited',
    # Chinese state-owned
    'CITIC Securities (Hong Kong) Limited',
    'CICC Hong Kong Securities Limited', 'China International Capital Corporation Hong Kong Securities Limited',
    'Guotai Junan Securities (Hong Kong) Limited',
    'Haitong International Securities Company Limited',
    'China Galaxy International Securities (Hong Kong) Co., Limited',
    'Huatai Financial Holdings (Hong Kong) Limited',
    'GF Securities (Hong Kong) Brokerage Limited',
    'CMB International Capital Limited',
    'CCB International Capital Limited',
    'BOCOM International Securities Limited',
    'ICBC International Securities Limited',
    'ABC International Securities Limited',
    'China Everbright Securities (HK) Limited',
    'Shenwan Hongyuan Securities (H.K.) Limited', 'Shenwan Hongyuan Capital (H.K.) Limited',
    'Ping An Securities Limited',
    'Soochow Securities (Hong Kong) Limited',
    'China Merchants Securities (HK) Co., Limited',
    'CEB International Capital Limited',
    'SPDB International Securities Limited',
    'Orient Securities (Hong Kong) Limited',
    'Dongxing Securities (Hong Kong) Company Limited',
    # HK local
    'KGI Asia Limited', 'KGI Capital Asia Limited',
    'Sun Hung Kai International Limited',
    'Phillip Securities (Hong Kong) Limited',
    'Emperor Securities Limited',
    'Bright Smart Securities International (H.K.) Limited',
    'Get Nice Securities Limited',
    'South China Securities Limited',
    'Core Pacific-Yamaichi International (H.K.) Limited',
    'Celestial Securities Limited',
    'Yue Xiu Securities Company Limited',
    'Quam Securities Limited',
    'Kingston Securities Limited',
    'First Shanghai Securities Limited',
    'Cheong Lee Securities Limited',
    'Grand China Securities Limited',
    'Aristo Securities Limited',
    'Advent Securities Limited',
    'Wanhai Securities Limited',
    'Patrons Securities Limited',
    'Black Marble Securities Limited',
    'Roofer Securities Limited',
    'Gransing Securities Co., Limited',
    'SFGHK Limited',
    'Guoyuan Securities Brokerage (Hong Kong) Limited',
    'Suncorp Securities Limited',
    'Uzen Securities Limited',
    'CNI Securities Limited',
    'Pinestone Securities Limited',
    'Zijing Capital Limited',
    'Kingkey Securities Limited',
    'Tiger Faith Securities Limited',
    'China Demeter Securities Limited',
    'Direct Profit Securities Limited',
    'Jakota Securities Group Limited',
    'Theia Securities Limited',
    'Astrum Capital Management Limited',
    'DaoKou Securities Limited',
    'Constance Capital Limited',
    'Central Wealth Securities Investment Limited',
    'Step Wide Investment Limited',
    'TFI Securities Limited',
    'DL Securities (HK) Limited',
    'Monmonkey Group Securities Limited',
    'Somerley Capital Limited',
    'Funderstone Securities Limited',
    'GEO Securities Limited',
    'Cheer Union Securities Limited',
    'Lego Securities Limited',
    'Grand Moore Capital Limited',
    'Maxa Securities Limited',
    'Optima Capital Limited',
    'RaffAello Securities (HK) Limited',
    'Amasse Capital Limited',
    'Frontier Capital Limited',
    'VB Securities Limited',
    'Runderstone Securities Limited',
    'MORTON SECURITIES LIMITED',
    'Rifa Securities Limited',
    'Yuet Sheung International Securities Limited',
    'Mont Avenir Capital Limited',
    'Arta Asset Management Limited',
    'Ruibang Securities Limited',
    'Alpha Financial Group Limited',
    'Glory Sun Securities Limited',
    'I WIN Securities Limited',
    'Tengard Capital Limited',
    'Caida Securities Limited',
    'Giraffe Securities Limited',
    'United Securities Limited',
    'Nova Capital Limited',
    'DDM Capital Limited',
    'Amber Securities Limited',
    'Hooray Securities Limited',
    'Fosun International Securities Limited',
    'Reliance Securities Limited',
    'SBI China Capital Financial Services Limited',
    'Prudential Brokerage Limited',
    'CNM Securities Limited',
    'Vickers Ballas Securities Limited',
    'BOCI Securities Limited',
    'Eddid Securities and Futures Limited',
    'Taiping Securities (HK) Co., Limited',
    'Zhongtai International Securities Limited',
    'CES Capital International (Hong Kong) Co., Limited',
    'Opus Capital Limited',
    'Platinum Securities Company Limited',
    'MIB Securities (Hong Kong) Limited',
    'UOB Kay Hian (Hong Kong) Limited',
    'CGS International Securities Hong Kong Limited',
    'CMBC Securities Company Limited',
    'Futu Securities International (Hong Kong) Limited',
    'BOCI Asia Limited',
    'Sigma Capital Management Limited',
    'Marshall Wace Asia Limited',
    'Bailian Capital Limited',
    'Fulbright Securities Limited',
    'Infinium Capital Limited',
    'REDSUN Capital Limited',
    'Pulse Wealth Limited',
    'Kaiser Securities Limited',
    'SHK HK Limited',
    'VMS Securities Limited',
    'Opulence Capital Limited',
    'Edmond Securities Limited',
    'Zion Securities Limited',
    'Huajin Securities (International) Limited',
    'Golden Mountain Securities Limited',
    'Yuehai Securities Limited',
    'Kingsway Financial Services Group Limited',
    # Bank securities arms
    'Bank of China (Hong Kong) Limited',
    'HSBC Broking Securities (Asia) Limited',
    'Standard Chartered Securities (Hong Kong) Limited',
    'Hang Seng Securities Limited',
    'Bank of East Asia Securities Limited',
    'Dah Sing Securities Limited',
    'Nanyang Commercial Bank Securities Limited',
    'Wing Lung Securities Limited',
    'Chiyu Securities Limited',
    'OCBC Wing Hang Securities Limited',
    # More international
    'BNP Paribas Securities (Asia) Limited',
    'DBS Asia Capital Limited',
    'Macquarie Capital Limited',
    'ING Securities Limited',
    'Barclays Capital Asia Limited',
    'Commerzbank AG',
    'Osiris Securities Limited',
]), key=len, reverse=True)

s = requests.Session()
s.headers.update({'User-Agent': UA})
NEEDS_KW = ['配售', '供股', '先舊後新']
all_needs = [(i, x) for i, x in enumerate(p) if not x.get('placing_agent') and any(k in x.get('method', '') for k in NEEDS_KW)]
print(f'{len(all_needs)} events to process')

found = 0
for idx, (orig_i, x) in enumerate(all_needs):
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

    print(f'[{idx+1}/{len(all_needs)}] {code} {name}', end=' ', flush=True)

    try:
        resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
    except:
        print('✗ pdf')
        continue

    text = ' '.join(doc[pg].get_text() for pg in range(min(doc.page_count, 12)))
    tl = text.lower()
    agent = None

    # Direct name match in text
    for kn in KNOWN:
        if kn.lower() in tl:
            if name and len(name) > 3 and name in kn:
                continue
            agent = kn
            break

    # OCR fallback — Mistral OCR primary
    if not agent and _MISTRAL_OK:
        try:
            agent = ocr_for_agent_extraction(resp.content, KNOWN, name)
        except Exception as e:
            print(f' [mistral] {e}', end='')

    # EasyOCR fallback
    if not agent:
        for pg_num in range(min(2, doc.page_count)):
            try:
                page = doc[pg_num]
                mat = pymupdf.Matrix(3, 3)
                pix = page.get_pixmap(matrix=mat)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = img[:, :, :3]
                lines = reader.readtext(img, detail=0, paragraph=False)
                ot = ' '.join(lines).lower()
                for kn in KNOWN:
                    if kn.lower() in ot:
                        if name and len(name) > 3 and name in kn:
                            continue
                        agent = kn
                        break
                if agent:
                    break
            except:
                pass

    doc.close()

    if agent:
        # Quality check: reject generic names and self-references
        al = agent.lower().strip()
        reject = False
        # Reject pure generic suffixes
        if al in ['securities limited', 'capital limited', 'securities co., limited',
                   'securities (hong kong) limited']:
            reject = True
        # Reject if agent is just the company's English name
        if name and len(name) > 3:
            for part_len in [3, 4]:
                for start in range(0, max(1, len(name) - part_len + 1)):
                    frag = name[start:start + part_len]
                    if len(frag) >= 3 and frag in agent:
                        reject = True
                        break
                if reject:
                    break
        if not reject:
            p[orig_i]['placing_agent'] = agent
            found += 1
            print(f'→ {agent[:55]}')
        else:
            print('✗ self/generic')
    else:
        print('✗')

    if (idx + 1) % 30 == 0:
        tmp = F + '.tmp'
        json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        os.replace(tmp, F)
        print(f'  [Saved: {found}]')

tmp = F + '.tmp'
json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
os.replace(tmp, F)

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nFINAL: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
