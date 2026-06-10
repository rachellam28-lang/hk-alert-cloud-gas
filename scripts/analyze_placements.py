"""
analyze_placements.py — 8120 Pattern + Conditional Test
========================================================
Tests:
  1. 8120 pattern: placement → T+1~T+5 jump (>5%/8%/15%) → 60d max gain
  2. Discount split: narrow (<10%) vs wide (>10%) × jump
  3. Survivorship sensitivity: delisted → worst-case -100% return
  4. Conditional test: corp background × technical (POC/FVG) signals
"""
import json
import os
import statistics
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_HISTORY = os.path.join(BASE, "data", "price_history.json")
PLACEMENTS = os.path.join(BASE, "data", "placements_enriched.json")
REPLAY_RESULTS = os.path.join(BASE, "data", "replay_results.json")

def load_json(path):
    with open(path) as f:
        return json.load(f)

def trading_dates_after(pxs, d0, n):
    """Return up to n trading dates strictly after d0."""
    ds = sorted(k for k in pxs if k > d0)
    return ds[:n]

def analyze_8120(placements, hist):
    """8120 pattern: placement → jump detection → forward returns."""
    
    # Survivorship tracking
    total_placements = len(placements)
    with_price_data = 0
    without_price_data = 0
    no_t0_date = 0
    
    thresholds = [0.05, 0.08, 0.15]
    results = {t: {"jumped": [], "no_jump": []} for t in thresholds}
    
    for p in placements:
        code = str(p.get("code", "")).strip().lstrip("0").zfill(5)
        pxs = hist.get(code)
        
        if not pxs:
            without_price_data += 1
            continue
        
        d0 = p.get("date_parsed") or p.get("date", "")
        d0 = str(d0)[:10]
        
        if d0 not in pxs:
            no_t0_date += 1
            continue
        
        with_price_data += 1
        discount = p.get("discount_pct")
        base = pxs[d0]
        if base <= 0:
            continue
        
        next5 = trading_dates_after(pxs, d0, 5)
        if not next5:
            continue
        
        # Check jump for each threshold
        for thresh in thresholds:
            jump_day = next((d for d in next5 if pxs[d] / base - 1 >= thresh), None)
            
            entry_day = jump_day or next5[0]
            entry = pxs[entry_day]
            
            after = trading_dates_after(pxs, entry_day, 60)
            if len(after) < 5:
                continue
            
            fwd_20d = pxs[after[min(19, len(after)-1)]] / entry - 1 if len(after) >= 20 else None
            max_gain_60d = max(pxs[d] for d in after) / entry - 1
            max_dd_20d = min(pxs[d] for d in after[:min(20, len(after))]) / entry - 1
            
            rec = {
                "code": code,
                "name": p.get("name", ""),
                "date": d0,
                "discount_pct": discount,
                "jumped": bool(jump_day),
                "jump_day": jump_day,
                "jump_pct": round(pxs[jump_day] / base - 1, 4) if jump_day else None,
                "entry_price": round(entry, 4),
                "fwd_20d": round(fwd_20d, 4) if fwd_20d is not None else None,
                "max_gain_60d": round(max_gain_60d, 4),
                "max_dd_20d": round(max_dd_20d, 4),
            }
            
            if jump_day:
                results[thresh]["jumped"].append(rec)
            else:
                results[thresh]["no_jump"].append(rec)
    
    return results, {
        "total": total_placements,
        "with_price_data": with_price_data,
        "without_price_data": without_price_data,
        "no_t0_date": no_t0_date,
    }

def print_distribution(label, records, field="max_gain_60d"):
    """Print quartile distribution for a group."""
    vals = [r[field] for r in records if r.get(field) is not None]
    if not vals:
        print(f"  {label}: n=0")
        return
    
    vals.sort()
    n = len(vals)
    q0, q1, q2, q3, q4 = (
        vals[0], vals[n//4], vals[n//2], vals[3*n//4], vals[-1]
    )
    gt100 = sum(1 for v in vals if v > 1.0)
    gt50 = sum(1 for v in vals if v > 0.50)
    win20 = sum(1 for r in records if r.get("fwd_20d") is not None and r["fwd_20d"] > 0)
    n20 = sum(1 for r in records if r.get("fwd_20d") is not None)
    
    print(f"  {label}: n={n}")
    print(f"    Quartiles: {q0*100:+.1f}% / {q1*100:+.1f}% / {q2*100:+.1f}% / {q3*100:+.1f}% / {q4*100:+.1f}%")
    print(f"    Win 20d: {win20}/{n20} ({win20/n20*100:.0f}%)" if n20 else "    Win 20d: N/A")
    print(f"    >50% gain: {gt50} ({gt50/n*100:.0f}%)")
    print(f"    >100% gain: {gt100} ({gt100/n*100:.1f}%)")
    print(f"    Median maxDD 20d: {statistics.median([r['max_dd_20d'] for r in records if r.get('max_dd_20d') is not None])*100:+.1f}%")
    return vals

def analyze_discount_split(records, threshold):
    """Split jumped records by discount narrow (<10%) vs wide (>=10%)."""
    narrow = [r for r in records if r.get("discount_pct") is not None and abs(r["discount_pct"]) < 10]
    wide = [r for r in records if r.get("discount_pct") is not None and abs(r["discount_pct"]) >= 10]
    no_discount = [r for r in records if r.get("discount_pct") is None]
    
    print(f"\n  --- Discount split (jump >{threshold*100:.0f}%) ---")
    print_distribution(f"  Narrow discount (<10%): n={len(narrow)}", narrow)
    print_distribution(f"  Wide discount (>=10%): n={len(wide)}", wide)
    if no_discount:
        print(f"  No discount data: {len(no_discount)} skipped")
    
    return narrow, wide

def survivorship_sensitivity(placements, hist, results_8pct):
    """
    Worst-case sensitivity: assume all stocks without price data went to 0.
    Returns adjusted metrics.
    """
    with_data = results_8pct["jumped"] + results_8pct["no_jump"]
    without_data = sum(1 for p in placements if 
                       str(p.get("code","")).strip().lstrip("0").zfill(5) not in hist)
    
    # For jumped group: add worst-case -100% returns for missing stocks
    jumped_codes = set(r["code"] for r in results_8pct["jumped"])
    
    print(f"\n--- Survivorship Sensitivity ---")
    print(f"  Placements with price data: {len(with_data)}")
    print(f"  Placements without price data (assumed delisted→0): {without_data}")
    
    # Original jumped group
    orig_gains = [r["max_gain_60d"] for r in results_8pct["jumped"]]
    # Worst case: add -1.0 for each missing stock
    worst_gains = orig_gains + [-1.0] * without_data
    
    if orig_gains:
        print(f"\n  Jumped group (original, n={len(orig_gains)}):")
        orig_sorted = sorted(orig_gains)
        print(f"    Median max_gain_60d: {orig_sorted[len(orig_sorted)//2]*100:+.1f}%")
        print(f"    >100% ratio: {sum(1 for g in orig_gains if g>1)/len(orig_gains)*100:.1f}%")
    
    if worst_gains:
        print(f"\n  Jumped group (worst-case, n={len(worst_gains)}):")
        worst_sorted = sorted(worst_gains)
        print(f"    Median max_gain_60d: {worst_sorted[len(worst_sorted)//2]*100:+.1f}%")
        print(f"    >100% ratio: {sum(1 for g in worst_gains if g>1)/len(worst_gains)*100:.1f}%")

def run_conditional_test(replay_results, holdings):
    """
    Conditional test: corp background stocks × POC/FVG vs pure technical.
    See if a corp announcement within 30 days before/after improves signal quality.
    """
    signals = replay_results.get("signals", [])
    if not signals:
        print("\n--- Conditional Test: SKIPPED (no replay data) ---")
        return
    
    # Build corp date map from holdings corpTypes → we need announcement dates
    # For now, use the corp_announcements.json
    corp_path = os.path.join(BASE, "data", "corp_announcements.json")
    corp_dates = defaultdict(list)
    if os.path.exists(corp_path):
        ca = load_json(corp_path)
        if isinstance(ca, list):
            for ann in ca:
                code = str(ann.get("code", "")).zfill(5)
                d = (ann.get("date") or "")[:10]
                if code and d:
                    corp_dates[code].append(d)
    
    # Also from placements
    if os.path.exists(PLACEMENTS):
        pl = load_json(PLACEMENTS)
        for p in pl:
            code = str(p.get("code", "")).strip().lstrip("0").zfill(5)
            d0 = p.get("date_parsed") or str(p.get("date", ""))[:10]
            if code and d0:
                corp_dates[code].append(d0)
    
    # For each signal, check if there's a corp event within ±30 days
    pure = []
    corp_backed = []
    
    for s in signals:
        code = s.get("code", "")
        sig_date = s.get("date", "")
        corp_events = corp_dates.get(code, [])
        
        has_corp = any(
            abs((max(d, sig_date) if d > sig_date else sig_date).count('-')) < 3  # wrong
            for d in corp_events
        )
        # Proper date check:
        from datetime import datetime, timedelta
        try:
            sd = datetime.strptime(sig_date[:10], "%Y-%m-%d")
            nearby = False
            for d in corp_events:
                try:
                    cd = datetime.strptime(d[:10], "%Y-%m-%d")
                    if abs((sd - cd).days) <= 30:
                        nearby = True
                        break
                except:
                    pass
            if nearby:
                corp_backed.append(s)
            else:
                pure.append(s)
        except:
            pure.append(s)
    
    print(f"\n--- Conditional Test (corp background × technical) ---")
    print(f"  Pure technical: {len(pure)} signals")
    print(f"  Corp-backed: {len(corp_backed)} signals")
    
    for label, group in [("Pure technical", pure), ("Corp-backed (30d)", corp_backed)]:
        if not group:
            continue
        f20 = [s.get("fwd_20d") for s in group if s.get("fwd_20d") is not None]
        gains = [s.get("max_gain_20d") for s in group if s.get("max_gain_20d") is not None]
        wins = sum(1 for r in f20 if r > 0)
        
        if f20:
            f20.sort()
            print(f"  {label}:")
            print(f"    n={len(group)}, median fwd_20d={f20[len(f20)//2]*100:+.2f}%")
            print(f"    win_rate={wins}/{len(f20)} ({wins/len(f20)*100:.1f}%)")
            if gains:
                gains.sort()
                print(f"    median max_gain_20d={gains[len(gains)//2]*100:+.2f}%")


if __name__ == "__main__":
    print("Loading data...")
    hist = load_json(PRICE_HISTORY)
    placements = load_json(PLACEMENTS)
    
    print(f"Price history: {len(hist)} stocks")
    print(f"Placements: {len(placements)} records")
    
    print("\n=== 8120 PATTERN TEST ===")
    results, stats = analyze_8120(placements, hist)
    
    print(f"\nData coverage:")
    print(f"  Total placements: {stats['total']}")
    print(f"  With price data: {stats['with_price_data']}")
    print(f"  Without price data (delisted/not found): {stats['without_price_data']}")
    print(f"  No T0 date match: {stats['no_t0_date']}")
    
    # For each threshold, show results
    for thresh in [0.05, 0.08, 0.15]:
        j = results[thresh]["jumped"]
        nj = results[thresh]["no_jump"]
        print(f"\n{'='*60}")
        print(f"Threshold: >{thresh*100:.0f}% jump in T+1~T+5")
        print(f"  Jumped: {len(j)}, No jump: {len(nj)}")
        
        print(f"\n  --- JUMPED GROUP (n={len(j)}) ---")
        print_distribution("  Jumped", j)
        
        print(f"\n  --- NO JUMP GROUP (n={len(nj)}) ---")
        print_distribution("  No jump", nj)
        
        # Discount split for 8% threshold
        if thresh == 0.08:
            analyze_discount_split(j, thresh)
    
    # Survivorship sensitivity
    survivorship_sensitivity(placements, hist, results[0.08])
    
    # Conditional test
    replay = load_json(REPLAY_RESULTS) if os.path.exists(REPLAY_RESULTS) else {}
    run_conditional_test(replay, {})
    
    print("\n=== DONE ===")
