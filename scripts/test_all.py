"""
Monolithic: pull placement prices + run both tests sequentially.
No concurrent writes — single process only.
"""
import json, time, statistics, os
import yfinance as yf
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
PH_PATH = os.path.join(DATA, 'price_history.json')

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

def trading_dates_after(pxs, d0, n):
    ds = sorted(k for k in pxs if k > d0)
    return ds[:n]

# ===== STEP 1: Pull price history for placement stocks =====
print("=== STEP 1: Pull price history ===")
placements = load_json(os.path.join(DATA, 'placements_enriched.json'), [])
p_codes = set()
for p in placements:
    c = p.get('code')
    if c:
        p_codes.add(str(c).strip().lstrip('0').zfill(5))

hist = load_json(PH_PATH, {})
missing = sorted(p_codes - set(hist.keys()))
print(f"Need {len(missing)} placement stocks (of {len(p_codes)} total)")

pulled, failed = 0, 0
for i, code in enumerate(missing):
    try:
        t = yf.Ticker(f'{code}.HK')
        df = t.history(period='2y')
        if df is None or df.empty:
            try:
                clean = str(int(code))
                t2 = yf.Ticker(f'{clean}.HK')
                df = t2.history(period='2y')
            except:
                pass
        if df is None or df.empty:
            failed += 1
            continue
        records = []
        for idx, row in df.iterrows():
            records.append({
                'date': str(idx)[:10],
                'open': float(row['Open']), 'high': float(row['High']),
                'low': float(row['Low']), 'close': float(row['Close']),
                'volume': float(row['Volume']),
            })
        hist[code] = records
        pulled += 1
        if (i+1) % 50 == 0:
            save_json(PH_PATH, hist)
            print(f"  Pull: {i+1}/{len(missing)} ({pulled} ok, {failed} fail)")
        time.sleep(0.12)
    except Exception as e:
        failed += 1
        time.sleep(1)

save_json(PH_PATH, hist)
total_pulled = pulled
total_failed = failed
print(f"Pull done: +{pulled}, fail={failed}, total cached={len(hist)}")

# ===== STEP 2: 8120 Pattern Test =====
print("\n=== STEP 2: 8120 Pattern Test ===")

jump_thresholds = [0.05, 0.08, 0.15]
all_results = []

for p in placements:
    code = str(p.get('code', '')).strip().lstrip('0').zfill(5)
    pxs = hist.get(code)
    if not pxs:
        continue
    
    d0 = p.get('date', '') or p.get('announcement_date', '') or ''
    if len(d0) > 10:
        d0 = d0[:10]
    
    try:
        base_date = d0[:4] + '-' + d0[4:6] + '-' + d0[6:8] if '-' not in d0 and len(d0) == 8 else d0
    except:
        continue
    
    # Find the announcement date: match exactly, or find next trading day
    px_by_date = {}
    for r in pxs:
        px_by_date[r['date']] = r['close']
    
    if base_date in px_by_date:
        entry_idx_date = base_date
    else:
        # Find next trading day after announcement
        dates = sorted(px_by_date.keys())
        entry_idx_date = None
        for d in dates:
            if d >= base_date:
                entry_idx_date = d
                break
        if entry_idx_date is None:
            continue
    
    base_close = px_by_date[entry_idx_date]
    if base_close <= 0.001:
        continue
    
    next5 = trading_dates_after(px_by_date, entry_idx_date, 5)
    if not next5:
        continue
    
    discount = p.get('discount_pct') or p.get('discount')
    
    rec = {
        'code': code,
        'name': p.get('name', ''),
        'date': base_date,
        'entry_date': entry_idx_date,
        'discount': discount,
    }
    
    # Check jumps at each threshold
    for thresh in jump_thresholds:
        jump_day = None
        for d in next5:
            if d in px_by_date and px_by_date[d] / base_close - 1 > thresh:
                jump_day = d
                break
        jumped = bool(jump_day)
        
        entry_day = jump_day if jumped else next5[0]
        entry_price = px_by_date[entry_day]
        
        after = trading_dates_after(px_by_date, entry_day, 60)
        
        if len(after) >= 20:
            fwd20 = px_by_date[after[19]] / entry_price - 1
            fwd5 = px_by_date[after[4]] / entry_price - 1 if len(after) >= 5 else None
            if len(after) >= 2:
                gains = [px_by_date[d] / entry_price - 1 for d in after]
                max_gain_60d = max(gains)
                dd_20d = min(px_by_date[d] / entry_price - 1 for d in after[:20])
            else:
                max_gain_60d = None
                dd_20d = None
            
            rec[f'jump_{int(thresh*100)}'] = jumped
            rec[f'fwd20_{int(thresh*100)}'] = round(fwd20, 4)
            rec[f'fwd5_{int(thresh*100)}'] = round(fwd5, 4) if fwd5 else None
            rec[f'maxgain_{int(thresh*100)}'] = round(max_gain_60d, 4) if max_gain_60d else None
            rec[f'dd20_{int(thresh*100)}'] = round(dd_20d, 4) if dd_20d else None
    
    if rec.get('jump_8') is not None:
        all_results.append(rec)

# Print results
for thresh in jump_thresholds:
    th = int(thresh * 100)
    print(f"\n--- Threshold: +{th}% ---")
    
    jumped = [r for r in all_results if r.get(f'jump_{th}')]
    nojump = [r for r in all_results if not r.get(f'jump_{th}')]
    
    for label, grp in [(f'配股後T+1~5有≥{th}%跳升', jumped),
                       (f'配股後冇跳升', nojump)]:
        if not grp:
            continue
        
        n = len(grp)
        f20 = [r[f'fwd20_{th}'] for r in grp if r.get(f'fwd20_{th}') is not None]
        g60 = [r[f'maxgain_{th}'] for r in grp if r.get(f'maxgain_{th}') is not None]
        dd20 = [r[f'dd20_{th}'] for r in grp if r.get(f'dd20_{th}') is not None]
        
        if not f20:
            print(f"  {label}: n={n} (no fwd20 data)")
            continue
        
        f20.sort()
        g60.sort()
        dd20.sort()
        
        q25, q50, q75 = f20[len(f20)//4], f20[len(f20)//2], f20[3*len(f20)//4]
        g25, g50, g75 = g60[len(g60)//4], g60[len(g60)//2], g60[3*len(g60)//4] if len(g60) >= 3 else (0,0,0)
        wins = sum(1 for x in f20 if x > 0) / len(f20) * 100
        over100 = sum(1 for x in g60 if x > 1.0) / len(g60) * 100 if g60 else 0
        
        print(f"  {label}: n={n}")
        print(f"    fwd20 quartiles: Q1={q25*100:+.1f}%  Q2={q50*100:+.1f}%  Q3={q75*100:+.1f}%")
        print(f"    win_rate: {wins:.0f}%")
        print(f"    max_gain_60d quartiles: Q1={g25*100:+.1f}%  Q2={g50*100:+.1f}%  Q3={g75*100:+.1f}%")
        print(f"    >100% in 60d: {sum(1 for x in g60 if x > 1.0)}/{len(g60)} ({over100:.0f}%)")
        if dd20:
            ddmed = dd20[len(dd20)//2]
            print(f"    maxDD_20d median: {ddmed*100:+.1f}%")
        
        # Discount split
        if th == 8:
            narrow = [r for r in grp if r.get('discount') is not None and r['discount'] < 10]
            wide = [r for r in grp if r.get('discount') is not None and r['discount'] >= 10]
            nodisc = [r for r in grp if r.get('discount') is None]
            
            for sub_label, sub_grp in [('  折讓<10%', narrow), ('  折讓>=10%', wide), ('  折讓=None', nodisc)]:
                if not sub_grp:
                    continue
                sn = len(sub_grp)
                sf = [r[f'fwd20_{th}'] for r in sub_grp if r.get(f'fwd20_{th}') is not None]
                sg = [r[f'maxgain_{th}'] for r in sub_grp if r.get(f'maxgain_{th}') is not None]
                if sf:
                    sf.sort()
                    smed = sf[len(sf)//2]
                    sover100 = sum(1 for x in sg if x > 1.0) / len(sg) * 100 if sg else 0
                    print(f"    {sub_label}: n={sn}, med_fwd20={smed*100:+.1f}%, >100%={sum(1 for x in sg if x > 1.0)}/{len(sg)} ({sover100:.0f}%)")

print(f"\nTotal placements: {len(placements)}, tested: {len(all_results)}")
print(f"Failed yfinance: {total_failed} (delisted/delisted)")

# ===== Survivorship sensitivity =====
no_data = len(placements) - len(all_results)
print(f"Survivorship gap: {no_data}/{len(placements)} ({no_data/len(placements)*100:.0f}%) placements no price data")
print("Worst-case: if all failed = -100%, jump group >100% rate drops proportionally")
