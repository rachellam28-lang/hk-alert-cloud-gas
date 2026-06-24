"""
Post-hoc 8120 Verification Script
===================================
Checks T-1 to T-5 trading day announcements for the T+1~T+5 close-to-close
price jump + volume ratio. Catches what the same-day-only cron scanner misses.

Usage:
  cd /c/Users/Administrator/Desktop/automatic/ccass-debug
  .venv/Scripts/python.exe -u _posthoc_8120.py

Input:  data/announcements.json (620+ entries, full history)
Output: data/_posthoc_8120_result.json (graded results, dedup-ready)

Features:
- Converts HKEX 5-digit codes to yfinance 4-digit tickers
- Checks T+1 through T+5 close-to-close jumps + volume ratios
- Tracks BEST alert level (RED > WATCH > -) per stock, not highest jump %
- Deduplicates same-stock same-date duplicate entries (e.g., 配股 + 配股/復牌)
- Grades per strict 8120 rules: ALL 3 conditions for RED

Grading rules:
  🔴 RED:  type=配售/placement + jump >= 8% + vol >= 1.5x  (ALL 3)
  🟡 WATCH: 1-2 of 3 conditions, ALL 供股/rights, ALL 增持/increase
  -: no trigger

Requirements:
  pip install yfinance
  yfinance shims must be renamed (yfinance.py -> _yfinance_shim.py)
"""
import json, sys, os
import yfinance as yf
from datetime import datetime, timedelta


def yf_code(hkex_5digit):
    """Convert HKEX 5-digit code to yfinance ticker (4-digit, leading zero)."""
    return f'{int(hkex_5digit):04d}.HK'


def load_candidates(announcements_path, target_dates):
    """Extract placement/rights/increase candidates from announcements.json."""
    with open(announcements_path, 'r') as f:
        data = json.load(f)

    candidates = []
    for e in data:
        d = e.get('date', '')
        if d not in target_dates:
            continue
        title = (e.get('title', '') or '')
        tl = (e.get('typeLabel', '') or '')
        types = e.get('types', [])

        # Skip completions, lapses
        if '完成' in title or 'COMPLETION' in title.upper() or 'LAPSE' in title.upper():
            continue

        is_placement = any(kw in tl for kw in ['配售', '配股']) and '供股' not in tl
        is_rights = '供股' in tl or '供股' in types
        is_increase = '增持' in tl or '增持' in types

        if is_placement or is_rights or is_increase:
            candidates.append({
                'code': e['code'],
                'name': e['name'],
                'date': d,
                'typeLabel': tl,
                'types': types,
                'is_placement': is_placement and not is_rights,
                'is_rights': is_rights,
                'is_increase': is_increase,
            })
    return candidates


def check_stock(candidate):
    """Check one stock for 8120 T+1~T+5 triggers. Returns result dict or None on error."""
    code = candidate['code']
    ann_date = candidate['date']
    sym = yf_code(code)

    t = yf.Ticker(sym)
    hist = t.history(period='20d')
    if len(hist) < 3:
        return None

    closes = hist['Close']
    volumes = hist['Volume']

    # Find announcement day close
    ann_idx = None
    for i in range(len(hist)):
        if hist.index[i].strftime('%Y-%m-%d') == ann_date:
            ann_idx = i
            break

    if ann_idx is None:
        return None

    ann_close = closes.iloc[ann_idx]

    best_alert = None
    best_info = None
    all_days = []

    for offset in range(1, 6):
        idx = ann_idx + offset
        if idx >= len(closes):
            break
        t_close = closes.iloc[idx]
        jump = (t_close / ann_close - 1) * 100 if ann_close > 0 else 0
        t_vol = volumes.iloc[idx]
        avg_start = max(0, idx - 5)
        avg_vol = volumes.iloc[avg_start:idx].mean() if idx > avg_start else 0
        vol_ratio = t_vol / avg_vol if avg_vol > 0 else 0
        t_date = hist.index[idx].strftime('%Y-%m-%d')

        if candidate['is_placement']:
            if jump >= 8 and vol_ratio >= 1.5:
                alert = 'RED'
            elif jump >= 8 or vol_ratio >= 1.5:
                alert = 'WATCH'
            else:
                alert = '-'
        else:
            alert = 'WATCH'  # Rights/increase always WATCHLIST

        day_info = {
            'offset': offset, 'date': t_date, 'jump': round(jump, 2),
            'vol_ratio': round(vol_ratio, 2), 'close': round(float(t_close), 4),
            'alert': alert
        }
        all_days.append(day_info)

        # Track BEST alert level (RED > WATCH > -), NOT highest jump %
        if alert == 'RED' and best_alert != 'RED':
            best_alert = 'RED'
            best_info = (offset, t_date, round(jump, 2), round(vol_ratio, 2),
                         round(float(t_close), 4), round(float(ann_close), 4))
        elif alert == 'WATCH' and best_alert is None:
            best_alert = 'WATCH'
            best_info = (offset, t_date, round(jump, 2), round(vol_ratio, 2),
                         round(float(t_close), 4), round(float(ann_close), 4))

    return {
        'code': code, 'name': candidate['name'], 'ann_date': ann_date,
        'typeLabel': candidate['typeLabel'],
        'is_placement': candidate['is_placement'],
        'is_rights': candidate['is_rights'],
        'is_increase': candidate['is_increase'],
        'best_alert': best_alert,
        'best_info': best_info,
        'all_days': all_days,
        'ann_close': round(float(ann_close), 4),
    }


def deduplicate_reds(results):
    """Deduplicate RED alerts by (code, ann_date). Same stock different dates = separate alerts."""
    seen = set()
    unique = []
    for r in results:
        if r['best_alert'] == 'RED':
            key = (r['code'], r['ann_date'])
            if key not in seen:
                seen.add(key)
                unique.append(r)
    return unique


def print_summary(results, errors):
    """Print human-readable summary."""
    reds = [r for r in results if r['best_alert'] == 'RED']
    watches = [r for r in results if r['best_alert'] == 'WATCH']
    nos = [r for r in results if r['best_alert'] is None]

    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")
    print(f"RED ALERTS: {len(reds)}")
    for r in reds:
        bi = r['best_info']
        print(f"  {r['code']} {r['name']} | ann={r['ann_date']} | {r['typeLabel']} | "
              f"T+{bi[0]} jump={bi[2]:+.1f}% vol={bi[3]:.1f}x")

    print(f"\nWATCHLIST: {len(watches)}")
    for r in watches:
        print(f"  {r['code']} {r['name']} | ann={r['ann_date']} | {r['typeLabel']}")

    print(f"\nNo trigger: {len(nos)}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")


def compute_target_dates(today=None):
    """Auto-compute past 7 calendar days (covers 5 trading days with weekends).
    If 'today' is provided as 'YYYY-MM-DD', use it; otherwise use current date."""
    if today is None:
        today = datetime.now()
    else:
        today = datetime.strptime(today, '%Y-%m-%d')
    return [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 8)]


def main():
    proj_dir = os.getcwd()

    # Auto-compute past 5 trading days (7 calendar days with weekend padding)
    target_dates = compute_target_dates()
    print(f"Target dates (past 7 calendar days): {target_dates}", flush=True)

    ann_path = os.path.join(proj_dir, 'data', 'announcements.json')
    candidates = load_candidates(ann_path, target_dates)
    print(f"Candidates to check: {len(candidates)}")

    results = []
    errors = []

    for c in candidates:
        sym = yf_code(c['code'])
        try:
            result = check_stock(c)
            if result is None:
                print(f"  {sym}: no data (ann date not in history or insufficient rows)")
                continue
            results.append(result)

            # Print per-stock results
            for day in result['all_days']:
                marker = '🔴' if day['alert'] == 'RED' else '🟡' if day['alert'] == 'WATCH' else '  '
                print(f"  {marker} {day['alert']:5s} | T+{day['offset']} ({day['date']}) | "
                      f"jump={day['jump']:+.1f}% | vol={day['vol_ratio']:.1f}x | close={day['close']}")

            if result['best_alert'] == 'RED':
                bi = result['best_info']
                print(f"  >>> FINAL: RED ALERT — T+{bi[0]} jump={bi[2]:+.1f}% vol={bi[3]:.1f}x <<<")
            elif result['best_alert'] == 'WATCH':
                print(f"  >>> FINAL: WATCHLIST <<<")
            else:
                print(f"  >>> FINAL: no trigger <<<")

        except Exception as e:
            errors.append(f"{sym}: {e}")
            print(f"  {sym}: ERROR {e}")

    print_summary(results, errors)

    # Save results
    out_path = os.path.join(proj_dir, 'data', '_posthoc_8120_result.json')
    reds = deduplicate_reds(results)
    watches = [r for r in results if r['best_alert'] == 'WATCH']
    nos = [r for r in results if r['best_alert'] is None]

    with open(out_path, 'w') as f:
        json.dump({
            'scan_date': datetime.now().strftime('%Y-%m-%d'),
            'results': results,
            'errors': errors,
            'reds': len(reds),
            'watches': len(watches),
            'no_trigger': len(nos)
        }, f, indent=2)

    print(f"\nResults saved to {out_path}")


if __name__ == '__main__':
    main()
