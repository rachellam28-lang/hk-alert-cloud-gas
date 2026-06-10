#!/usr/bin/env python3
"""Extract PDF text+OCR for LLM agent identification."""
import json, os, requests, pymupdf, numpy as np, easyocr, sys
sys.path.insert(0, '/tmp/hkex-filing-scraper/src')
from hkex_scraper.api import fetch_chunk_via_api

reader = easyocr.Reader(['en', 'ch_sim'], gpu=False)
p = json.load(open('data/placements_enriched.json', encoding='utf-8'))
UA = 'Mozilla/5.0'

NEEDS_KW = ['配售', '供股', '先舊後新']
SKIP_KW = ['代價發行']
needs = [(i, x) for i, x in enumerate(p)
         if not x.get('placing_agent')
         and any(k in x.get('method', '') for k in NEEDS_KW)
         and not any(k in x.get('method', '') for k in SKIP_KW)]

print(f'{len(needs)} events to extract')

s = requests.Session()
s.headers.update({'User-Agent': UA})
extracts = []

for idx, (orig_i, x) in enumerate(needs):
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
        except:
            pass

    print(f'[{idx+1}/{len(needs)}] {code} {name}', end=' ', flush=True)

    text = ''
    ocr_text = ''

    if url:
        try:
            resp = requests.get(url, headers={'User-Agent': UA}, timeout=20)
            doc = pymupdf.open(stream=resp.content, filetype='pdf')

            text = ' '.join(doc[pg].get_text() for pg in range(min(doc.page_count, 15)))

            ocr_parts = []
            for pg_num in range(min(3, doc.page_count)):
                try:
                    page = doc[pg_num]
                    mat = pymupdf.Matrix(3, 3)
                    pix = page.get_pixmap(matrix=mat)
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    if pix.n == 4:
                        img = img[:, :, :3]
                    lines = reader.readtext(img, detail=0, paragraph=False)
                    ocr_parts.append(' '.join(lines))
                except:
                    pass
            ocr_text = ' | '.join(ocr_parts)
            doc.close()
            print('ok')
        except Exception as e:
            print(f'err: {e}')

    extracts.append({
        'idx': orig_i,
        'code': code,
        'name': name,
        'date': date_str,
        'method': x.get('method', ''),
        'text': text[:3000],
        'ocr': ocr_text[:2000],
        'url': url or '',
    })

    if (idx + 1) % 20 == 0:
        json.dump(extracts, open('data/extracts_for_llm.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'  [Saved {len(extracts)}]')

json.dump(extracts, open('data/extracts_for_llm.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\nDone: {len(extracts)} extracts saved')
