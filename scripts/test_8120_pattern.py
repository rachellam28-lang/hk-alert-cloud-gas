"""
test_8120_pattern.py
Placement jump pattern: 配股後T+1~T+5跳升 → 60日 max gain.
Tests 5%/8%/15% thresholds + discount split.
"""
import json, statistics, sys, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE, 'data', 'placements_enriched.json'), encoding='utf-8') as f:
    placements = json.load(f)
with open(os.path.join(BASE, 'data', 'price_history.json')) as f:
    hist = json.load(f)

def trading_dates_after(pxs, d0, n):
    ds = sorted(k for k in pxs if k > d0)
    return ds[:n]

def parse_date(raw):
    """Parse various date formats to YYYY-MM-DD."""
    import re
    s = str(raw).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except: pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

def parse_discount(p):
    disc = p.get('discount') or p.get('discount_pct') or p.get('折讓')
    if disc is None or disc == 'N/A' or disc == '':
        return None
    try:
        return float(str(disc).replace('%','').strip())
    except:
        return None

# Run for each threshold
for threshold_pct in [5.0, 8.0, 15.0]:
    print(f"\n{'='*60}")
    print(f"Threshold: +{threshold_pct:.0f}% jump")
    print(f"{'='*60}")
    
    results = []
    no_price = 0
    skipped_date = 0
    
    for p in placements:
        code = str(p.get('code','')).strip().lstrip('0').zfill(5)
        pxs = hist.get(code)
        d0_str = parse_date(p.get('date') or p.get('announcement_date') or '')
        
        if not d0_str:
            skipped_date += 1
            continue
        if not pxs:
            no_price += 1
            continue
        
        # Find closest trading date >= d0
        dates_sorted = sorted(pxs.keys())
        d0 = None
        for d in dates_sorted:
            if d >= d0_str:
                d0 = d
                break
        if not d0:
            no_price += 1
            continue
        
        base = pxs.get(d0)
        if not base or base <= 0.001:
            continue
        
        next5 = trading_dates_after(pxs, d0, 5)
        if not next5:
            no_price += 1
            continue
        
        # Detect jump
        jumped = False
        jump_day = None
        for d in next5:
            px = pxs.get(d)
            if px and px / base - 1 > threshold_pct / 100:
                jumped = True
                jump_day = d
                break
        
        entry_day = jump_day or next5[0]
        entry = pxs.get(entry_day)
        if not entry or entry <= 0.001:
            continue
        
        after = trading_dates_after(pxs, entry_day, 60)
        if len(after) < 20:
            continue
        
        discount = parse_discount(p)
        rec = {
            'code': code,
            'jumped': jumped,
            'discount': discount,
            'entry_price': entry,
            'fwd_20d': pxs[after[19]] / entry - 1 if len(after) >= 20 else None,
            'max_gain_60d': max(pxs[d] for d in after) / entry - 1 if after else None,
            'max_dd_20d': min(pxs[d] for d in after[:20]) / entry - 1 if len(after) >= 20 else None,
        }
        results.append(rec)
    
    jumped = [r for r in results if r['jumped']]
    no_jump = [r for r in results if not r['jumped']]
    
    print(f"Placements: {len(placements)} total")
    print(f"  skipped date: {skipped_date}, no price: {no_price}")
    print(f"  tested: {len(results)}")
    
    for label, grp in [('配股後有跳升', jumped), ('配股後冇跳升', no_jump)]:
        if not grp:
            continue
        n = len(grp)
        f20 = [r['fwd_20d'] for r in grp if r['fwd_20d'] is not None]
        mg60 = [r['max_gain_60d'] for r in grp if r['max_gain_60d'] is not None]
        dd20 = [r['max_dd_20d'] for r in grp if r['max_dd_20d'] is not None]
        
        # Quartiles
        mg60.sort()
        q1, q2, q3 = mg60[len(mg60)//4], mg60[len(mg60)//2], mg60[3*len(mg60)//4]
        
        print(f"\n{label}: n={n}")
        print(f"  med_fwd20d: {statistics.median(f20)*100:+.1f}%")
        print(f"  win_rate(>0): {sum(1 for x in f20 if x>0)/len(f20)*100:.0f}%")
        print(f"  med_maxgain_60d: {q2*100:+.1f}%")
        print(f"  maxgain quartiles: Q1={q1*100:+.1f}%, Q3={q3*100:+.1f}%, max={max(mg60)*100:+.0f}%")
        print(f"  >100%_in_60d: {sum(1 for x in mg60 if x>1)}/{n} ({sum(1 for x in mg60 if x>1)/n*100:.0f}%)")
        print(f"  med_maxdd_20d: {statistics.median(dd20)*100:+.1f}%")
        
        # Split by discount
        if label == '配股後有跳升':
            narrow = [r for r in grp if r['discount'] is not None and r['discount'] < 10]
            wide = [r for r in grp if r['discount'] is not None and r['discount'] >= 10]
            unknown = [r for r in grp if r['discount'] is None]
            
            for dlabel, dgrp in [('折讓<10%', narrow), ('折讓>=10%', wide), ('折讓=None', unknown)]:
                if not dgrp:
                    continue
                dn = len(dgrp)
                df20 = [r['fwd_20d'] for r in dgrp if r['fwd_20d'] is not None]
                dmg = [r['max_gain_60d'] for r in dgrp if r['max_gain_60d'] is not None]
                if dmg:
                    dmg.sort()
                    dq2 = dmg[len(dmg)//2]
                    print(f"  [{dlabel}] n={dn}, med_fwd20={statistics.median(df20)*100:+.1f}%, med_maxgain60={dq2*100:+.1f}%, >100%={sum(1 for x in dmg if x>1)}/{dn} ({sum(1 for x in dmg if x>1)/dn*100:.0f}%)")
                else:
                    print(f"  [{dlabel}] n={dn}, no data")
