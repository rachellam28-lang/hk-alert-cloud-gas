"""Feed Webb-site pnotes (placing notes) into breakthrough detector.
Webb-site pnotes have structured prices: unit_price field.
"""
import sys, json
from pathlib import Path
from datetime import date

PROJ = Path(__file__).parent.parent
sys.path.insert(0, str(PROJ))

from scanner.breakthrough_detector import load_price_cache, save_price_cache, export_breakthroughs_json

# Find Webb-site summary — auto-locate from project root
PROJECT_ROOT = Path(__file__).parent.parent
summary = PROJECT_ROOT / "data" / "webb_site" / "summary.json"
if not summary.exists():
    print(f"No Webb-site summary at {summary}")
    sys.exit(1)
print(f"Using: {summary}")
data = json.loads(summary.read_text(encoding='utf-8'))

sources = data.get('sources', {})
pnotes = sources.get('pnotes', {})

if not pnotes:
    print("No pnotes data!")
    sys.exit(1)

top_entries = pnotes.get('top', [])
print(f"Pnotes entries: {len(top_entries)}")

cache = load_price_cache()
added = 0

for p in top_entries:
    code = str(p.get('code', '')).strip()
    if not code:
        continue
    # Pad to 5 digits
    code = code.zfill(5)
    price_val = p.get('price')
    
    if price_val is None or price_val == '?':
        continue
    
    try:
        price = float(price_val)
    except:
        continue
    
    if price <= 0:
        continue
    
    name = p.get('name', '')
    
    # Determine type based on ratio or source
    ptype = 'placement'  # Default, most pnotes are placements
    
    if code not in cache:
        cache[code] = []
    
    # Check for duplicates
    today = date.today().isoformat()
    existing = [e for e in cache[code] if e['type'] == ptype and e.get('date','')[:10] == today[:10]]
    if existing:
        print(f"  {code} ({name}): already cached")
        continue
    
    cache[code].append({
        'type': ptype,
        'price': price,
        'date': today,
        'title': f"Webb-site pnote: {name}",
        'link': f"https://webb-site.com/dbpub/subscribe.asp?c={code}",
    })
    added += 1
    print(f"  ✓ {code} {name}: @{price}")

if added:
    save_price_cache(cache)
    print(f"\nAdded {added} new prices")
else:
    print("\nNo new prices (all already cached)")

print(f"Cache: {len(cache)} stocks")
export_breakthroughs_json()
