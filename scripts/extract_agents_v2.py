#!/usr/bin/env python3
"""Fast agent extraction using ncms JSON feed — batch search all stocks at once."""
import json, os, sys, time, re
from urllib.request import urlopen, Request
import pymupdf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PLACEMENTS_FILE = os.path.join(DATA_DIR, "placements_enriched.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

AGENT_PAT = re.compile(
    r'(?:P|p)lacing\s+(?:A|a)gent|配售代理|包銷商|Underwriter|'
    r'Sole\s+(?:P|p)lacing|聯合配售代理|Global\s+Coordinator|'
    r'Joint\s+(?:P|p)lacing\s+(?:A|a)gents?',
    re.MULTILINE)

FINANCIAL_KW = ['securities', 'capital', 'finance', 'bank', 'asia', 'hong kong',
                '證券', '金融', '資本', '銀行', '融資', '企業融資', '投資',
                'partners', 'group', 'holdings', 'international', 'limited',
                'first', 'grand', 'fortune', 'central', 'ruibang', 'morgan',
                'stanley', 'bnp', 'paribas', 'macquarie', 'dbs', 'kgi',
                'guotai', 'aristo', 'cheong', 'lee', 'wanhai', 'advent', 'patrons',
                'theia', 'sfghk', 'gransing', 'suncorp', 'uzen', 'kingston', 'kingkey',
                'pinestone', 'zijing', 'cni', 'vb', 'step', 'wide', 'astrum', 'daokou',
                'constance', 'nice', 'wealth', 'tiger', 'faith', 'direct', 'profit',
                'tf', 'sfg', 'get', 'roofer', 'jakota', 'black', 'marble']

COMPANY_PAT = re.compile(
    r'([A-Z][A-Za-z\s&.,()\'\-]{5,80}?\s+(?:Limited|LIMITED|Ltd\.?|Inc\.?|'
    r'Corp\.?|Corporation|Group|Holdings|International|Capital|Securities|Finance|'
    r'Financial|Bank|Partners|Asia|HK|Hong\s+Kong))|'
    r'([^\n\r，,]{2,40}(?:有限公司|股份有限公司|證券有限公司|金融有限公司|資本有限公司|'
    r'融資有限公司|企業有限公司|集團有限公司|控股有限公司|銀行))',
    re.MULTILINE)

PLACEMENT_KW = ['PLACING', 'PLACEMENT', 'RIGHTS', 'SUBSCRIPTION',
                '配售', '供股', '認購', '發行', 'MANDATE', 'TOP-UP']


def clean_agent(raw, stock_name):
    if not raw: return None
    name = ' '.join(str(raw).split())
    for prefix in ['Placing Agent ', 'Placing agent ', 'placing agent ',
                   'Company Placing Agent ', 'Company and ', 'Company ']:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):]
    name = re.sub(r'\s+Shares\.?\s+By order of.*', '', name, flags=re.I)
    name = re.sub(r'\s+Having taken into account.*', '', name, flags=re.I)
    name = re.sub(r'\s+EXCHANGE RISK.*', '', name, flags=re.I)
    name = re.sub(r'\s+\(Formerly known as.*', '', name)
    if stock_name and len(stock_name) > 3 and stock_name in name:
        return None
    if len(name) < 8 or len(name) > 50:
        return None
    if not any(kw in name.lower() for kw in FINANCIAL_KW):
        if not re.search(r'[\u4e00-\u9fff]', name):
            return None
    return name.strip()


def extract_agent_from_pdf(pdf_url, stock_name):
    try:
        resp = urlopen(Request(pdf_url, headers={"User-Agent": UA}), timeout=25)
        pdf_bytes = resp.read()
    except Exception:
        return None
    if len(pdf_bytes) < 100:
        return None
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype='pdf')
        text = ''.join(doc[pg].get_text() for pg in range(min(doc.page_count, 8)))
        doc.close()
    except Exception:
        return None
    if not text.strip():
        return None

    agent_pos = [m.start() for m in AGENT_PAT.finditer(text)]
    if not agent_pos:
        return None

    companies = []
    seen = set()
    for m in COMPANY_PAT.finditer(text):
        name = m.group(0).strip()
        if len(name) < 6 or name.lower() in seen:
            continue
        seen.add(name.lower())
        companies.append((m.start(), name))

    if not companies:
        return None

    best, best_score = None, float('inf')
    for pos, name in companies:
        dist = min(abs(pos - a) for a in agent_pos)
        bonus = -200 if any(k in name.lower() for k in FINANCIAL_KW) else 0
        if dist + bonus < best_score:
            best_score = dist + bonus
            best = name

    if best and best_score < 3000:
        return clean_agent(best, stock_name)

    for para in text.split('\n\n'):
        if re.search(r'(?:P|p)lacing\s+(?:A|a)gent|配售代理', para):
            for m in COMPANY_PAT.finditer(para):
                result = clean_agent(m.group(0).strip(), stock_name)
                if result:
                    return result
    return clean_agent(best, stock_name) if best else None


def main():
    print("Loading placements...", flush=True)
    with open(PLACEMENTS_FILE, encoding='utf-8') as f:
        placements = json.load(f)

    NEEDS_AGENT_KW = ['配售', '供股', '先舊後新']
    needs = [p for p in placements
             if not p.get('placing_agent')
             and any(kw in p.get('method', '') for kw in NEEDS_AGENT_KW)]

    # Build lookup: set of stock codes we need
    needed_codes = set()
    for p in needs:
        code = p['code'].lstrip('0') or '0'
        needed_codes.add(p['code'])
        needed_codes.add(code)

    print(f"Need agents for {len(needs)} events ({len(needed_codes)} unique stocks)")

    # Phase 1: Scan ncms feed pages for matching stocks
    # Map: stock_code -> [(pdf_url, title, date_str)]
    matches = {}  # code -> list of pdf urls
    print("\n=== Phase 1: Scanning ncms feed ===")
    for page in range(1, 35):
        url = f"https://www.hkexnews.hk/ncms/json/eds/lcisehk7relsde_{page}.json"
        try:
            resp = urlopen(Request(url, headers={"User-Agent": UA}), timeout=12)
            data = json.loads(resp.read())
        except Exception as e:
            print(f"  Page {page}: error {e}")
            break

        news_list = data.get("newsInfoLst", [])
        if not news_list:
            print(f"  Page {page}: empty, done scanning")
            break

        found_any = False
        for row in news_list:
            # Stock code is in stock[].sc array, NOT t1Code
            stocks = row.get("stock", [])
            row_codes = set()
            for s in stocks:
                sc = str(s.get("sc", ""))
                row_codes.add(sc)
                row_codes.add(sc.lstrip('0') or '0')
            
            # Check if any of our needed codes match
            matched = row_codes & needed_codes
            if matched:
                fl = str(row.get("webPath", ""))
                title = str(row.get("title", ""))
                rel = str(row.get("relTime", ""))
                if fl.endswith('.pdf'):
                    for mc in matched:
                        if mc not in matches:
                            matches[mc] = []
                        matches[mc].append((fl, title, rel))
                    found_any = True

        if found_any:
            print(f"  Page {page}: {len(news_list)} items, matches so far: {len(matches)} stocks", flush=True)
        time.sleep(0.3)

    print(f"\nFound PDFs for {len(matches)} stocks")

    # Phase 2: For each needed event, try to find matching PDF and extract agent
    print("\n=== Phase 2: Extracting agents from PDFs ===")
    found = 0
    for i, p in enumerate(needs):
        code = p['code']
        code_short = code.lstrip('0') or '0'
        date_str = p['date']
        name = p['name']

        # Get PDFs for this stock
        pdfs = matches.get(code, []) + matches.get(code_short, [])
        if not pdfs:
            # Try direct ncms search for this code
            continue

        # Filter placement-related
        placement_pdfs = [r for r in pdfs if any(kw in str(r[1]).upper() for kw in PLACEMENT_KW)]
        if not placement_pdfs:
            placement_pdfs = pdfs[:5]

        print(f"[{i+1}/{len(needs)}] {code} {name}", end=' ', flush=True)

        agent = None
        for r in placement_pdfs[:5]:
            pdf_url = r[0]
            if not pdf_url.startswith('http'):
                pdf_url = 'https://www1.hkexnews.hk' + pdf_url
            agent = extract_agent_from_pdf(pdf_url, name)
            if agent:
                break
            time.sleep(0.15)

        if agent:
            for pl in placements:
                if pl['code'] == code and pl['date'] == date_str:
                    pl['placing_agent'] = agent
                    break
            found += 1
            print(f"→ {agent}")
        else:
            print("✗")

        if (i + 1) % 10 == 0:
            with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(placements, f, ensure_ascii=False, indent=2)
            print(f"  [Saved: {found} new]")

        time.sleep(0.3)

    with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(placements, f, ensure_ascii=False, indent=2)

    total = sum(1 for p in placements if p.get('placing_agent'))
    print(f"\nDone: {found} new, {total}/{len(placements)} have agents")


if __name__ == '__main__':
    main()
