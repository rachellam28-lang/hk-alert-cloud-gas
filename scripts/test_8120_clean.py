"""
8120 pattern test using GIT-DERIVED price data (raw/prices_*.json).
Zero yfinance. Zero external API. Format B: {date: {code: close}}.
"""
import json, os, statistics
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, 'raw')

def load_price_history():
    """raw/prices_YYYYMMDD.json → {date: {code: close}}"""
    hist_dates = {}
    for fname in sorted(os.listdir(RAW_DIR)):
        if not fname.startswith('prices_') or not fname.endswith('.json'):
            continue
        date = fname[7:11] + '-' + fname[11:13] + '-' + fname[13:15]
        with open(os.path.join(RAW_DIR, fname)) as f:
            hist_dates[date] = json.load(f)
    
    # Invert: {code: {date: close}}
    hist = defaultdict(dict)
    for date, codes in hist_dates.items():
        for code, close in codes.items():
            hist[str(code).zfill(5)][date] = close
    
    return hist, sorted(hist_dates.keys())

def load_placements():
    with open(os.path.join(BASE, 'data', 'placements_enriched.json'), encoding='utf-8') as f:
        return json.load(f)

def load_holdings():
    with open(os.path.join(BASE, 'holdings.json'), encoding='utf-8') as f:
        return json.load(f)

def trading_dates_after(dates, d0, n):
    """Find n trading dates after d0."""
    return [d for d in dates if d > d0][:n]

print("Loading data...")
hist, all_dates = load_price_history()
placements = load_placements()
holdings = load_holdings()

live_codes = set(str(s['c']).zfill(5) for s in holdings.get('stocks', []))

# Dead/zombie check
p_codes = set()
for p in placements:
    c = str(p.get('code', '')).strip().lstrip('0').zfill(5)
    if c and c != '00000':
        p_codes.add(c)

delisted = [c for c in p_codes if c not in live_codes]
zombies = []
for c in p_codes & live_codes:
    px_dates = hist.get(c, {})
    if px_dates:
        last_date = max(px_dates.keys())
        last_close = px_dates[last_date]
        # zombie: price < 0.01 OR price unchanged for all available dates
        prices = list(px_dates.values())
        if last_close < 0.01 or (len(set(prices)) == 1 and len(prices) > 1):
            zombies.append(c)

dead_zombie = set(delisted + zombies)
print(f"Placements: {len(placements)} total")
print(f"  Delisted: {len(delisted)}")
print(f"  Zombies: {len(zombies)}")
print(f"  Dead+zombie: {len(dead_zombie)} ({len(dead_zombie)/len(placements)*100:.1f}%)")
print(f"  Has price data: {sum(1 for c in p_codes if c in hist and hist[c])}")

# ===== 8120 Pattern Test =====
print("\n=== 8120 PATTERN TEST (8% close-to-close, git data) ===")

jumped = []
nojump = []
no_data = []

for p in placements:
    code = str(p.get('code', '')).strip().lstrip('0').zfill(5)
    pxs = hist.get(code, {})
    if not pxs:
        no_data.append(code)
        continue
    
    d0 = p.get('date', '') or ''
    # Handle DD/MM/YYYY format
    if '/' in d0:
        try:
            from datetime import datetime
            dt = datetime.strptime(d0[:10], '%d/%m/%Y')
            d0 = dt.strftime('%Y-%m-%d')
        except:
            pass
    elif len(d0) == 8 and d0.isdigit():
        d0 = f"{d0[:4]}-{d0[4:6]}-{d0[6:8]}"
    elif len(d0) > 10:
        d0 = d0[:10]
    
    # Find entry date (announcement date or next trading day)
    base_close = pxs.get(d0)
    entry_date = d0
    if base_close is None:
        # Find next trading day
        for d in sorted(pxs.keys()):
            if d >= d0:
                entry_date = d
                base_close = pxs[d]
                break
    
    if base_close is None or base_close <= 0.001:
        no_data.append(code)
        continue
    
    next5 = trading_dates_after(all_dates, entry_date, 5)
    if not next5:
        no_data.append(code)
        continue
    
    # Check for 8% jump (close-to-close)
    jump_day = None
    jump_pct = 0
    for d in next5:
        if d in pxs:
            chg = pxs[d] / base_close - 1
            if chg > 0.08:
                jump_day = d
                jump_pct = chg
                break
    
    # Entry price: jump day if jumped, else first available close
    if jump_day:
        entry_price = pxs[jump_day]
    else:
        entry_price = base_close
    
    # Forward returns
    after_all = trading_dates_after(all_dates, jump_day or entry_date, 60)
    
    rec = {
        'code': code,
        'name': p.get('name', ''),
        'date': d0,
        'jumped': bool(jump_day),
        'jump_pct': round(jump_pct * 100, 1) if jump_day else 0,
        'discount': p.get('discount_pct') or p.get('discount'),
        'entry_price': entry_price,
    }
    
    if len(after_all) >= 20:
        # 20d forward
        d20 = after_all[19]
        if d20 in pxs:
            rec['fwd20'] = round(pxs[d20] / entry_price - 1, 4)
        
        # Max gain in 60d
        gains_60 = []
        for d in after_all:
            if d in pxs:
                gains_60.append(pxs[d] / entry_price - 1)
        if gains_60:
            rec['max_gain60'] = round(max(gains_60), 4)
            rec['max_dd20'] = round(min(gains_60[:20]), 4) if len(gains_60) >= 20 else None
    
    if rec.get('fwd20') is not None:
        if rec['jumped']:
            jumped.append(rec)
        else:
            nojump.append(rec)

def stats(grp, label):
    if not grp:
        print(f"{label}: n=0")
        return 0, 0, len(grp)
    
    f20 = [r['fwd20'] for r in grp if r.get('fwd20') is not None]
    g60 = [r['max_gain60'] for r in grp if r.get('max_gain60') is not None]
    dd20 = [r['max_dd20'] for r in grp if r.get('max_dd20') is not None]
    
    f20.sort()
    g60.sort()
    dd20.sort()
    
    print(f"\n{label}: n={len(grp)}")
    if f20:
        print(f"  fwd20 Q1/Q2/Q3: {f20[len(f20)//4]*100:+.1f}% / {f20[len(f20)//2]*100:+.1f}% / {f20[3*len(f20)//4]*100:+.1f}%")
    if g60:
        print(f"  maxGain60 Q1/Q2/Q3: {g60[len(g60)//4]*100:+.1f}% / {g60[len(g60)//2]*100:+.1f}% / {g60[3*len(g60)//4]*100:+.1f}%")
    
    wins = sum(1 for x in f20 if x > 0)
    print(f"  win_rate(>0): {wins}/{len(f20)} ({wins/len(f20)*100:.0f}%)" if f20 else "  no fwd20")
    
    over100 = sum(1 for x in g60 if x > 1.0)
    print(f"  >100% in 60d: {over100}/{len(g60)} ({over100/len(g60)*100:.0f}%)" if g60 else "")
    
    if dd20:
        print(f"  maxDD median: {dd20[len(dd20)//2]*100:+.1f}%")
    
    # Discount split
    narrow = [r for r in grp if r.get('discount') is not None and r['discount'] < 10]
    wide = [r for r in grp if r.get('discount') is not None and r['discount'] >= 10]
    if narrow:
        ng = [r['max_gain60'] for r in narrow if r.get('max_gain60') is not None]
        nf = [r['fwd20'] for r in narrow if r.get('fwd20') is not None]
        if nf:
            over100n = sum(1 for x in ng if x > 1.0)
            print(f"  [折讓<10%] n={len(narrow)}, med_fwd20={sorted(nf)[len(nf)//2]*100:+.1f}%, >100%={over100n}/{len(ng)} ({over100n/len(ng)*100:.0f}%)" if ng else "")
    if wide:
        wf = [r['fwd20'] for r in wide if r.get('fwd20') is not None]
        wg = [r['max_gain60'] for r in wide if r.get('max_gain60') is not None]
        if wg:
            over100w = sum(1 for x in wg if x > 1.0)
            print(f"  [折讓>=10%] n={len(wide)}, med_fwd20={sorted(wf)[len(wf)//2]*100:+.1f}%, >100%={over100w}/{len(wg)} ({over100w/len(wg)*100:.0f}%)" if wf else "")
    
    return sum(1 for x in g60 if x > 1.0) if g60 else 0, len(g60), len(grp)

over100_j, winners_j, nj = stats(jumped, "JUMPED (>=8%)")
over100_nj, winners_nj, nn = stats(nojump, "NO JUMP")

if nj > 0 and nn > 0:
    ratio = (over100_j/nj) / (over100_nj/nn)
    print(f"\nRatio >100%: {over100_j}/{nj} ({over100_j/nj*100:.0f}%) vs {over100_nj}/{nn} ({over100_nj/nn*100:.0f}%) = {ratio:.1f}x")

# Worst-case: add dead+zombie as non-winners
dead_in_jump = sum(1 for c in dead_zombie if any(r['code'] == c for r in jumped))
dead_in_nojump = sum(1 for c in dead_zombie if any(r['code'] == c for r in nojump))
untested_dead = len(dead_zombie) - dead_in_jump - dead_in_nojump

print(f"\n=== WORST-CASE SENSITIVITY ===")
print(f"Dead+zombie total: {len(dead_zombie)}")
print(f"  In jump group: {dead_in_jump}")
print(f"  In no-jump group: {dead_in_nojump}")  
print(f"  Untested: {untested_dead}")
print(f"  Stress: Jump >100% = {over100_j}/({nj}+{untested_dead}) = {over100_j/(nj+untested_dead)*100:.0f}%")
print(f"  Stress: No-jump >100% = {over100_nj}/({nn}+{untested_dead}) = {over100_nj/(nn+untested_dead)*100:.0f}%")
