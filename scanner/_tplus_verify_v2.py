"""Precise T+1~T+5 close-to-close verification using raw price snapshots.
Handles both legacy (float=close) and new (dict={close,vol,...}) formats."""
import json
import os
import glob
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "raw"

candidates = [
    ("00700", "騰訊", "2026-06-05", "配售", None),
    ("01912", "CONTEL", "2026-06-08", "配股", None),
    ("00953", "SHAW BROTHERS", "2026-06-08", "配股", None),
    ("09936", "XIMEI RESOURCES", "2026-06-08", "配股", None),
    ("01815", "EVEREST GOLD", "2026-06-08", "配股", None),
    ("00994", "CT VISION", "2026-06-08", "配股", None),
    ("00254", "NUR HOLDINGS", "2026-06-08", "配股", None),
    ("02186", "LUYE PHARMA", "2026-06-11", "配股", 0.38),
]

def load_all_prices():
    prices = {}
    for f in sorted(glob.glob(str(BASE / "prices_*.json"))):
        fn = os.path.basename(f)
        date_str = fn.replace("prices_", "").replace(".json", "")
        dt = datetime.strptime(date_str, "%Y%m%d")
        date_key = dt.strftime("%Y-%m-%d")
        with open(f, 'r') as fh:
            prices[date_key] = json.load(fh)
    return prices

def get_close(prices, code, date_str):
    """Get close price. Handles float (legacy) and dict (new) formats."""
    if date_str not in prices or code not in prices[date_str]:
        return None
    v = prices[date_str][code]
    if isinstance(v, (int, float)):
        return float(v)
    elif isinstance(v, dict):
        return v.get("close")
    return None

def get_vol(prices, code, date_str):
    """Get volume. Only available in dict-format snapshots."""
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

print("=== Precise T+1~T+5 Close-to-Close Verification (Price Snapshots) ===\n")

prices = load_all_prices()
available_dates = sorted(prices.keys())
print(f"Loaded {len(available_dates)} date snapshots: {available_dates[0]} to {available_dates[-1]}\n")

results = []

for code, name, ann_date_str, ctype, scanner_vol_ratio in candidates:
    print(f"--- {code} {name} | {ctype} | Ann: {ann_date_str} ---")
    
    # Check if stock exists in price data
    found_in_any = False
    for d in available_dates:
        if code in prices[d]:
            found_in_any = True
            break
    
    if not found_in_any:
        print(f"  No price data in any snapshot\n")
        results.append({
            'code': code, 'name': name, 'ctype': ctype,
            'ann_date': ann_date_str,
            'skip_reason': 'no_price_data', 'is_red': False
        })
        continue
    
    # Find ann close
    ann_close = get_close(prices, code, ann_date_str)
    actual_ann_date = ann_date_str
    
    if ann_close is None:
        dt = datetime.strptime(ann_date_str, "%Y-%m-%d")
        for i in range(1, 8):
            nd = (dt + timedelta(days=i)).strftime("%Y-%m-%d")
            ann_close = get_close(prices, code, nd)
            if ann_close is not None:
                actual_ann_date = nd
                break
    
    if ann_close is None:
        print(f"  Cannot determine ann close\n")
        results.append({
            'code': code, 'name': name, 'ctype': ctype,
            'ann_date': ann_date_str, 'skip_reason': 'no_ann_close', 'is_red': False
        })
        continue
    
    # Volume ratio: prefer computed from snapshots, fallback to scanner
    ann_vol = get_vol(prices, code, actual_ann_date)
    avg_vol_20d = compute_20d_avg_vol(prices, code, actual_ann_date)
    if avg_vol_20d > 0 and ann_vol is not None:
        ann_vol_ratio = ann_vol / avg_vol_20d
        vol_source = "computed"
    elif scanner_vol_ratio is not None:
        ann_vol_ratio = scanner_vol_ratio
        vol_source = "scanner"
    else:
        ann_vol_ratio = 0
        vol_source = "unavailable"
    
    print(f"  Ann close: {ann_close:.4f} (on {actual_ann_date})")
    if vol_source == "computed":
        print(f"  Vol ratio: {ann_vol_ratio:.1f}x (ann_vol={ann_vol}, 20d_avg={avg_vol_20d:.0f})")
    else:
        print(f"  Vol ratio: {ann_vol_ratio:.1f}x (source: {vol_source})")
    
    # T+ checks
    tplus_days = []
    dt_ann = datetime.strptime(actual_ann_date, "%Y-%m-%d")
    
    for offset in range(1, 6):
        td = (dt_ann + timedelta(days=offset)).strftime("%Y-%m-%d")
        tclose = get_close(prices, code, td)
        if tclose is not None:
            jump = (tclose - ann_close) / ann_close * 100
            tplus_days.append((offset, td, tclose, jump))
            print(f"  T+{offset} ({td}): close={tclose:.4f}, jump={jump:+.1f}%")
        else:
            print(f"  T+{offset} ({td}): no data")
    
    if not tplus_days:
        print(f"  No T+ data available\n")
        results.append({
            'code': code, 'name': name, 'ctype': ctype,
            'ann_date': ann_date_str, 'ann_close': ann_close,
            'ann_vol_ratio': round(ann_vol_ratio, 1),
            'skip_reason': 'no_tplus_data', 'is_red': False
        })
        continue
    
    max_jump = max(d[3] for d in tplus_days)
    max_jump_t = next(d[0] for d in tplus_days if d[3] == max_jump)
    is_penny = ann_close < 0.50
    
    is_placement = ctype in ('配售', '配股')
    vol_ok = ann_vol_ratio >= 1.5
    jump_ok = max_jump >= 8.0
    
    if not is_placement:
        skip = f"type={ctype}(非配售)"
    elif not vol_ok:
        skip = f"vol={ann_vol_ratio:.1f}x<1.5x"
    elif not jump_ok:
        skip = f"jump={max_jump:.1f}%<8%"
    else:
        skip = ""
    
    alert_level = "RED" if (is_placement and vol_ok and jump_ok) else "WATCHLIST"
    penny_flag = " ⚠️" if is_penny else ""
    
    print(f"  → {alert_level} | skip: {skip} | penny={'yes' + penny_flag if is_penny else 'no'}")
    print()
    
    results.append({
        'code': code, 'name': name, 'ctype': ctype,
        'ann_date': ann_date_str, 'actual_ann_date': actual_ann_date,
        'ann_close': round(ann_close, 4),
        'ann_vol_ratio': round(ann_vol_ratio, 1), 'vol_source': vol_source,
        'max_jump': round(max_jump, 1), 'max_jump_t': max_jump_t,
        'tplus_data': [(t, td, round(tc, 4), round(tj, 1)) for t, td, tc, tj in tplus_days],
        'is_red': alert_level == 'RED',
        'skip_reason': skip,
        'is_penny': is_penny,
    })

print("=== SUMMARY ===")
reds = [r for r in results if r['is_red']]
watches = [r for r in results if not r['is_red']]
print(f"RED: {len(reds)} | WATCHLIST/EXCLUDED: {len(watches)}")
for r in results:
    level = "🔴 RED" if r['is_red'] else "🟡 WATCH"
    print(f"  {r['code']} {r['name']}: {level} | {r.get('skip_reason','?')}")

outpath = Path(__file__).resolve().parent / "_tplus_verify_v2.json"
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print(f"\nSaved to _tplus_verify_v2.json")
