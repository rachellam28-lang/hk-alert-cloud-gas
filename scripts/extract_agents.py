#!/usr/bin/env python3
"""Extract placing agents from HKEX PDFs — uses title search for historical + ncms feed for recent.
Handles both old and new events. Cleans agent names.
"""
import json, re, sys, os, time
from urllib.request import urlopen, Request, build_opener, HTTPCookieProcessor
from urllib.parse import urlencode
from http.cookiejar import CookieJar
import pymupdf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PLACEMENTS_FILE = os.path.join(DATA_DIR, "placements_enriched.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

NEEDS_AGENT_KW = ['配售', '供股', '先舊後新']
PLACEMENT_KW = ['PLACING', 'PLACEMENT', 'RIGHTS', 'SUBSCRIPTION',
                '配售', '供股', '認購', '發行', 'MANDATE', 'TOP-UP']

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
                'tf', 'sfg', 'cni', 'get', 'vb', 'roofer', 'jakota', 'black', 'marble']


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


def search_hkex_title(code, date_str):
    """Search HKEX by stock code + date using title search form."""
    try:
        dd, mm, yyyy = date_str.split('/')
        from_date = f"{yyyy}{mm}{dd}"
        to_date = from_date
        # Also search 2 days before/after
        from_d = f"{yyyy}{mm}{int(dd):02d}"
    except:
        return []

    cj = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))
    opener.addheaders = [('User-Agent', UA)]

    # Get session
    try:
        resp = opener.open("https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=EN", timeout=20)
        html = resp.read().decode('utf-8', errors='replace')
    except Exception:
        return []

    vs_match = re.search(r'javax\.faces\.ViewState.*?value="([^"]+)"', html)
    if not vs_match:
        return []
    viewstate = vs_match.group(1)

    # POST to set date range
    fa_match = re.search(r'<form[^>]*action="([^"]+)"', html)
    form_action = fa_match.group(1) if fa_match else '/search/titlesearch.xhtml'
    post_url = f"https://www1.hkexnews.hk{form_action}"

    # Expand date range by ±7 days to catch filings near the event date
    from_dt = f"{yyyy}{int(mm)-1 if int(mm)>1 else 12:02d}{int(dd):02d}"
    to_dt = f"{yyyy}{int(mm)+1 if int(mm)<12 else 1:02d}{int(dd):02d}"
    # Actually use ±3 days
    try:
        opener.open(post_url, data=urlencode({
            'j_idt10': 'j_idt10',
            'j_idt10:loadMoreRange': '300',
            'javax.faces.ViewState': viewstate,
            'from': from_date,
            'to': to_date,
        }).encode(), timeout=20)
    except Exception:
        pass

    # Now query by stock code
    # Re-fetch for fresh ViewState
    try:
        resp2 = opener.open("https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=EN", timeout=15)
        html2 = resp2.read().decode('utf-8', errors='replace')
        vs2 = re.search(r'javax\.faces\.ViewState.*?value="([^"]+)"', html2)
        if not vs2:
            return []
        viewstate2 = vs2.group(1)
    except Exception:
        return []

    # API call with stock ID
    code_int = str(int(code))
    params = {
        "sortDir": "0", "sortByOptions": "DateTime", "category": "0",
        "market": "SEHK", "stockId": code_int, "documentType": "-1",
        "fromDate": from_date, "toDate": to_date,
        "title": "", "searchType": "0",
        "t1code": "-2", "t2Gcode": "-2", "t2code": "-2",
        "rowRange": "300", "lang": "E",
    }
    api_url = "https://www1.hkexnews.hk/search/titleSearchServlet.do?" + urlencode(params)

    req = Request(api_url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
        "X-Requested-With": "XMLHttpRequest",
    })

    try:
        resp = opener.open(req, timeout=30)
        raw = json.loads(resp.read())
        result = json.loads(raw.get("result", "null") or "null")
        if not result:
            return []
        results = []
        for r in result:
            title = r.get("TITLE", "")
            file_link = r.get("FILE_LINK", "")
            if file_link:
                pdf_url = "https://www1.hkexnews.hk" + file_link.replace("/apps/", "/listedco/listconews/sehk/")
                results.append((pdf_url, title))
        return results
    except Exception:
        return []


def search_hkex_feed(code, date_str):
    """Search recent ncms/json/eds feed (last ~2 weeks)."""
    try:
        dd, mm, yyyy = date_str.split('/')
        target_date = f"{dd}/{mm}/{yyyy}"
    except:
        return []

    results = []
    for page in range(1, 25):
        url = f"https://www.hkexnews.hk/ncms/json/eds/lcisehk7relsde_{page}.json"
        try:
            resp = urlopen(Request(url, headers={"User-Agent": UA}), timeout=12)
            data = json.loads(resp.read())
        except Exception:
            break

        news_list = data.get("newsInfoLst", [])
        if not news_list:
            break

        for row in news_list:
            stock_codes = str(row.get("t1Code", ""))
            code_clean = code.lstrip('0') or '0'
            if code not in stock_codes and code_clean not in stock_codes:
                continue
            if target_date not in str(row.get("relTime", "")):
                continue
            file_link = str(row.get("fileLink", ""))
            if file_link.endswith('.pdf'):
                results.append((file_link, str(row.get("title", "")), str(row.get("relTime", ""))))

        if data.get("maxNumOfFile", 0) <= page:
            break
    return results


def extract_agent_from_pdf(pdf_url, stock_name):
    try:
        resp = urlopen(Request(pdf_url, headers={"User-Agent": UA}), timeout=30)
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

    # Find company names
    COMPANY_PAT = re.compile(
        r'([A-Z][A-Za-z\s&.,()\'-]{5,80}?\s+(?:Limited|LIMITED|LimiTeD|Ltd\.?|Inc\.?|'
        r'Corp\.?|Corporation|Group|Holdings|International|Capital|Securities|Finance|'
        r'Financial|Bank|Partners|Asia|HK|Hong\s+Kong))|'
        r'([^\n\r，,]{2,40}(?:有限公司|股份有限公司|證券有限公司|金融有限公司|資本有限公司|'
        r'融資有限公司|企業有限公司|集團有限公司|控股有限公司|銀行))',
        re.MULTILINE)
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

    # Fallback: paragraph-level search
    for para in text.split('\n\n'):
        if re.search(r'(?:P|p)lacing\s+(?:A|a)gent|配售代理', para):
            for m in COMPANY_PAT.finditer(para):
                result = clean_agent(m.group(0).strip(), stock_name)
                if result:
                    return result
    return clean_agent(best, stock_name) if best else None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', type=int, default=0, help='Batch number (1-N), 0=all')
    ap.add_argument('--batch-size', type=int, default=25)
    args = ap.parse_args()

    print("Loading placements...", flush=True)
    with open(PLACEMENTS_FILE, encoding='utf-8') as f:
        placements = json.load(f)

    needs = [p for p in placements
             if not p.get('placing_agent')
             and any(kw in p.get('method', '') for kw in NEEDS_AGENT_KW)]

    # Batch slicing
    if args.batch > 0:
        start = (args.batch - 1) * args.batch_size
        end = start + args.batch_size
        needs = needs[start:end]
        print(f"Batch {args.batch}: items {start+1}-{min(end, len(needs))} of {len(needs)} total")
    else:
        print(f"Total: {len(placements)}, Need: {len(needs)}, Have: {len(placements)-len(needs)}")

    print()

    found = 0
    for i, p in enumerate(needs):
        code = p['code']
        date_str = p['date']
        name = p['name']

        # Skip if already processed this run
        if p.get('placing_agent'):
            continue

        # Quick check: is date recent enough for feed?
        try:
            dd, mm, yyyy = date_str.split('/')
            from datetime import date, timedelta
            evt_date = date(int(yyyy), int(mm), int(dd))
            is_recent = (date.today() - evt_date).days <= 14
        except:
            is_recent = False

        print(f"[{i+1}/{len(needs)}] {code} {name} ({date_str})", end=' ', flush=True)

        # Try feed first for recent, title search for older
        if is_recent:
            results = search_hkex_feed(code, date_str)
            if results:
                results = [(fl, t, rt) for fl, t, rt in results]
            else:
                results = search_hkex_title(code, date_str)
                results = [(fl, t, '') for fl, t in results]
        else:
            results = search_hkex_title(code, date_str)
            results = [(fl, t, '') for fl, t in results]

        if not results:
            print("no filings")
            time.sleep(0.3)
            continue

        # Filter placement-related
        placement_results = [r for r in results
                            if any(kw in str(r[1]).upper() for kw in PLACEMENT_KW)]
        if not placement_results:
            placement_results = results[:3]

        agent = None
        for r in placement_results[:3]:
            pdf_url = r[0]
            agent = extract_agent_from_pdf(pdf_url, name)
            if agent:
                break
            time.sleep(0.2)

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
            print(f"  [Saved: {found}]")

        time.sleep(1.0)  # HKEX rate limit

    with open(PLACEMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(placements, f, ensure_ascii=False, indent=2)

    total = sum(1 for p in placements if p.get('placing_agent'))
    print(f"\nDone: {found} new, {total}/{len(placements)} have agents")


if __name__ == '__main__':
    main()
