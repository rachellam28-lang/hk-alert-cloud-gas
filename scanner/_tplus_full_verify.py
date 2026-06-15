"""Full T+1~T+5 verification for ALL placements in window, with false-positive filtering."""
import json
import os
import glob
from datetime import datetime, timedelta

BASE = r"C:\Users\Administrator\Desktop\automatic\ccass-debug"
RAW = os.path.join(BASE, "raw")

# False positive patterns
FP_PATTERNS = [
    "CONVERTIBLE BONDS", "Notes due", "Fixed Rate", "Perpetual Subordinated",
    "Conversion Price", "CONVERSION AND CANCELLATION OF",
    "COMPLETION OF", "配股完成", "認購完成",
    "SUPPLEMENTAL ANNOUNCEMENT", "補充公告",
    "EXTENSION OF", "REVISION OF",
    "LAPSE OF",
    "MONTHLY UPDATE IN RELATION TO",
    "PROPOSED INITIAL PUBLIC OFFERING", "ISSUANCE OF A SHARES", "A SHARES",
]

def is_false_positive(title_cn, title_en):
    """Check if announcement is a false positive (debt, completion, supplemental, etc)."""
    text = f"{title_cn or ''} {title_en or ''}".upper()
    for pat in FP_PATTERNS:
        if pat.upper() in text:
            return True, pat
    # Debt: title with "$... Securities" but not "Placing"/"Subscription"/"Allotment"
    if "SECURITIES" in text and "$" in text:
        if not any(kw in text for kw in ["PLACING", "SUBSCRIPTION", "ALLOTMENT"]):
            return True, "debt_securities"
    return False, ""

def load_announcements():
    p = os.path.join(BASE, "data", "announcements.json")
    with open(p, 'r') as f:
        return json.load(f)

def load_all_prices():
    prices = {}
    for f in sorted(glob.glob(os.path.join(RAW, "prices_*.json"))):
        fn = os.path.basename(f)
        date_str = fn.replace("prices_", "").replace(".json", "")
        dt = datetime.strptime(date_str, "%Y%m%d")
        date_key = dt.strftime("%Y-%m-%d")
        with open(f, 'r') as fh:
            prices[date_key] = json.load(fh)
    return prices

def get_close(prices, code, date_str):
    if date_str not in prices or code not in prices[date_str]:
        return None
    v = prices[date_str][code]
    if isinstance(v, (int, float)):
        return float(v)
    elif isinstance(v, dict):
        return v.get("close")
    return None

def get_vol(prices, code, date_str):
    if date_str not in prices or code not in prices[date_str]:
        return None
    v = prices[date_str][code]
    if isinstance(v, dict):
        return v.get("vol")
    return None

def compute_20d_avg_vol(prices, code, date_str, max_lookback=30):
    vols = []
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(1, max_lookback + 1):
        prev = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        v = get_vol(prices, code, prev)
        if v is not None and v > 0:
            vols.append(v)
        if len(vols) >= 20:
            break
    if len(vols) >= 5:
        return sum(vols) / len(vols)
    return 0

# Load data
anns = load_announcements()
prices = load_all_prices()
available_dates = sorted(prices.keys())
print(f"Loaded {len(anns)} announcements, {len(available_dates)} price snapshots")
print(f"Date range: {available_dates[0]} to {available_dates[-1]}")
print()

# Determine T+ window
today = datetime(2026, 6, 12)
today_str = today.strftime("%Y-%m-%d")
# T+1~T+5 means announcements from calendar days T-5 through T-1
# But June 7-8 is weekend, so trading days T+ are:
# T+1 = Jun 15 (Mon), T+1 side means ann from Jun 11
# T+5 = Jun 19 (Fri), T+5 side means ann from Jun 5
# Actually simpler: announcements from Jun 4 to Jun 12
# T+1~T+5 from today covers ann dates Jun 4-11 (plus T+0 today)
window_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")

print(f"T+ window: announcements from {window_start} to {today_str}")
print()

# Step 1: Filter for placement type in window
placements = []
fp_skipped = []
for a in anns:
    dt = a.get('date', '')
    if dt < window_start or dt > today_str:
        continue
    ctype = a.get('type', '').lower()
    if ctype not in ('placement', '配售', '配股', 'block_trade'):
        continue
    
    title_cn = a.get('title_cn', '') or a.get('title', '')
    title_en = a.get('title_en', '')
    is_fp, fp_reason = is_false_positive(title_cn, title_en)
    if is_fp:
        fp_skipped.append({**a, 'fp_reason': fp_reason})
        continue
    
    placements.append(a)

print(f"Placements in T+ window: {len(placements)} (filtered out {len(fp_skipped)} false positives)")
for fp in fp_skipped:
    print(f"  FP: {fp.get('code','')} {fp.get('name','')} | {fp.get('date','')} | reason={fp['fp_reason']}")
print()

# Get scanner data for vol ratios
scanner_file = os.path.join(BASE, "scanner", "corp_scan_result.json")
scanner_vols = {}
if os.path.exists(scanner_file):
    with open(scanner_file) as f:
        sd = json.load(f)
    for a in sd.get('alerted', []) + sd.get('watchlisted', []):
        code = a.get('code', '')
        vr = a.get('volume_ratio')
        if code and vr:
            scanner_vols[code] = vr

# Step 2: T+ verification for each placement
results = []
for p in placements:
    code = p.get('code', '')
    name = p.get('name', code)
    ann_date = p.get('date', '')
    ctype = p.get('type', '')
    title_cn = p.get('title_cn', '') or p.get('title', '')
    
    print(f"--- {code} {name} | {ctype} | {ann_date} ---")
    
    # Check if stock exists
    found = False
    for d in available_dates:
        if code in prices[d]:
            found = True
            break
    if not found:
        print(f"  No price data")
        results.append({'code': code, 'name': name, 'ctype': ctype, 'ann_date': ann_date,
                       'skip_reason': 'no_price_data', 'is_red': False, 'title_cn': title_cn})
        print()
        continue
    
    # Find ann close
    ann_close = get_close(prices, code, ann_date)
    actual_ann_date = ann_date
    if ann_close is None:
        dt = datetime.strptime(ann_date, "%Y-%m-%d")
        for i in range(1, 8):
            nd = (dt + timedelta(days=i)).strftime("%Y-%m-%d")
            ann_close = get_close(prices, code, nd)
            if ann_close is not None:
                actual_ann_date = nd
                break
    if ann_close is None:
        print(f"  Cannot determine ann close")
        results.append({'code': code, 'name': name, 'ctype': ctype, 'ann_date': ann_date,
                       'skip_reason': 'no_ann_close', 'is_red': False, 'title_cn': title_cn})
        print()
        continue
    
    # Volume ratio
    ann_vol = get_vol(prices, code, actual_ann_date)
    avg_vol = compute_20d_avg_vol(prices, code, actual_ann_date)
    scanner_vr = scanner_vols.get(code)
    
    if avg_vol > 0 and ann_vol is not None:
        vol_ratio = ann_vol / avg_vol
        vol_source = "computed"
    elif scanner_vr is not None:
        vol_ratio = scanner_vr
        vol_source = "scanner"
    else:
        vol_ratio = 0
        vol_source = "unavailable"
    
    print(f"  Close: {ann_close:.4f} ({actual_ann_date}) | Vol: {vol_ratio:.1f}x ({vol_source})")
    
    # Price floor check
    if ann_close < 0.05:
        print(f"  → SKIP: price < $0.05 (penny stock noise)")
        results.append({'code': code, 'name': name, 'ctype': ctype, 'ann_date': ann_date,
                       'ann_close': ann_close, 'vol_ratio': vol_ratio,
                       'skip_reason': 'price<0.05', 'is_red': False, 'title_cn': title_cn})
        print()
        continue
    
    # T+ checks
    tplus_days = []
    dt_ann = datetime.strptime(actual_ann_date, "%Y-%m-%d")
    for offset in range(1, 6):
        td = (dt_ann + timedelta(days=offset)).strftime("%Y-%m-%d")
        tclose = get_close(prices, code, td)
        if tclose is not None:
            jump = (tclose - ann_close) / ann_close * 100
            tplus_days.append((offset, td, tclose, jump))
            print(f"  T+{offset} ({td}): {tclose:.4f}, {jump:+.1f}%")
    
    if not tplus_days:
        print(f"  No T+ data")
        is_t0 = ann_date == today_str
        reason = "T+ pending — announced today" if is_t0 else "no_tplus_data"
        results.append({'code': code, 'name': name, 'ctype': ctype, 'ann_date': ann_date,
                       'ann_close': ann_close, 'vol_ratio': vol_ratio,
                       'skip_reason': reason, 'is_red': False, 'title_cn': title_cn})
        print()
        continue
    
    max_jump = max(d[3] for d in tplus_days)
    max_jump_t = next(d[0] for d in tplus_days if d[3] == max_jump)
    is_penny = ann_close < 0.50
    
    is_placement_type = ctype in ('placement', '配售', '配股')
    vol_ok = vol_ratio >= 1.5
    jump_ok = max_jump >= 8.0
    
    if not is_placement_type:
        skip = f"type={ctype}(非配售)"
    elif not vol_ok:
        skip = f"vol={vol_ratio:.1f}x<1.5x"
    elif not jump_ok:
        skip = f"jump={max_jump:.1f}%<8%"
    else:
        skip = ""
    
    alert_level = "RED" if (is_placement_type and vol_ok and jump_ok) else "WATCHLIST"
    
    print(f"  → {alert_level} | skip: {skip}")
    print()
    
    results.append({
        'code': code, 'name': name, 'ctype': ctype, 'ann_date': ann_date,
        'actual_ann_date': actual_ann_date, 'ann_close': round(ann_close, 4),
        'vol_ratio': round(vol_ratio, 1), 'vol_source': vol_source,
        'max_jump': round(max_jump, 1), 'max_jump_t': max_jump_t,
        'is_red': alert_level == 'RED', 'skip_reason': skip,
        'is_penny': is_penny, 'title_cn': title_cn,
    })

# Summary
print("=" * 60)
print("=== SUMMARY ===")
reds = [r for r in results if r['is_red']]
watches = [r for r in results if not r['is_red']]
print(f"🔴 RED: {len(reds)}")
print(f"🟡 WATCHLIST: {len(watches)}")
print(f"🚫 FP SKIPPED: {len(fp_skipped)}")
print()

for r in reds:
    print(f"🔴 {r['code']} {r['name']} | {r['ctype']} | T+{r['max_jump_t']} +{r['max_jump']}% | vol {r['vol_ratio']}x")
    
if not reds:
    print("No RED alerts.")

print()
print("Watchlist:")
for r in watches:
    print(f"🟡 {r['code']} {r['name']} | {r['ann_date']} | skip: {r.get('skip_reason','?')}")

# Save
out = {
    'scan_date': today_str,
    'red_alerts': [r for r in results if r['is_red']],
    'watchlist': [r for r in results if not r['is_red']],
    'fp_skipped': fp_skipped,
}
outpath = os.path.join(BASE, "scanner", "_tplus_full_verify.json")
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print(f"\nSaved to _tplus_full_verify.json")
