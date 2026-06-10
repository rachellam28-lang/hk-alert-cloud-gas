#!/usr/bin/env python3
"""Clean up bad agent names."""
import json, re

with open('data/placements_enriched.json', encoding='utf-8') as f:
    placements = json.load(f)

bad_prefixes = [
    'subscribe', 'ubscribe', 'ubscription', 'ubsequent', 'ubstantial', 'ubscriber',
    'acquire, purchase', 'offer to acquire', 'the securities and futures',
    'To the best', 'The Board proposes', 'This announcement', 'Number of Placing',
    'Pursuant to', 'Hong Kong Exchanges', 'The Placing The Board',
    'PROPOSED INCREASE', 'Independent Financial', 'placed', 'LOAN CAPITALISATION',
    'Other Placing Agents', 'References are made', 'Seller',
    'as its financial', 'Acting in concert',
]

cleaned = 0
for p in placements:
    agent = p.get('placing_agent', '')
    if not agent:
        continue
    
    skip = False
    for bp in bad_prefixes:
        if agent.lower().startswith(bp.lower()):
            skip = True
            break
    
    if not skip:
        for bc in ['Hong Kong Exchanges', 'not constitute', 'Morgan Stanley European', 'THE PLACING On', 'THE PLACING The']:
            if bc.lower() in agent.lower():
                skip = True
                break
    
    if not skip and len(agent) > 70:
        skip = True
    
    if not skip:
        fk = ['securities', 'capital', 'finance', 'bank', 'asia', 'international',
              'partners', 'group', 'limited', 'ltd', 'inc', 'investment', 'asset',
              'management', 'corp', 'haitong', 'cicc', 'huatai', 'morgan stanley',
              'citigroup', 'china galaxy', '證券', '金融', '資本']
        if not any(kw in agent.lower() for kw in fk):
            skip = True
    
    if not skip and p['name'] and len(p['name']) > 3 and p['name'] in agent:
        skip = True
    
    if skip:
        p['placing_agent'] = None
        cleaned += 1

agents = [p for p in placements if p.get('placing_agent')]
print(f'Cleaned: {cleaned}, Remaining: {len(agents)}/402')

from collections import Counter
for a, c in Counter(p['placing_agent'] for p in agents).most_common(25):
    print(f'  {c}x {a[:70]}')

with open('data/placements_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(placements, f, ensure_ascii=False, indent=2)
print('Saved.')
