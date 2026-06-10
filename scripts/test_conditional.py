"""
Conditional test: corp背景 × POC/FVG vs 淨技術
Does a corporate action background revive technical signals?

Reads: 
  - events.json (replay signals with alert_date, signal_type, category)
  - price_history.json (daily close per stock)
  - announcements.json (corp actions with date)
"""
import json, os, statistics
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return default

def trading_dates_after(pxs, d0, n):
    ds = sorted(k for k in pxs if k > d0)
    return ds[:n]

print("=== Conditional Test: Corp Background × Technical Signals ===\n")

# Load data
events = load_json(os.path.join(BASE, 'events.json'), [])
if isinstance(events, dict):
    events = events.get('events', [])
hist = load_json(os.path.join(DATA, 'price_history.json'), {})
anns = load_json(os.path.join(DATA, 'announcements.json'), [])

# Build corp date map: {code: set of dates within 30d window}
from datetime import datetime as dt
corp_dates = defaultdict(set)
for a in (anns or []):
    code = str(a.get('code', '')).strip().lstrip('0').zfill(5)
    adate = a.get('date', '')[:10]
    if code and adate:
        corp_dates[code].add(adate)

# For each event, check if there's a corp announcement within ±30 days
print(f"Events: {len(events)}")
print(f"Hist stocks: {len(hist)}")
print(f"Announcement codes: {len(corp_dates)}")

# Test groups
groups = defaultdict(list)  # (signal_group, has_corp) -> [fwd20 returns]

for e in events:
    code = e.get('code', '')
    stype = e.get('signal_type', '')
    cat = e.get('category', '')
    alert_date = e.get('alert_date', '')[:10]
    
    pxs = hist.get(code)
    if not pxs:
        continue
    
    px_by_date = {}
    for r in pxs:
        px_by_date[r['date']] = r['close']
    
    if alert_date not in px_by_date:
        # Find next trading day
        dates = sorted(px_by_date.keys())
        found = False
        for d in dates:
            if d >= alert_date:
                alert_date, found = d, True
                break
        if not found:
            continue
    
    entry = px_by_date[alert_date]
    if entry <= 0.001:
        continue
    
    # Forward 20d
    after = trading_dates_after(px_by_date, alert_date, 20)
    if len(after) < 15:
        continue
    
    fwd20 = px_by_date[after[min(19, len(after)-1)]] / entry - 1
    
    # Check corp proximity: any announcement for this code within ±30d of alert_date?
    cd = corp_dates.get(code, set())
    has_corp_nearby = False
    for d in cd:
        try:
            delta = abs((dt.strptime(alert_date, '%Y-%m-%d') - dt.strptime(d, '%Y-%m-%d')).days)
            if delta <= 30:
                has_corp_nearby = True
                break
        except:
            pass
    
    # Classify signal group
    if cat in ('poc',):
        sg = 'POC'
    elif cat in ('fvg', 'fvg_gap'):
        sg = 'FVG'
    elif cat in ('year_open',):
        sg = '年開'
    else:
        sg = 'other'
    
    if sg == 'other':
        continue
    
    key = (sg, 'corp背景' if has_corp_nearby else '淨技術')
    # Also track 20d max gain/drawdown
    window = [px_by_date[d] / entry - 1 for d in after[:20]]
    max_gain = max(window) if window else 0
    max_dd = min(window) if window else 0
    
    groups[key].append({
        'fwd20': fwd20,
        'max_gain': max_gain,
        'max_dd': max_dd,
    })

# Print results
print(f"\n{'Group':<30} {'n':>5} {'med_fwd20':>10} {'win%':>7} {'med_gain':>10} {'med_dd':>9}")
print("-" * 75)

for key in sorted(groups.keys()):
    vals = groups[key]
    n = len(vals)
    if n < 5:
        continue
    
    fwds = sorted([v['fwd20'] for v in vals])
    gains = sorted([v['max_gain'] for v in vals])
    dds = sorted([v['max_dd'] for v in vals])
    
    med_fwd = fwds[len(fwds)//2]
    win = sum(1 for x in fwds if x > 0) / n * 100
    med_gain = gains[len(gains)//2]
    med_dd = dds[len(dds)//2]
    
    print(f"{key[0]:<12} {key[1]:<17} {n:>5} {med_fwd*100:>+9.1f}% {win:>6.0f}% {med_gain*100:>+9.1f}% {med_dd*100:>+8.1f}%")

# Cross comparison
print("\n--- Cross Comparison ---")
for sg in ['POC', 'FVG', '年開']:
    corp_k = (sg, 'corp背景')
    tech_k = (sg, '淨技術')
    if corp_k in groups and tech_k in groups:
        corp = groups[corp_k]
        tech = groups[tech_k]
        corp_fwd = sorted([v['fwd20'] for v in corp])
        tech_fwd = sorted([v['fwd20'] for v in tech])
        corp_med = corp_fwd[len(corp_fwd)//2]
        tech_med = tech_fwd[len(tech_fwd)//2]
        corp_win = sum(1 for x in corp_fwd if x > 0) / len(corp_fwd) * 100
        tech_win = sum(1 for x in tech_fwd if x > 0) / len(tech_fwd) * 100
        
        corp_gain = sorted([v['max_gain'] for v in corp])
        tech_gain = sorted([v['max_gain'] for v in tech])
        corp_gain_med = corp_gain[len(corp_gain)//2] if corp_gain else 0
        tech_gain_med = tech_gain[len(tech_gain)//2] if tech_gain else 0
        
        print(f"\n{sg}:")
        print(f"  corp背景: n={len(corp)}, fwd20_med={corp_med*100:+.1f}%, win={corp_win:.0f}%, maxgain_med={corp_gain_med*100:+.1f}%")
        print(f"  淨技術:   n={len(tech)}, fwd20_med={tech_med*100:+.1f}%, win={tech_win:.0f}%, maxgain_med={tech_gain_med*100:+.1f}%")
        diff = corp_med - tech_med
        win_diff = corp_win - tech_win
        gain_diff = corp_gain_med - tech_gain_med
        print(f"  Δ:        fwd20={diff*100:+.1f}%, win={win_diff:+.0f}%, maxgain={gain_diff*100:+.1f}%")
