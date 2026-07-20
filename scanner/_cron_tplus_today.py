"""T+1~T+5 placement tracking for 2026-06-24 report."""
import json, sys, os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

hkt = timezone(timedelta(hours=8))
now = datetime.now(hkt)
today = now.strftime('%Y-%m-%d')
cutoff = (now - timedelta(days=7)).strftime('%Y-%m-%d')

with open('data/announcements.json') as f:
    anns = json.load(f)

EXCLUDE_TITLE_ANY = [
    'CONVERTIBLE BOND', 'CONVERTIBLE BONDS', '配股完成', 'COMPLETION OF PLACING',
    '認購完成', 'COMPLETION OF SUBSCRIPTION', 'LAPSE OF', 'TERMINATION',
    '澄清公告', 'MONTHLY UPDATE', 'EXTENSION OF', 'DELAY IN DESPATCH',
    'POLL RESULTS', 'VOTING RESULTS', 'UPDATE ON ISSUE OF SCHEME SHARES',
    'DOMESTIC SHARE SUBSCRIPTION', 'REVISED TIMETABLE', 'FURTHER DELAY',
    'PROPOSED OFFERING OF HKD-DENOMINATED',
]

def is_cb_cluster(code, all_anns):
    for a in all_anns:
        title_upper = (a.get('title') or '').upper()
        if a.get('code') == code and 'CONVERTIBLE BOND' in title_upper:
            return True
    return False

def should_exclude(a, all_anns):
    title = (a.get('title') or '').upper()
    if is_cb_cluster(a.get('code'), all_anns):
        return True, 'CB_cluster'
    for kw in EXCLUDE_TITLE_ANY:
        if kw.upper() in title:
            return True, kw
    types = a.get('types', [])
    if '供股' in types:
        return True, '供股'
    if 'CONNECTED TRANSACTION' in title or '關連交易' in title:
        return True, 'connected_tx'
    if 'PLACING OF SHARES IN KINGBOARD' in title:
        return True, 'parent_placing'
    return False, ''

results = []
excluded = []
for a in anns:
    a_date = a.get('date', '')
    if a_date < cutoff or a_date >= today:
        continue
    types = a.get('types', [])
    if '配股' not in types:
        continue
    exclude, reason = should_exclude(a, anns)
    if exclude:
        excluded.append({'code': a.get('code'), 'name': a.get('name'), 'date': a_date, 'reason': reason})
        continue
    results.append({
        'code': a.get('code'), 'name': a.get('name', ''), 'date': a_date,
        'title': (a.get('title') or '')[:80], 'types': types,
    })

print(f"=== Filtered placements for T+ tracking: {len(results)} ===")
for r in results:
    ann_date = datetime.strptime(r['date'], '%Y-%m-%d').replace(tzinfo=hkt)
    t_plus = (now - ann_date).days
    print(f"{r['code']} {r['name']} | T+{t_plus} | {r['date']} | {r['title']}")

print(f"\n=== Excluded: {len(excluded)} ===")
from collections import Counter
for reason, count in Counter(e['reason'] for e in excluded).most_common():
    print(f"  {reason}: {count}")

# Price action check
print(f"\n=== Price check ===")
import yfinance as yf
import time

alert_candidates = []
for r in results:
    try:
        yahoo = f"{r['code'][-4:]}.HK"
        tk = yf.Ticker(yahoo)
        df = tk.history(period='1mo', timeout=15)
        if df.empty or len(df) < 3:
            print(f"  {r['code']} {r['name']}: no data ({len(df)} rows)")
            continue
        close_now = float(df['Close'].iloc[-1])
        vol_today = float(df['Volume'].iloc[-1])
        vol_20d = float(df['Volume'].tail(21).head(20).mean()) if len(df)>=21 else float(df['Volume'].mean())
        vol_ratio = vol_today / vol_20d if vol_20d > 0 else 0

        close_ann = None
        for i in range(len(df)):
            if df.index[i].strftime('%Y-%m-%d') >= r['date']:
                close_ann = float(df['Close'].iloc[i])
                break
        if close_ann is None:
            close_ann = float(df['Close'].iloc[0])
        pct_change = (close_now - close_ann)/close_ann*100 if close_ann>0 else 0
        ann_date = datetime.strptime(r['date'], '%Y-%m-%d').replace(tzinfo=hkt)
        t_plus = (now - ann_date).days
        meets_vol = vol_ratio >= 1.5
        meets_jump_up = pct_change >= 8
        print(f"  {r['code']} {r['name']} | T+{t_plus} | {close_now:.3f} | Δ={pct_change:+.1f}% | vol={vol_ratio:.2f}x | {'🔴' if meets_vol and meets_jump_up else '🟡' if meets_vol or abs(pct_change)>=8 else '-'}")
        alert_candidates.append({**r, 'close_now': close_now, 'pct_change': pct_change, 'vol_ratio': vol_ratio, 't_plus': t_plus, 'meets_all': meets_vol and meets_jump_up})
        time.sleep(0.5)
    except Exception as e:
        print(f"  {r['code']} {r['name']}: ERROR {e}")

print(f"\n=== RED: {sum(1 for a in alert_candidates if a['meets_all'])} ===")
for a in alert_candidates:
    if a['meets_all']:
        print(f"  🔴 {a['code']} {a['name']} | T+{a['t_plus']} | Δ={a['pct_change']:+.1f}% | vol={a['vol_ratio']:.2f}x")
