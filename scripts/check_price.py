import json, re

with open('data/announcements.json') as f:
    data = json.load(f)

placements = [d for d in data if '配股' in d.get('types', [])]
print(f'配股: {len(placements)}')

has_price = 0
for p in placements:
    t = p['title'].upper()
    # Find prices like HK$0.50, $0.50, AT HK$0.50, HKD 0.50
    prices = re.findall(r'(?:HK\$?\s*|HKD\s*|AT\s+\$?\s*)(\d+\.?\d*)', t)
    if prices:
        has_price += 1
        if has_price <= 10:
            print(f'{p["code"]} {p["name"][:14]} prices={prices} | {t[:100]}')
    elif has_price <= 2:
        print(f'{p["code"]} {p["name"][:14]} NO PRICE | {t[:100]}')

print(f'\n有價: {has_price}/{len(placements)}')
print(f'無價: {len(placements)-has_price}/{len(placements)}')
