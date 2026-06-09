#!/usr/bin/env python3
"""Auto-fill HKEX Excel template with placement data + westock enrichment"""
import json, openpyxl, subprocess, re
from datetime import datetime
from collections import defaultdict

# Load our enriched data
with open('data/placements_enriched.json', 'r', encoding='utf-8') as f:
    placements = json.load(f)

# Run trade_signal to get conviction
import sys; sys.path.insert(0, 'scripts')
from gen_rights_page import trade_signal, stock_events
for p in placements:
    p['trade'] = trade_signal(p)

# Sort by conviction (highest first), take top 80
sorted_p = sorted(placements, key=lambda p: p['trade'].get('conviction', 0), reverse=True)
top = sorted_p[:80]

print(f"Filling Excel with top {len(top)} conviction events...")

# Open template
template_path = r'C:\Users\Administrator\Downloads\HKEX發股供股清單 精簡詳細雙版本.xlsx'
wb = openpyxl.load_workbook(template_path)

# === Fill A_精簡版 ===
ws_a = wb['A_精簡版_機器填充用']
# Clear existing data (keep header)
for row in range(ws_a.max_row, 1, -1):
    for col in range(1, ws_a.max_column + 1):
        ws_a.cell(row=row, column=col).value = None

# Write header
headers_a = ['股票代號', '公告日期', '類型碼', '新股數', '發行價', '股本後', '攤薄%', '折溢價%', '集資額', '完成日期', '狀態']
for i, h in enumerate(headers_a, 1):
    ws_a.cell(row=1, column=i, value=h)

# Map our categories to type codes
type_map = {
    '供股': 'Rights',
    '配售': 'Placing_GM',
    '代價發行': 'Issue_GM_Debt',
    '先舊後新': 'Placing_SM',
}

# Write data
for row_i, p in enumerate(top, 2):
    disc = p.get('discount_pct')
    ws_a.cell(row=row_i, column=1, value=p['code'])
    ws_a.cell(row=row_i, column=2, value=p['date_parsed'])
    ws_a.cell(row=row_i, column=3, value=type_map.get(p['category'], p['category']))
    ws_a.cell(row=row_i, column=4, value=p['shares'])
    ws_a.cell(row=row_i, column=5, value=p['price_num'] if p['price_num'] > 0 else p['price'])
    ws_a.cell(row=row_i, column=6, value='')  # 股本後 — need HKEX
    ws_a.cell(row=row_i, column=7, value=p['pct_num'] if p['pct_num'] > 0 else '')
    ws_a.cell(row=row_i, column=8, value=round(disc, 1) if disc is not None else '')
    ws_a.cell(row=row_i, column=9, value=p['amount_num'])
    ws_a.cell(row=row_i, column=10, value='')  # 完成日期 — need HKEX
    ws_a.cell(row=row_i, column=11, value='進行中' if p['date_parsed'] > '2026-05-01' else '待確認')

# === Fill B_詳細版 ===
ws_b = wb['B_詳細版_人工拆解用']
for row in range(ws_b.max_row, 1, -1):
    for col in range(1, ws_b.max_column + 1):
        ws_b.cell(row=row, column=col).value = None

headers_b = ['股票代號', '公告日期', '文件類型', '事件簡述', 'HKEX_PDF連結', '新股數量', '發行價',
             '股本前', '股本後', '攤薄%', '折溢價%', '折溢價基準', '集資額毛', '集資額淨',
             '用途', '認購人／配售對象', '完成日期', '股東會日期', '狀態', '備註']
for i, h in enumerate(headers_b, 1):
    ws_b.cell(row=1, column=i, value=h)

for row_i, p in enumerate(top, 2):
    disc = p.get('discount_pct')
    t = p.get('trade', {})
    
    ws_b.cell(row=row_i, column=1, value=p['code'])
    ws_b.cell(row=row_i, column=2, value=p['date_parsed'])
    ws_b.cell(row=row_i, column=3, value=type_map.get(p['category'], p['category']))
    ws_b.cell(row=row_i, column=4, value=f"{p['category']}: {p['purpose'][:80]}")
    ws_b.cell(row=row_i, column=5, value='')  # PDF link
    ws_b.cell(row=row_i, column=6, value=p['shares'])
    ws_b.cell(row=row_i, column=7, value=p['price_num'] if p['price_num'] > 0 else p['price'])
    ws_b.cell(row=row_i, column=8, value='')
    ws_b.cell(row=row_i, column=9, value='')
    ws_b.cell(row=row_i, column=10, value=p['pct_num'] if p['pct_num'] > 0 else '')
    disc_label = f"{round(disc,1)}%" if disc is not None else ''
    ws_b.cell(row=row_i, column=11, value=disc_label)
    ws_b.cell(row=row_i, column=12, value='市價' if p.get('market_price', 0) > 0 else '')
    ws_b.cell(row=row_i, column=13, value=p['amount_num'])
    ws_b.cell(row=row_i, column=14, value=p['amount_num'])  # 集資額淨 ≈ 集資額毛
    ws_b.cell(row=row_i, column=15, value=p['purpose'][:120])
    ws_b.cell(row=row_i, column=16, value='')  # 認購人 — need HKEX
    ws_b.cell(row=row_i, column=17, value='')
    ws_b.cell(row=row_i, column=18, value='')
    ws_b.cell(row=row_i, column=19, value='進行中' if p['date_parsed'] > '2026-05-01' else '待確認')
    
    # 備註: trading signal + patterns
    notes = f"{t.get('signal','')} | {t.get('thesis','')}"
    ws_b.cell(row=row_i, column=20, value=notes[:200])

# Save
outpath = r'C:\Users\Administrator\Desktop\automatic\ccass-debug\data\HKEX_供配股_自動填充.xlsx'
wb.save(outpath)
print(f"\nSaved: {outpath}")
print(f"A_精簡版: {len(top)} rows filled")
print(f"B_詳細版: {len(top)} rows filled")
print(f"\n仍未自動化的欄位 (需 HKEX PDF):")
print("  - 完成日期 (需爬HKEX公告)")
print("  - 股本前/後 (需FF305月報表)")
print("  - 認購人/配售對象 (需PDF提取)")
print("  - HKEX_PDF連結 (需Title Search)")
