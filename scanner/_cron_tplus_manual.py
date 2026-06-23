"""
Manual T+1~T+5 tracking — queries announcements.json for genuine placements,
filters false positives (CB, 復牌, parent-subsidiary), fetches yfinance,
applies strict 3-condition test.
"""
import json, os, sys, time
from datetime import datetime, timezone, timedelta

HKT = timezone(timedelta(hours=8))
now_hkt = datetime.now(HKT)
today_str = now_hkt.strftime('%Y-%m-%d')
cutoff = (now_hkt - timedelta(days=7)).strftime('%Y-%m-%d')

# Load announcements
with open('data/announcements.json') as f:
    anns = json.load(f)

# CB keywords from skill
CB_KEYWORDS = [
    'CONVERTIBLE BOND', 'ZERO COUPON', 'FIXED RATE', 'NOTES DUE',
    'PERPETUAL SUBORDINATED', 'CONTINGENT CONVERTIBLE',
    'CONVERTIBLE BONDS', 'SENIOR NOTES'
]

def is_cb(title):
    """Check if announcement title indicates a convertible bond / debt issuance."""
    t = (title or '').upper()
    for kw in CB_KEYWORDS:
        if kw in t:
            if 'PLACING' in t:
                return True  # Lenovo case: "PROPOSED ISSUANCE OF US$... ZERO COUPON CONVERTIBLE BONDS"
            if 'SHARES' not in t:
                return True
    return False

def is_resumption(title):
    """復牌 = exchange notice about trading resumption, not a corp action."""
    t = (title or '')
    return '復牌' in t or 'RESUMPTION' in t.upper()

def is_parent_subsidiary(title, code):
    """Parent company placing/disposing subsidiary shares."""
    t = (title or '').upper()
    if code == '00148' and 'KINGBOARD LAMINATES' in t:
        return True
    if 'PLACING OF SHARES IN' in t:
        return True
    return False

def code_to_yahoo(code):
    """Convert HK stock code to yahoo ticker."""
    c = code.lstrip('0') or '0'
    return f"{c}.HK"

# Filter to genuine placements
genuine = []
skip_reasons = {}

for a in anns:
    types = a.get('types', [])
    if not isinstance(types, list):
        types = []
    adate = a.get('date', '')
    
    if adate < cutoff or adate >= today_str:
        continue
    
    if '配股' not in types:
        continue
    
    code = a.get('code', '')
    name = a.get('name', '')
    title = a.get('title', '') or a.get('title_en', '') or ''
    
    # False positive filters
    if is_cb(title):
        skip_reasons.setdefault('CB/可換股債券', []).append(f"{code} {name} ({adate})")
        continue
    
    if is_resumption(title):
        skip_reasons.setdefault('復牌', []).append(f"{code} {name} ({adate})")
        continue
    
    if is_parent_subsidiary(title, code):
        skip_reasons.setdefault('母公司減持子公司', []).append(f"{code} {name} ({adate})")
        a['_flag'] = 'parent_subsidiary'
        genuine.append(a)
        continue
    
    genuine.append(a)

# Deduplicate by code (keep most recent)
seen = {}
for a in sorted(genuine, key=lambda x: x.get('date', ''), reverse=True):
    code = a.get('code', '')
    if code not in seen:
        seen[code] = a

genuine_deduped = sorted(seen.values(), key=lambda x: x.get('date', ''))

print(f"=== T+ Tracking: Genuine Placements ===")
print(f"After filtering: {len(genuine_deduped)} unique stocks")
print(f"Skip reasons:")
for reason, items in skip_reasons.items():
    print(f"  {reason}: {len(items)}")
    for item in items[:5]:
        print(f"    - {item}")
    if len(items) > 5:
        print(f"    ... +{len(items)-5} more")

print(f"\n--- Genuine placements for T+ check ---")
for a in genuine_deduped:
    flag = f" ⚠️{a['_flag']}" if a.get('_flag') else ''
    print(f"  {a['code']} {a['name']} | date={a['date']} | types={a.get('types')}{flag}")

# Now yfinance check
print(f"\n=== yfinance Price/Volume Check ===")
results = []

for a in genuine_deduped:
    code = a['code']
    name = a['name']
    adate = a['date']
    flag = a.get('_flag', '')
    
    ticker = code_to_yahoo(code)
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        df_1mo = tk.history(period='1mo', timeout=15)
        if df_1mo.empty:
            print(f"  {code} {name}: NO DATA (delisted?)")
            results.append({**a, 'status': 'no_data', 'error': 'empty df'})
            continue
        
        # Current close
        close_now = float(df_1mo['Close'].iloc[-1])
        
        # Find the close on announcement day or the next trading day
        adate_dt = datetime.strptime(adate, '%Y-%m-%d')
        df_local = df_1mo.copy()
        df_local.index = df_local.index.tz_localize(None) if df_local.index.tz is None else df_local.index.tz_convert(None)
        
        # Find closest trading day on or after ann date
        ann_idx = None
        for i, idx in enumerate(df_local.index):
            if idx >= adate_dt:
                ann_idx = i
                break
        
        if ann_idx is None:
            ann_close = close_now
            print(f"  {code} {name}: ann date {adate} out of range, using latest")
        else:
            ann_close = float(df_1mo['Close'].iloc[ann_idx])
        
        # T+ days (days since announcement)
        if ann_idx is not None:
            t_plus = len(df_1mo) - 1 - ann_idx
        else:
            t_plus = '?'
        
        # Price change
        pct_change = ((close_now - ann_close) / ann_close * 100) if ann_close > 0 else 0
        
        # Volume ratio
        vols = df_1mo['Volume'].values
        vol_today = float(vols[-1])
        vol_20avg = float(vols[-21:-1].mean()) if len(vols) >= 21 else float(vols.mean())
        vol_ratio = vol_today / vol_20avg if vol_20avg > 0 else 0
        
        # Check 3 conditions
        is_placement = True  # all are placements at this point
        vol_ok = vol_ratio >= 1.5
        jump_ok = pct_change >= 8.0
        
        # RED if ALL 3
        is_red = is_placement and vol_ok and jump_ok
        
        status = '🔴RED' if is_red else ('🟡PARTIAL' if (vol_ok or jump_ok) else '⚪NONE')
        if flag:
            status += ' ⚠️parent_subsidiary'
        
        print(f"  {code} {name} | ann={adate} T+{t_plus} | close_ann={ann_close:.3f}→{close_now:.3f} | jump={pct_change:+.1f}% | vol={vol_ratio:.1f}x | {status}")
        
        results.append({
            'code': code, 'name': name, 'date': adate,
            'close_ann': round(ann_close, 3), 'close_now': round(close_now, 3),
            'pct_change': round(pct_change, 1), 'vol_ratio': round(vol_ratio, 2),
            't_plus': t_plus,
            'is_red': is_red, 'is_partial': not is_red and (vol_ok or jump_ok),
            'types': a.get('types', []), 'flag': flag
        })
        time.sleep(0.5)
        
    except Exception as e:
        print(f"  {code} {name}: ERROR - {e}")
        results.append({**a, 'status': 'error', 'error': str(e)})

# Summary
reds = [r for r in results if r.get('is_red')]
partials = [r for r in results if r.get('is_partial')]
print(f"\n=== SUMMARY ===")
print(f"🔴 RED (meets ALL 3): {len(reds)}")
for r in reds:
    print(f"  {r['code']} {r['name']} | T+{r['t_plus']} | +{r['pct_change']}% | {r['vol_ratio']}x")
print(f"🟡 PARTIAL (1-2 conditions): {len(partials)}")
for r in partials:
    print(f"  {r['code']} {r['name']} | T+{r['t_plus']} | +{r['pct_change']}% | {r['vol_ratio']}x")
print(f"⚪ NO TRIGGER: {len(results) - len(reds) - len(partials)}")

# Save output
output = {
    'scan_time': now_hkt.strftime('%Y-%m-%d %H:%M HKT'),
    'genuine_count': len(genuine_deduped),
    'red_alerts': reds,
    'partial_matches': partials,
    'all_results': results,
    'skip_reasons': {k: len(v) for k, v in skip_reasons.items()},
    'skip_detail': {k: v for k, v in skip_reasons.items()}
}
with open('scanner/tplus_result.json', 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)
print(f"\nResults saved to scanner/tplus_result.json")
