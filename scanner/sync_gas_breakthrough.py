"""Sync GAS recentCorps → breakthrough price cache.
Downloads HKEX PDFs and extracts placement/rights prices from raw text.
"""
import json, sys, re, time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).parent.parent))
from scanner.breakthrough_detector import save_price_cache, load_price_cache, export_breakthroughs_json

GAS_URL = "https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec?format=json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Price extraction patterns from HKEX PDF raw text
PRICE_PATTERNS = [
    # "配售價為每股HK$0.38" / "placing price of HK$0.38 per share"
    (re.compile(r'(?:配售價|placing\s*price|offer\s*price|subscription\s*price)[^$]*HK\$\s*(\d+\.?\d*)', re.I), 'placement'),
    # "供股價為每股HK$0.12" / "rights issue price of HK$0.12"
    (re.compile(r'(?:供股價|rights?\s*issue\s*price|subscription\s*price)[^$]*HK\$\s*(\d+\.?\d*)', re.I), 'rights'),
    # "每股配售價HK$0.38"
    (re.compile(r'每股(?:配售價|供股價)[^$]*HK\$\s*(\d+\.?\d*)', re.I), 'any'),
    # "at the subscription price of HK$0.38"
    (re.compile(r'(?:at|subscription|placing|offer)\s+(?:the\s+)?(?:price|subscription\s+price)\s+of\s+HK\$\s*(\d+\.?\d*)', re.I), 'any'),
]

def extract_price_from_pdf(pdf_url: str, expected_type: str) -> float | None:
    """Download PDF and extract placement/rights issue price."""
    try:
        req = Request(pdf_url, headers={"User-Agent": UA})
        resp = urlopen(req, timeout=20)
        data = resp.read()
        text = data.decode('latin-1', errors='replace')
    except Exception as e:
        print(f"    download err: {e}")
        return None
    
    # Remove PDF binary noise - only keep readable text
    # Focus on text between stream/endstream markers
    text_parts = re.findall(r'\((.*?)\)', text)
    clean_text = ' '.join(text_parts)
    
    for pat, ptype in PRICE_PATTERNS:
        matches = pat.findall(clean_text)
        if matches:
            prices = [float(m) for m in matches if 0.001 < float(m) < 10000]
            if prices:
                # For specific types, prefer exact match
                if ptype == expected_type or ptype == 'any':
                    return prices[0]  # First match is usually the right one
    
    # Fallback: find any HK$ price near "配售" or "供股" context
    fallback = re.compile(r'(?:配售|供股|placing|rights|subscription).{0,100}HK\$\s*(\d+\.?\d*)', re.I)
    m = fallback.search(clean_text)
    if m:
        price = float(m.group(1))
        if 0.001 < price < 10000:
            return price
    
    return None


def main():
    # Fetch GAS data
    print("Fetching GAS data...")
    req = Request(GAS_URL, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as resp:
        gas = json.loads(resp.read().decode("utf-8"))
    
    corps = gas.get("recentCorps", [])
    print(f"Found {len(corps)} recent corporate actions")
    
    cache = load_price_cache()
    added = 0
    
    for corp in corps:
        code = str(corp.get("code", "")).zfill(5)
        ctype = corp.get("type", "")
        
        if ctype not in ("placement", "rights"):
            continue
        
        url = corp.get("url", "")
        corp_date = corp.get("date", "")
        
        if not url:
            continue
        
        # Check if already cached
        if code in cache:
            existing = [e for e in cache[code] if e["type"] == ctype and e["date"] == corp_date]
            if existing:
                print(f"  {code} ({ctype}): already cached")
                continue
        
        print(f"  {code} ({ctype}): downloading PDF...")
        price = extract_price_from_pdf(url, ctype)
        
        if price is None:
            print(f"    no price extracted")
            continue
        
        if code not in cache:
            cache[code] = []
        
        cache[code].append({
            "type": ctype,
            "price": price,
            "date": corp_date,
            "title": corp.get("name", ""),
            "link": url,
        })
        added += 1
        print(f"    ✓ {ctype} @{price}")
        
        time.sleep(1)  # Be gentle
    
    if added:
        save_price_cache(cache)
        print(f"\nSaved {added} new prices to cache")
    
    # Export breakthroughs
    print("\nScanning for breakthroughs...")
    path = export_breakthroughs_json()
    print(f"Done! → {path}")


if __name__ == "__main__":
    main()
