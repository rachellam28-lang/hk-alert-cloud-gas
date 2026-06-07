import json, os
from collections import defaultdict

backup_dir = r'C:\Users\Administrator\ccass-backups'

# Step 1: Load existing history (keep as-is for rich data)
existing_path = r'C:\Users\Administrator\Desktop\automatic\ccass-debug\data\history.json'
existing = json.load(open(existing_path, encoding='utf-8'))
existing_dates = set(d['date'] for d in existing.get('days', []))

seen = set()
all_alerts = defaultdict(list)

# Load existing entries first (preferred - they have message/created_at)
for day_data in existing.get('days', []):
    d = day_data['date']
    for a in day_data.get('alerts', []):
        code = str(a.get('code', '')).strip()
        sig = a.get('signal', '')
        if isinstance(sig, dict):
            sig = sig.get('label', '') or sig.get('type', '') or ''
        key = code + '|' + str(sig) + '|' + d
        seen.add(key)
        all_alerts[d].append(a)

print('Existing:', len(all_alerts), 'days,', sum(len(v) for v in all_alerts.values()), 'alerts')

# Step 2: Add GAS backup data for dates NOT already covered
files = [f for f in os.listdir(backup_dir) if f.startswith('gas_data_2026') and f.endswith('.json')]

for fname in sorted(files):
    fpath = os.path.join(backup_dir, fname)
    d = json.load(open(fpath, encoding='utf-8'))
    
    for g in d.get('groups', []):
        code = str(g.get('code', '')).strip()
        name = g.get('name', '')
        for s in g.get('signals', []):
            if not s.get('date'):
                continue
            day = s['date'][:10]
            if day in existing_dates:
                continue  # Skip dates already covered by local scanner
            label = s.get('label', '')
            key = code + '|' + label + '|' + day
            if key in seen:
                continue
            seen.add(key)
            all_alerts[day].append({
                'code': code,
                'name': name,
                'signal': label,
                'category': 'tech',
                'created_at': s.get('date', ''),
                'chart_url': s.get('link', '') or '',
                'message': ''
            })
    
    for c in d.get('recentCorps', []):
        if not c.get('date'):
            continue
        day = c['date']
        if day in existing_dates:
            continue
        code = str(c.get('code', '')).strip()
        ctype = c.get('type', '')
        key = code + '|' + ctype + '|corp|' + day
        if key in seen:
            continue
        seen.add(key)
        all_alerts[day].append({
            'code': code,
            'name': c.get('name', ''),
            'signal': ctype,
            'category': 'corp_action',
            'created_at': c.get('date', ''),
            'chart_url': c.get('url', '') or '',
            'message': c.get('title', '') or ''
        })

# Build output
days = []
for date_str in sorted(all_alerts.keys(), reverse=True):
    days.append({'date': date_str, 'alerts': all_alerts[date_str]})

total = sum(len(d['alerts']) for d in days)
output = {'ok': True, 'total': total, 'days': days}

out_path = r'C:\Users\Administrator\Desktop\automatic\ccass-debug\data\history.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, default=str)

print('\nFinal:', len(days), 'days,', total, 'alerts')
for d in days:
    print(' ', d['date'], ':', len(d['alerts']))
