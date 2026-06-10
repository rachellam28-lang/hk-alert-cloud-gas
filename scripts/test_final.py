"""Final: 8120 + zombie + conditional — 246 cached stocks, no re-pull."""
import json, statistics, os, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')

def load_j(p, d=None):
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    return d

def td_after(pxs, d0, n):
    return sorted([d for d in pxs if d > d0])[:n]

hist = load_j(os.path.join(DATA, 'price_history.json'), {})
holdings = load_j(os.path.join(BASE, 'holdings.json'), {})
placements = load_j(os.path.join(DATA, 'placements_enriched.json'), [])
announcements = load_j(os.path.join(DATA, 'announcements.json'), [])

stocks = holdings.get('stocks', [])
live_set = {str(s['c']).strip().lstrip('0').zfill(5) for s in stocks}

print("=== ZOMBIE + DELIST CHECK ===")
# Zombie: vol=0 with no price movement
zombies_holdings = 0
for s in stocks:
    vol = s.get('vol', 0) or 0
    lp = s.get('lp', 0) or 0
    if vol == 0 and lp < 0.001:
        zombies_holdings += 1
# Also check: price unchanged for 60+ days = flatline
# We'll check from price_history
stock_vol = {str(s['c']).strip().lstrip('0').zfill(5): s for s in stocks}

p_in_holdings = 0
p_not_in_holdings = 0
p_zombies = 0
p_has_yf = 0
p_missing_yf = 0
p_total = len(placements)

for p in placements:
    code = str(p.get('code', '')).strip().lstrip('0').zfill(5)
    if code in live_set:
        p_in_holdings += 1
        sv = stock_vol.get(code, {})
        vol = sv.get('vol', 0) or 0
        lp = sv.get('lp', 0) or 0
        # Check if flatlined in price_history
        pxs = hist.get(code)
        if pxs:
            p_has_yf += 1
            # Check last 60 trading days for flat price
            dates = sorted(r['date'] for r in pxs if r['close'] > 0.001)[-60:]
            if len(dates) >= 30:
                closes = [next(r['close'] for r in pxs if r['date']==d) for d in dates]
                if max(closes) - min(closes) < 0.0001 and vol == 0:
                    p_zombies += 1
            if vol == 0 and lp < 0.001:
                p_zombies += 1
        else:
            p_missing_yf += 1
            if vol == 0 and lp < 0.001:
                p_zombies += 1
    else:
        p_not_in_holdings += 1

print(f"Placements: {p_total} total")
print(f"  In holdings (live): {p_in_holdings}")
print(f"  NOT in holdings (delisted): {p_not_in_holdings}")
print(f"  Zombies (dead money): {p_zombies}")
print(f"  Has yfinance data: {p_has_yf}")
print(f"  Missing yf (live): {p_missing_yf}")
print(f"  Real dead+zombie rate: {p_not_in_holdings + p_zombies}/{p_total} ({round((p_not_in_holdings+p_zombies)/p_total*100,1)}%)")

# ===== 8120 PATTERN TEST =====
print("\n=== 8120 PATTERN TEST (8% threshold) ===")
th = 8

results_8120 = []
for p in placements:
    code = str(p.get('code', '')).strip().lstrip('0').zfill(5)
    pxs = hist.get(code)
    if not pxs:
        continue
    
    d0 = str(p.get('date', '') or p.get('announcement_date', ''))[:10]
    if not d0 or len(d0) < 8:
        continue
    
    px_by_date = {r['date']: r['close'] for r in pxs}
    dates = sorted(px_by_date.keys())
    
    # Find first trading day >= announcement date
    t0 = None
    for d in dates:
        if d >= d0:
            t0 = d
            break
    if not t0:
        continue
    
    base = px_by_date[t0]
    if base <= 0.001:
        continue
    
    n5 = td_after(px_by_date, t0, 5)
    if not n5:
        continue
    
    jumped = any(px_by_date[d] / base - 1 > th/100 for d in n5)
    entry_day = next((d for d in n5 if px_by_date[d] / base - 1 > th/100), n5[0])
    entry = px_by_date[entry_day]
    
    after = td_after(px_by_date, entry_day, 60)
    if len(after) < 20:
        continue
    
    fwd20 = px_by_date[after[19]] / entry - 1
    after_gains = [px_by_date[d] / entry - 1 for d in after]
    max_gain = max(after_gains)
    max_dd = min(after_gains[:20])
    over100 = 1 if max_gain > 1.0 else 0
    
    discount = p.get('discount_pct') or p.get('discount')
    is_zombie = code not in live_set or (stock_vol.get(code, {}).get('vol', 0) == 0 and stock_vol.get(code, {}).get('lp', 0) < 0.001)
    
    results_8120.append({
        'code': code, 'jumped': jumped, 'fwd20': round(fwd20, 4),
        'max_gain': round(max_gain, 4), 'max_dd': round(max_dd, 4),
        'over100': over100, 'discount': discount, 'zombie': is_zombie,
    })

def print_stats(grp, label):
    if not grp:
        print(f"  {label}: n=0")
        return 0, 0, []
    n = len(grp)
    f20 = [r['fwd20'] for r in grp]
    g60 = [r['max_gain'] for r in grp]
    dd = [r['max_dd'] for r in grp]
    over100 = sum(r['over100'] for r in grp)
    
    f20.sort(); g60.sort(); dd.sort()
    q1f, q2f, q3f = f20[n//4], f20[n//2], f20[3*n//4]
    q1g, q2g, q3g = g60[n//4], g60[n//2], g60[3*n//4]
    wins = sum(1 for x in f20 if x > 0) / n * 100
    ddmed = dd[n//2]
    
    print(f"  {label}: n={n}")
    print(f"    fwd20 Q1/Q2/Q3: {q1f*100:+.1f}% / {q2f*100:+.1f}% / {q3f*100:+.1f}%")
    print(f"    win_rate: {wins:.0f}%")
    print(f"    max_gain Q1/Q2/Q3: {q1g*100:+.1f}% / {q2g*100:+.1f}% / {q3g*100:+.1f}%")
    print(f"    >100%: {over100}/{n} ({over100/n*100:.0f}%)")
    print(f"    maxDD median: {ddmed*100:+.1f}%")
    return over100, n, f20

jumped_grp = [r for r in results_8120 if r['jumped']]
nojump_grp = [r for r in results_8120 if not r['jumped']]

print(f"\nTotal tested: {len(results_8120)}/{p_total}")
w_j, n_j, _ = print_stats(jumped_grp, f"JUMPED (>={th}% in T+1~5)")
w_nj, n_nj, _ = print_stats(nojump_grp, "NO JUMP")

if n_nj > 0:
    print(f"\n  Ratio >100%: {w_j}/{n_j} ({w_j/n_j*100:.0f}%) vs {w_nj}/{n_nj} ({w_nj/n_nj*100:.0f}%) = {round((w_j/n_j)/(w_nj/n_nj+0.001),1)}x")

# Discount split on jumped
print("\n  [Discount split — JUMPED group]:")
narrow = [r for r in jumped_grp if r['discount'] is not None and r['discount'] < 10]
wide = [r for r in jumped_grp if r['discount'] is not None and r['discount'] >= 10]
nodisc = [r for r in jumped_grp if r['discount'] is None]
for lbl, grp in [('折讓<10%', narrow), ('折讓>=10%', wide), ('折讓=None', nodisc)]:
    if grp:
        f = sorted([r['fwd20'] for r in grp])
        o100 = sum(r['over100'] for r in grp)
        print(f"    {lbl}: n={len(grp)}, med_fwd20={f[len(f)//2]*100:+.1f}%, >100%={o100}/{len(grp)} ({o100/len(grp)*100:.0f}%)")

# ===== WORST-CASE SENSITIVITY =====
print("\n=== WORST-CASE SENSITIVITY ===")
total_dead_zombie = p_not_in_holdings + p_zombies
dead_set_by_code = set()
for p in placements:
    code = str(p.get('code', '')).strip().lstrip('0').zfill(5)
    if code not in live_set:
        dead_set_by_code.add(code)
    elif code in stock_vol:
        sv = stock_vol.get(code, {})
        if sv.get('vol', 0) == 0 and sv.get('lp', 0) < 0.001:
            dead_set_by_code.add(code)

# Count dead/zombie in each group
dead_in_jump = sum(1 for r in jumped_grp if r['zombie'])
dead_in_nojump = sum(1 for r in nojump_grp if r['zombie'])
dead_untested = total_dead_zombie - dead_in_jump - dead_in_nojump

print(f"Dead+zombie total: {total_dead_zombie}")
print(f"  In jump group: {dead_in_jump}")
print(f"  In no-jump group: {dead_in_nojump}")
print(f"  Untested (no price data): {dead_untested}")
print(f"  Assumed jump/nojump split: ~{round(n_j/(n_j+n_nj)*100)}% / {round(n_nj/(n_j+n_nj)*100)}%")

# Worst-case: all untested dead -> no jump, all dead = 0 over100
worst_jump = w_j
worst_nj_total = n_nj + dead_untested
worst_rate_jump = worst_jump / (n_j + dead_in_jump + dead_untested * n_j/(n_j+n_nj)) if n_j > 0 else 0
worst_rate_nojump = worst_nj_total / (n_nj + dead_in_nojump + dead_untested * n_nj/(n_j+n_nj)) if n_nj > 0 else 0

# Simpler: assume dead/zombie all = 0 over100, jump rate among survivors only
simple_wc_jump = w_j / (n_j + dead_untested * 0.24) if n_j > 0 else 0
simple_wc_nojump = w_nj / (n_nj + dead_untested * 0.76) if n_nj > 0 else 0

print(f"\n  Stress test (>100% rate):")
print(f"    Jump: {w_j/n_j*100:.0f}% → worst-case {simple_wc_jump*100:.0f}%")
print(f"    No-jump: {w_nj/n_nj*100:.0f}% → worst-case {simple_wc_nojump*100:.0f}%")

# ===== CONDITIONAL TEST: Corp background × Technical signals =====
print("\n=== CONDITIONAL TEST: Corp × Technical Signals ===")

# Build corp stock set from announcements (90-day window)
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
corp_stocks = set()
for a in (announcements or []):
    date = str(a.get('date', ''))[:10]
    if date >= cutoff:
        code = str(a.get('code', '')).strip().lstrip('0').zfill(5)
        if code:
            corp_stocks.add(code)

print(f"Corp stocks (90d): {len(corp_stocks)}")

# Use replay_results.json for technical signals
replay = load_j(os.path.join(DATA, 'replay_results.json'), {})
signals = replay.get('signals', [])

if signals:
    print(f"Replay signals: {len(signals)}")
    
    # Classify each signal: corp_background or not
    corp_sigs = [s for s in signals if s['code'] in corp_stocks]
    pure_sigs = [s for s in signals if s['code'] not in corp_stocks]
    
    print(f"  Corp background: {len(corp_sigs)} signals")
    print(f"  Pure technical: {len(pure_sigs)} signals")
    
    for label, grp in [('Corp背景 × 技術', corp_sigs), ('淨技術', pure_sigs)]:
        if not grp:
            continue
        f20 = [s.get('fwd_20d') for s in grp if s.get('fwd_20d') is not None]
        dd = [s.get('max_drawdown_20d') for s in grp if s.get('max_drawdown_20d') is not None]
        gain = [s.get('max_gain_20d') for s in grp if s.get('max_gain_20d') is not None]
        
        n = len(grp)
        nf = len(f20)
        
        if nf < 5:
            print(f"\n  {label}: n={n}, fwd20 done={nf} (insufficient)")
            continue
        
        f20.sort(); dd.sort(); gain.sort()
        wins = sum(1 for x in f20 if x > 0) / nf * 100
        med_f = f20[nf//2]
        med_dd = dd[len(dd)//2] if dd else 0
        q3_gain = gain[3*len(gain)//4] if len(gain) >= 4 else (gain[-1] if gain else 0)
        
        # By signal type
        by_type = {}
        for s in grp:
            st = s.get('signal_type', '?')
            by_type.setdefault(st, []).append(s.get('fwd_20d'))
        
        print(f"\n  {label}: n={n}")
        print(f"    median fwd_20d: {med_f*100:+.1f}%")
        print(f"    win rate: {wins:.0f}%")
        print(f"    median maxDD: {med_dd*100:+.1f}%")
        print(f"    Q3 max_gain: {q3_gain*100:+.1f}%")
        
        for st, vals in sorted(by_type.items(), key=lambda x: -len(x[1])):
            valid = [v for v in vals if v is not None]
            if len(valid) < 10:
                continue
            valid.sort()
            print(f"      {st}: n={len(valid)}, med={valid[len(valid)//2]*100:+.1f}%, win={sum(1 for v in valid if v>0)/len(valid)*100:.0f}%")
else:
    print("  No replay signals found — run replay_signals.py first")

print("\n=== DONE ===")
