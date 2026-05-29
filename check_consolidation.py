"""Check 27 extreme py_pct stocks for HKEX share consolidation announcements."""
import requests, json, time, sys
from bs4 import BeautifulSoup

EXTREME = [
    '00117','00326','00465','00622','00679','00745','00784','00894',
    '01228','01300','01396','01570','01716','01747','01757','02339',
    '02427','02442','03938','06869','08239','08460','08507','08603',
    '08611','09929','09963'
]

# HK Keywords for share consolidation
KW = [
    'share consolidation', 'capital reorganisation', 'capital reorganization',
    'subdivision of shares', 'subdivision of',
    '合併股份', '股份合併', '並股', '合併', '重組股本',
    'change in board lot', 'par value',
]

def check_stock(code):
    """Check HKEX announcements for a stock code."""
    for kw in KW:
        try:
            r = requests.get(
                'https://www1.hkexnews.hk/search/titlesearch.xhtml',
                params={
                    'lang': 'en', 'stock': code,
                    'from': '2023-01-01', 'to': '2026-05-29',
                    'title': kw, 'category': '0',
                    'market': 'SEHK', 'documentType': '-1',
                },
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=15
            )
            if 'Total records found: 0' not in r.text:
                import re
                m = re.search(r'Total records found: (\d+)', r.text)
                count = int(m.group(1)) if m else 0
                if count > 0:
                    soup = BeautifulSoup(r.text, 'html.parser')
                    titles = []
                    for row in soup.select('tr.row0, tr.row1'):
                        cells = row.find_all('td')
                        if cells:
                            titles.append(cells[0].get_text(strip=True)[:100])
                    return f'CONFIRMED ({count} records, kw={kw}): {titles[0] if titles else "?"}'
        except Exception as e:
            pass
        time.sleep(0.3)
    return 'NOT FOUND'

if __name__ == '__main__':
    confirmed = []
    not_found = []
    for i, code in enumerate(EXTREME):
        print(f'[{i+1}/27] {code}...', end=' ', flush=True)
        result = check_stock(code)
        print(result)
        if result.startswith('CONFIRMED'):
            confirmed.append((code, result))
        else:
            not_found.append(code)
    
    print(f'\n=== RESULTS ===')
    print(f'CONFIRMED: {len(confirmed)}')
    for c, r in confirmed:
        print(f'  {c}: {r}')
    print(f'NOT FOUND: {len(not_found)}')
    for c in not_found:
        print(f'  {c}')
