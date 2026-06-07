"""Scrape HKEX PDFs to extract placement/subscription prices and discounts."""
import json, urllib.request, re, time, os
from io import BytesIO
from PyPDF2 import PdfReader

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(PROJ, 'data', 'announcements.json')

def extract_price_from_pdf(url, code):
    """Extract placement/subscription price and discount from a HKEX PDF."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            pdf_bytes = resp.read()
    except Exception as e:
        return {'error': str(e)}

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        text = ''
        for page in reader.pages[:4]:
            text += (page.extract_text() or '') + '\n'
    except Exception as e:
        return {'error': 'PDF parse: ' + str(e)}

    result = {
        'offer_price': None,
        'closing_price': None,
        'discount_pct': None,
        'premium_pct': None,
        'ratio': None,
    }

    # Extract offer/placing/subscription price
    m = re.search(r'(?:Placing|Subscription|Issue|Offer)\s+Price\s+of\s+HK\$\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'at\s+(?:the\s+)?(?:Placing|Subscription|Issue)\s+Price\s+of\s+HK\$\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'Subscription\s+Price\s+(?:of\s+)?HK\$\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'HK\$\s*(\d+\.?\d*)\s*(?:per|/)\s*(?:Placing|Subscription|Rights|Offer)?\s*Share', text, re.IGNORECASE)
    result['offer_price'] = float(m.group(1)) if m else None

    # Extract closing/reference price
    m = re.search(r'closing\s+price\s+of\s+(?:approximately\s+)?HK\$\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'closing\s+price\s+per\s+Share\s+(?:of|as)\s+(?:approximately\s+)?HK\$\s*(\d+\.?\d*)', text, re.IGNORECASE)
    result['closing_price'] = float(m.group(1)) if m else None

    # Extract discount percentage
    m = re.search(r'discount\s+of\s+(?:approximately\s+)?(\d+\.?\d*)\s*%', text, re.IGNORECASE)
    if m:
        result['discount_pct'] = float(m.group(1))
    elif result['offer_price'] and result['closing_price']:
        result['discount_pct'] = round((1 - result['offer_price'] / result['closing_price']) * 100, 1)

    # Extract premium
    m = re.search(r'premium\s+of\s+(?:approximately\s+)?(\d+\.?\d*)\s*%', text, re.IGNORECASE)
    if m:
        result['premium_pct'] = float(m.group(1))

    return result


def classify_price(result, types_list):
    """Classify placement/rights as high/low based on discount."""
    types_set = set(types_list)
    disc = result.get('discount_pct')
    premium = result.get('premium_pct')
    price = result.get('offer_price')

    if price is None:
        return 'unknown'

    if '供股' in types_set:
        if disc is not None and disc > 30:
            return 'low'
        if premium is not None and premium > 0:
            return 'high'
        return 'neutral'

    if '配股' in types_set:
        if disc is not None and disc > 15:
            return 'low'
        if disc is not None and disc < 5:
            return 'high'
        return 'neutral'

    return 'unknown'


def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    to_process = [d for d in data if ('配股' in d.get('types', []) or '供股' in d.get('types', [])) and d.get('url', '')]
    total = len(to_process)
    print('Processing {} entries...'.format(total))

    updated = 0
    for i, d in enumerate(to_process):
        code = d['code']
        name = d.get('name', '')
        url = d['url']
        print('  [{}/{}] {} {}'.format(i+1, total, code, name[:20]), end=' ', flush=True)

        result = extract_price_from_pdf(url, code)
        price_level = classify_price(result, d.get('types', []))

        d['offer_price'] = result.get('offer_price')
        d['discount_pct'] = result.get('discount_pct')
        d['price_level'] = price_level

        if result.get('error'):
            print('ERR: ' + result['error'][:60])
        elif result.get('offer_price'):
            disc_pct = result.get('discount_pct')
            disc_str = ', disc={}%'.format(disc_pct) if disc_pct is not None else ''
            print('HK${}{} -> {}'.format(result['offer_price'], disc_str, price_level))
        else:
            print('NO PRICE')

        updated += 1
        time.sleep(0.3)

    with open(DATA_PATH, 'w') as f:
        json.dump(data, f, ensure_ascii=False)
    print('\nDone. Updated {} entries.'.format(updated))

    from collections import Counter
    levels = Counter(d.get('price_level', 'unknown') for d in data if d.get('offer_price'))
    print('Price levels: high={}, neutral={}, low={}, unknown={}'.format(
        levels.get('high', 0), levels.get('neutral', 0), levels.get('low', 0), levels.get('unknown', 0)))


if __name__ == '__main__':
    main()
