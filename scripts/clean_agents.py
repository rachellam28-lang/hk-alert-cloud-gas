#!/usr/bin/env python3
"""Clean bad agents: remove stock names, text fragments, add prefixes."""
import json, re

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
    kwlist = ['securities','capital','finance','bank','asia','hong kong',
              'partners','group','holdings','international','limited',
              'first','grand','fortune','central','ruibang','morgan',
              'stanley','bnp','paribas','macquarie','dbs','kgi',
              'guotai','aristo','cheong','lee','wanhai','advent','patrons',
              'theia','sfghk','gransing','suncorp','uzen','kingston','kingkey',
              'pinestone','zijing','cni','vb','step','wide','astrum','daokou',
              'constance','nice','wealth','tiger','faith','direct','profit',
              'tf','sfg','roofer','jakota','black','marble','ruibang',
              'tfi','central']
    if not any(kw in name.lower() for kw in kwlist):
        if not re.search(r'[\u4e00-\u9fff]', name):
            return None
    return name.strip()

with open('data/placements_enriched.json') as f:
    data = json.load(f)

cleaned = removed = 0
for p in data:
    old = p.get('placing_agent')
    if old:
        new = clean_agent(old, p.get('name',''))
        if new and new != old:
            p['placing_agent'] = new
            cleaned += 1
            print(f'  CLEAN: {p["code"]} → {new}')
        elif not new:
            p['placing_agent'] = None
            removed += 1
            print(f'  REMOVE: {p["code"]} {old[:40]}')

print(f'Cleaned: {cleaned}, Removed: {removed}')
remaining = sum(1 for p in data if p.get('placing_agent'))
print(f'Remaining: {remaining}/{len(data)}')

with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
