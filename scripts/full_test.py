"""
FULL run: pull ALL missing prices + 8120 test + conditional test.
Monolithic — single process, no concurrent writes.
"""
import json, time, statistics, os
import yfinance as yf
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')

def load(path, default=None):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return default

def save(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

def pad(code):
    return str(code).strip().lstrip('0').zfill(5)

def yf_pull(code):
    """Try multiple ticker formats for yfinance HK stocks."""
    formats = [f'{code}.HK']
    try:
        clean = str(int(code))
        if clean != code:
            formats.append(f'{clean}.HK')
    except:
        pass
    if code.startswith('0') and len(code) == 5:
        formats.insert(0, f'{int(code)}.HK')  # 005 → 5.HK first for GEM
    for fmt in formats:
        try:
            df = yf.Ticker(fmt).history(period='2y')
            if df is not None and not df.empty:
                records = []
                for idx, row in df.iterrows():
                    records.append({
                        'date': str(idx)[:10],
                        'open': float(row['Open']), 'high': float(row['High']),
                        'low': float(row['Low']), 'close': float(row['Close']),
                        'volume': float(row['Volume']),
                    })
                return records
        except:
            continue
    return None

# ===== STEP 1: Pull all missing prices =====
print("=== STEP 1: Pull prices ===")

holdings = load(os.path.join(BASE, 'holdings.json'), {})
placements = load(os.path.join(DATA, 'placements_enriched.json'), [])
hist = load(os.path.join(DATA, 'price_history.json'), {})

all_needed = set()
for s in (holdings.get('stocks') or []):
    all_needed.add(pad(s['c']))
for p in (placements or []):
    all_needed.add(pad(p.get('code', '')))
all_needed.discard('00000')

missing = sorted(all_needed - set(hist.keys()))
print(f"Need: {len(missing)} stocks (total universe: {len(all_needed)})")

pulled, failed, yf_no_data = 0, 0, 0
for i, code in enumerate(missing):
    records = yf_pull(code)
    if records:
        hist[code] = records
        pulled += 1
    elif records is None:
        failed += 1
    else:
        yf_no_data += 1

    if (i+1) % 100 == 0:
        save(os.path.join(DATA, 'price_history.json'), hist)
        print(f"  {i+1}/{len(missing)} (pulled {pulled}, fail {failed}, nodata {yf_no_data})")
    time.sleep(0.1)

save(os.path.join(DATA, 'price_history.json'), hist)
print(f"Pull done: +{pulled}, fail={failed}, nodata={yf_no_data}, total={len(hist)}")

# ===== Check zombie+dead =====
live_codes = {pad(s['c']) for s in (holdings.get('stocks') or [])}
yf_codes = set(hist.keys())
not_in_holdings = yf_codes - live_codes
not_in_yf = live_codes - yf_codes

zombies = 0
for code in live_codes:
    s = next((x for x in holdings['stocks'] if pad(x['c']) == code), None)
    if s and s.get('vol', 0) == 0 and s.get('hi52') == s.get('lo52'):
        zombies += 1

print(f"\nData quality:")
print(f"  In yf but NOT in holdings (delisted): {len(not_in_holdings)}")
print(f"  In holdings but NOT in yf (yf gap): {len(not_in_yf)}")
print(f"  Zombie (0 vol + frozen price): {zombies}")
print(f"  True dead+zombie rate: {(len(not_in_holdings)+zombies)}/{len(live_codes)} ({(len(not_in_holdings)+zombies)/len(live_codes)*100:.1f}%)")

# ===== STEP 2: 8120 Pattern Test (full universe) =====
print("\n=== STEP 2: 8120 Pattern Test (8% threshold) ===")

def trading_dates_after(pxs, d0, n):
    ds = sorted(k for k in pxs if k > d0)
    return ds[:n]

results_8120 = []
for p in (placements or []):
    code = pad(p.get('code', ''))
    pxs = hist.get(code)
    if not pxs:
        continue

    d0 = p.get('date', '') or p.get('announcement_date', '') or ''
    if len(d0) > 10:
        d0 = d0[:10]

    px_map = {r['date']: r['close'] for r in pxs}
    sorted_dates = sorted(px_map.keys())

    # Find entry date (announcement date or next trading day)
    entry_date = None
    for d in sorted_dates:
        if d >= d0:
            entry_date = d
            break
    if not entry_date or entry_date not in px_map:
        continue

    base = px_map[entry_date]
    if base <= 0.001:
        continue

    next5 = trading_dates_after(px_map, entry_date, 5)
    if not next5:
        continue

    # Check for 8% jump
    jump_day = None
    for d in next5:
        if d in px_map and px_map[d] / base - 1 > 0.08:
            jump_day = d
            break

    entry_day = jump_day if jump_day else next5[0]
    entry_px = px_map[entry_day]
    after = trading_dates_after(px_map, entry_day, 60)

    if len(after) < 20:
        continue

    fwd20 = px_map[after[19]] / entry_px - 1
    gains = [px_map[d] / entry_px - 1 for d in after if d in px_map]
    max_gain = max(gains) if gains else 0
    dd20 = min(px_map[d] / entry_px - 1 for d in after[:20] if d in px_map)
    win = fwd20 > 0

    discount = p.get('discount_pct') or p.get('discount')

    results_8120.append({
        'code': code, 'name': p.get('name', ''),
        'date': entry_date, 'jumped': bool(jump_day),
        'fwd20': round(fwd20, 4), 'max_gain_60d': round(max_gain, 4),
        'dd_20d': round(dd20, 4), 'win': win,
        'discount': discount,
    })

jumped = [r for r in results_8120 if r['jumped']]
nojump = [r for r in results_8120 if not r['jumped']]

for label, grp in [('Jump', jumped), ('No Jump', nojump)]:
    n = len(grp)
    f20 = [r['fwd20'] for r in grp]
    g60 = [r['max_gain_60d'] for r in grp]
    dd = [r['dd_20d'] for r in grp]
    wins = sum(1 for r in grp if r['win']) / n * 100
    over100 = sum(1 for x in g60 if x > 1.0) / len(g60) * 100 if g60 else 0

    f20.sort(); g60.sort(); dd.sort()
    print(f"\n{label} (n={n}):")
    print(f"  fwd20 Q1/Q2/Q3: {f20[len(f20)//4]*100:+.1f}% / {f20[len(f20)//2]*100:+.1f}% / {f20[3*len(f20)//4]*100:+.1f}%")
    print(f"  maxGain60 Q1/Q2/Q3: {g60[len(g60)//4]*100:+.1f}% / {g60[len(g60)//2]*100:+.1f}% / {g60[3*len(g60)//4]*100:+.1f}%")
    print(f"  win_rate: {wins:.0f}%")
    print(f"  >100% in 60d: {sum(1 for x in g60 if x > 1.0)}/{len(g60)} ({over100:.0f}%)")
    print(f"  maxDD median: {dd[len(dd)//2]*100:+.1f}%")

# Worst-case: assume all missing placements are dead
n_missing = max(0, len(placements) - len(results_8120))
if n_missing > 0 and jumped:
    jn = len(jumped) + int(n_missing * len(jumped) / (len(jumped) + len(nojump)))
    nn = len(nojump) + n_missing - int(n_missing * len(jumped) / (len(jumped) + len(nojump)))
    jw = sum(1 for r in jumped if r['max_gain_60d'] > 1.0)
    nw = sum(1 for r in nojump if r['max_gain_60d'] > 1.0)
    print(f"\nWorst-case (add {n_missing} missing as dead):")
    print(f"  Jump: >100% rate drops to {jw}/{jn} ({jw/jn*100:.0f}%)")
    print(f"  No-jump: >100% rate drops to {nw}/{nn} ({nw/nn*100:.0f}%)")

print(f"\nTested: {len(results_8120)}/{len(placements)} placements")

# ===== STEP 3: Conditional Test (corp × POC/FVG) =====
print("\n=== STEP 3: Conditional Test (corp background × POC/FVG) ===")

# Load corp events from announcements.json
anns = load(os.path.join(DATA, 'announcements.json'), [])
corp_codes = set()
corp_dates = defaultdict(set)  # code → {dates with corp action}
for a in (anns or []):
    code = pad(a.get('code', ''))
    d = a.get('date', '')[:10]
    if code and d:
        corp_codes.add(code)
        corp_dates[code].add(d)

# Load replay results
replay = load(os.path.join(DATA, 'replay_results.json'), {})
signals = replay.get('signals', []) if replay else []

# Classify: corp background = signal_date within 60d of a corp action
corp_bg = []
nocorp_bg = []
for s in signals:
    code = s.get('code', '')
    sdate = s.get('date', '')[:10]
    corp_dates_for_code = corp_dates.get(code, set())
    has_corp = any(abs_days(sdate, cd) <= 60 for cd in corp_dates_for_code) if corp_dates_for_code else False
    (corp_bg if has_corp else nocorp_bg).append(s)

from datetime import datetime, timedelta
def abs_days(d1, d2):
    try:
        dt1 = datetime.strptime(d1, '%Y-%m-%d')
        dt2 = datetime.strptime(d2, '%Y-%m-%d')
        return abs((dt1 - dt2).days)
    except:
        return 999

# By signal type
for label, grp in [('corp背景', corp_bg), ('純技術(無corp)', nocorp_bg)]:
    if not grp:
        continue

    types = defaultdict(list)
    for s in grp:
        types[s.get('signal_type', '?')].append(s)

    print(f"\n{label} ({len(grp)} signals):")
    for stype, sigs in sorted(types.items(), key=lambda x: -len(x[1])):
        n = len(sigs)
        f20 = [s.get('fwd_20d') for s in sigs if s.get('fwd_20d') is not None]
        g60 = [s.get('max_gain_20d') for s in sigs if s.get('max_gain_20d') is not None]
        wins = sum(1 for x in f20 if x > 0) / len(f20) * 100 if f20 else 0

        if len(f20) < 10:
            print(f"  {stype}: n={n} (insufficient)")
            continue

        f20.sort()
        m20 = f20[len(f20)//2]
        print(f"  {stype}: n={n}, med_fwd20={m20*100:+.1f}%, win={wins:.0f}%", end="")
        if g60:
            g60.sort()
            gmed = g60[len(g60)//2]
            print(f", med_maxGain20={gmed*100:+.1f}%")
        else:
            print()

print("\nDone.")
