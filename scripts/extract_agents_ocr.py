#!/usr/bin/env python3
"""OCR extraction with atomic writes + batch processing."""
import json, os, re, sys, time
import requests, pymupdf, numpy as np
import easyocr

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PLACEMENTS_FILE = os.path.join(DATA_DIR, "placements_enriched.json")
TMP_FILE = PLACEMENTS_FILE + ".tmp"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

print("Loading EasyOCR...", flush=True)
READER = easyocr.Reader(['en', 'ch_sim'], gpu=False)
print("Ready.", flush=True)


def ocr_page(pdf_url):
    """Download PDF, render page 1, OCR full text."""
    try:
        resp = requests.get(pdf_url, headers={"User-Agent": UA}, timeout=25)
        resp.raise_for_status()
    except Exception:
        return []
    
    try:
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
        page = doc[0]
        mat = pymupdf.Matrix(3, 3)
        pix = page.get_pixmap(matrix=mat)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        doc.close()
    except Exception:
        return []
    
    try:
        return READER.readtext(img, detail=0, paragraph=False)
    except Exception:
        return []


def find_agent(lines):
    """Find placing agent from OCR text lines."""
    for i, line in enumerate(lines):
        upper = line.upper().replace(' ', '')
        if any(kw in upper for kw in ['SOLEPLACINGAGENT', 'PLACINGAGENT',
                                        'SOLEOVERALLCOORDINATOR', 'CAPITALMARKETINTERMEDIARY']):
            for j in range(i+1, min(len(lines), i+5)):
                cand = lines[j].strip()
                if any(kw in cand.upper() for kw in
                       ['SECURITIES', 'CAPITAL', 'FINANCE', 'BANK', 'ASIA',
                        'INTERNATIONAL', 'PARTNERS', 'GROUP', 'LIMITED', 'LTD',
                        '證券', '金融', '資本', '銀行']):
                    cand = re.sub(r'\s+', ' ', cand).strip('.,;:')
                    if 6 < len(cand) < 70:
                        return cand
    return None


def main():
    with open(PLACEMENTS_FILE, encoding='utf-8') as f:
        placements = json.load(f)
    
    NEEDS_KW = ['配售', '供股', '先舊後新']
    needs = [(i, p) for i, p in enumerate(placements)
             if not p.get('placing_agent') and p.get('pdf_url')
             and any(kw in p.get('method', '') for kw in NEEDS_KW)]
    
    print(f"Processing {len(needs)} PDFs with OCR...")
    
    found = 0
    for idx, (orig_i, p) in enumerate(needs):
        code = p['code']
        name = p['name']
        
        print(f"[{idx+1}/{len(needs)}] {code} {name}", end=' ', flush=True)
        
        lines = ocr_page(p['pdf_url'])
        if not lines:
            print("✗ OCR fail")
            continue
        
        agent = find_agent(lines)
        
        if agent and any(kw in agent.lower() for kw in
                         ['securities', 'capital', 'finance', 'bank', 'asia',
                          'international', 'partners', 'group', 'limited', 'ltd']):
            if name and len(name) > 3 and name in agent:
                print(f"✗ self: {agent}")
                continue
            placements[orig_i]['placing_agent'] = agent
            found += 1
            print(f"→ {agent}")
        else:
            print("✗")
        
        if (idx + 1) % 10 == 0:
            # Atomic write
            with open(TMP_FILE, 'w', encoding='utf-8') as f:
                json.dump(placements, f, ensure_ascii=False, indent=2)
            os.replace(TMP_FILE, PLACEMENTS_FILE)
            print(f"  [Saved: {found}]")
    
    # Final save
    with open(TMP_FILE, 'w', encoding='utf-8') as f:
        json.dump(placements, f, ensure_ascii=False, indent=2)
    os.replace(TMP_FILE, PLACEMENTS_FILE)
    
    total = sum(1 for p in placements if p.get('placing_agent'))
    print(f"\nDone: {found} new, {total}/{len(placements)} have agents")


if __name__ == '__main__':
    main()
