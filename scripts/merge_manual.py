#!/usr/bin/env python3
"""Merge user's manual tracking data with our enriched placements"""
import json

# User's manually tracked data (from image)
manual_data = [
    {"code": "00476", "name": "科軒動力", "finished_date": "2026-04-24", "new_qty": "3830W",
     "last_price": 0.54, "last_return_pct": 0, "vendor": "-", "note": "Done"},
    {"code": "08120", "name": "國農金融投資", "finished_date": "", "new_qty": "27104.46W",
     "last_price": 1.07, "last_return_pct": 1.9, "vendor": "?控證券", "note": "配60%"},
    {"code": "01153", "name": "佳源服務", "finished_date": "2026-04-24", "new_qty": "60500W",
     "last_price": 0.35, "last_return_pct": 0, "vendor": "寶時證券有限公司", "note": "Done"},
    {"code": "00020", "name": "商湯集團", "finished_date": "2026-04-24", "new_qty": "1700000W",
     "last_price": 2.03, "last_return_pct": 2.01, "vendor": "匯豐", "note": "配56%"},
    {"code": "00524", "name": "長城天下", "finished_date": "", "new_qty": "39385.5W",
     "last_price": 1.07, "last_return_pct": 33.75, "vendor": "一盈證券有限公司", "note": "配股後爆1倍急回"},
    {"code": "01380", "name": "中國金石", "finished_date": "", "new_qty": "15880.702W",
     "last_price": 0.56, "last_return_pct": -3.45, "vendor": "-", "note": ""},
]

# Load our enriched data
with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Merge: for each manual entry, find matching placement and enrich
enriched_count = 0
for m in manual_data:
    code = m['code']
    # Find matching events for this code
    matches = [p for p in data if p['code'] == code]
    for p in matches:
        p['manual_finished_date'] = m['finished_date']
        p['manual_last_price'] = m['last_price']
        p['manual_return_pct'] = m['last_return_pct']
        p['manual_vendor'] = m['vendor']
        p['manual_note'] = m['note']
        p['manual_new_qty'] = m['new_qty']
        enriched_count += 1
        print(f"  {code} {p['name']}: vendor={m['vendor']}, return={m['last_return_pct']}%")

print(f"\nEnriched {enriched_count} events with manual data")

# Save
with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("Saved")
