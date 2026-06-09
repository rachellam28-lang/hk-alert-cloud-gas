import json

with open('data/confluence.json') as f:
    conf = json.load(f)
with open('data/announcements.json') as f:
    anns = json.load(f)

targets = ['00476', '08120', '01153', '00020', '00524', '01380']

print('=== Webb-site pnotes 24/4/2026 x HOLDINGS Confluence ===')
print()

for code in targets:
    ann_matches = [a for a in anns if str(a.get('code','')).zfill(5) == code]
    conf_matches = [c for c in conf if str(c.get('code','')).zfill(5) == code]
    
    parts = []
    if ann_matches:
        types = set()
        for a in ann_matches:
            types.add(a.get('typeLabel','?'))
        parts.append('Ann: YES (' + ', '.join(types) + ')')
    else:
        parts.append('Ann: NO')
    
    if conf_matches:
        for c in conf_matches:
            pat = c.get('pattern','')
            pre = c.get('pre_count',0)
            post = c.get('post_count',0)
            pat_label = {'frontrun':'DUCK','dual':'DUAL','catalyst':'CHASE'}.get(pat, pat)
            parts.append('Conf: ' + pat_label + ' pre=' + str(pre) + ' post=' + str(post))
    else:
        parts.append('Conf: NO')
    
    print(code + ' | ' + ' | '.join(parts))

print()
print('=== Detail ===')
for code in targets:
    conf_matches = [c for c in conf if str(c.get('code','')).zfill(5) == code]
    if conf_matches:
        for c in conf_matches:
            print(code + ' ' + str(c.get('name','?')) + ':')
            print('  Pre: ' + str(c.get('pre_types',[])))
            print('  Post: ' + str(c.get('post_types',[])))
            print('  Pattern: ' + str(c.get('pattern')) + ' | Date: ' + str(c.get('date')))
    else:
        ann_matches = [a for a in anns if str(a.get('code','')).zfill(5) == code]
        if ann_matches:
            print(code + ' ' + str(ann_matches[0].get('name','?')) + ': in announcements, no confluence')
        else:
            print(code + ': NOT in system')
