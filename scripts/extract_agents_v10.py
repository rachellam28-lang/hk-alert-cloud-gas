#!/usr/bin/env python3
"""v10: Defensive OCR — try/except everywhere, smaller images, memory cleanup."""
import json, os, re, requests, pymupdf, numpy as np, gc, sys, time, traceback

# Load EasyOCR ONCE at startup (main cause of segfaults is repeated model loading)
try:
    reader = None  # Lazy init
    def get_reader():
        global reader
        if reader is None:
            import easyocr
            reader = easyocr.Reader(['en', 'ch_sim'], gpu=False)
        return reader
except Exception as e:
    print(f'EasyOCR init error: {e}')

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

# Known agents for text matching (quick first pass)
KNOWN_SHORT = [
    'KGI Asia', 'Guotai Junan', 'Macquarie', 'BNP Paribas', 'DBS Asia',
    'Morgan Stanley', 'First Shanghai', 'Cheong Lee', 'Kingkey', 'Grand China',
    'Aristo', 'Advent', 'Wanhai', 'Patrons', 'Black Marble', 'Roofer', 'Gransing',
    'SFGHK', 'Guoyuan', 'Suncorp', 'Uzen', 'CNI Securities', 'Pinestone',
    'Zijing', 'Kingston', 'China Demeter', 'Direct Profit', 'Jakota', 'Theia',
    'Astrum', 'DaoKou', 'Constance', 'Central Wealth', 'Step Wide', 'Tiger Faith',
    'TFI Securities', 'CCB International', 'CMB International', 'Haitong',
    'CITIC Securities', 'China Galaxy', 'GF Securities', 'Huatai', 'QUAM',
    'Ruibang', 'DL Securities', 'Monmonkey', 'Somerley', 'Funderstone', 'GEO',
    'BofA Securities', 'Dongxing', 'Cheer Union', 'Lego', 'Grand Moore',
    'Maxa', 'Optima', 'RaffAello', 'Amasse', 'Frontier', 'VB Securities',
    'Get Nice', 'Emperor', 'Bright Smart', 'Sun Hung Kai', 'Phillip',
    'Celestial', 'South China', 'Core Pacific', 'Yue Xiu', 'Shenwan',
    'Soochow', 'Everbright', 'China Merchants', 'Ping An', 'Futu',
    'Vickers', 'Nomura', 'CLSA', 'Mizuho', 'Daiwa', 'Credit Suisse',
    'Deutsche Bank', 'BOCOM', 'ICBC International', 'ABC International',
    'CEB', 'CNM', 'SBI', 'Prudential', 'Orient Securities', 'Reliance', 'Fosun',
    'Amber', 'Hooray', 'DDM', 'Tengard', 'Caida', 'Giraffe', 'United Securities',
    'Nova', 'Alpha Financial', 'Glory Sun', 'I WIN', 'Runderstone', 'MORTON',
    'Rifa', 'Yuet Sheung', 'Mont Avenir', 'Arta', 'MIB Securities',
    'UOB Kay Hian', 'J.P. Morgan', 'Goldman Sachs', 'UBS', 'Jefferies',
    'CGS International', 'CMBC', 'Eddid', 'Taiping', 'SPDB',
    'Zhongtai', 'CES Capital', 'Opus', 'Platinum', 'Sigma', 'Marshall Wace',
    'Bailian', 'Fulbright', 'Infinium', 'REDSUN', 'Pulse Wealth', 'Kaiser',
    'SHK HK', 'VMS', 'Opulence', 'Edmond', 'Zion', 'Huajin', 'Golden Mountain',
    'Yuehai', 'Kingsway', 'BOCI', 'Metaverse', 'VBG Capital',
    'CNI Securities Group', 'Direct Profit Enterprises',
]

s = requests.Session()
s.headers.update({'User-Agent': UA})
found = 0

for idx, (orig_i, x) in enumerate(needs):
    code = x['code']
    name = x['name']
    date_str = x['date']
    url = x.get('pdf_url')
    
    print(f'[{idx+1}/{len(needs)}] {code} {name}', end=' ', flush=True)
    
    if not url:
        print('no-pdf')
        continue
    
    try:
        resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
    except:
        print('✗ dl')
        continue
    
    try:
        agent = None
        n_pages = doc.page_count
        
        # Phase 1: Text search on all pages
        text = ' '.join(doc[pg].get_text() for pg in range(min(n_pages, 10)))
        tl = text.lower()
        for kn in KNOWN_SHORT:
            if kn.lower() in tl:
                if name and len(name) > 3 and name in kn:
                    continue
                agent = kn
                break
        
        # Phase 2: Targeted OCR on pages with 'Placing Agent' mention
        if not agent:
            # Find which pages mention 'placing agent'
            target_pages = set()
            for pg_num in range(min(n_pages, 8)):
                try:
                    pt = doc[pg_num].get_text().lower()
                    if 'placing agent' in pt:
                        target_pages.add(pg_num)
                except:
                    pass
            # Also always scan pages 0-1
            target_pages.update([0, 1])
            target_pages = sorted(target_pages)[:5]  # Max 5 pages
            
            for pg_num in target_pages:
                try:
                    page = doc[pg_num]
                    # Use smaller matrix to reduce memory
                    mat = pymupdf.Matrix(1.5, 1.5)
                    pix = page.get_pixmap(matrix=mat)
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    if pix.n == 4:
                        img = img[:, :, :3]
                    
                    rdr = get_reader()
                    if rdr is None:
                        break
                    lines = rdr.readtext(img, detail=0, paragraph=False)
                    ot = ' '.join(lines).lower()
                    
                    for kn in KNOWN_SHORT:
                        if kn.lower() in ot:
                            if name and len(name) > 3 and name in kn:
                                continue
                            # Find the actual line containing this agent
                            for li in lines:
                                if kn.lower() in li.lower():
                                    agent = re.sub(r'\s+', ' ', li).strip('.,;: ')
                                    # Truncate at common delimiters
                                    for delim in [', The ', ', the ', ', and ', '. The ', '\n', ', a ']:
                                        if delim in agent:
                                            agent = agent.split(delim)[0].strip()
                                    if 8 < len(agent) < 70:
                                        break
                            if agent:
                                break
                    if agent:
                        break
                except Exception as e:
                    continue
            
            # Cleanup
            del pix, img
            gc.collect()
        
        doc.close()
        
        if agent:
            al = agent.lower()
            # Reject garbage
            garbage = ['reference is made', 'proposed increase', 'by order of',
                       'subject to the', 'pursuant to', 'general mandate',
                       'placing agent to the', 'the board', 'announcement',
                       'company placing agent']
            if not any(g in al for g in garbage) and 10 < len(agent) < 70:
                p[orig_i]['placing_agent'] = agent
                found += 1
                print(f'→ {agent[:55]}')
            else:
                print('✗ garbage')
        else:
            print('✗')
            
    except Exception as e:
        print(f'✗ err:{str(e)[:30]}')
        try:
            doc.close()
        except:
            pass
        gc.collect()
    
    if (idx + 1) % 25 == 0:
        try:
            tmp = F + '.tmp'
            json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            os.replace(tmp, F)
            print(f'  [Saved: {found}]')
        except:
            pass
    sys.stdout.flush()

# Final save
try:
    tmp = F + '.tmp'
    json.dump(p, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    os.replace(tmp, F)
except:
    pass

wa = sum(1 for x in p if x.get('placing_agent'))
print(f'\nDone: {found} new, {wa}/402 ({wa/402*100:.1f}%)')
