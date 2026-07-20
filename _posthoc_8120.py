"""
Post-hoc 8120 Verification — cron-safe, self-contained.
Checks T-1~T-5 announcement candidates for T+1~T+5 close-to-close jumps + volume ratios.
"""
import json, sys, os
import yfinance as yf
from datetime import datetime, timedelta


def yf_code(hkex_5digit):
    return f'{int(hkex_5digit):04d}.HK'


def main():
    proj_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(proj_dir)

    # Compute target dates (past 10 calendar days for safety)
    today = datetime.now()
    target_dates = set()
    for i in range(0, 11):
        target_dates.add((today - timedelta(days=i)).strftime('%Y-%m-%d'))

    # Load announcements
    ann_path = os.path.join(proj_dir, 'data', 'announcements.json')
    with open(ann_path, 'r') as f:
        all_data = json.load(f)

    # Filter candidates: placement/rights/increase from target dates
    candidates = []
    for e in all_data:
        d = e.get('date', '')
        if d not in target_dates:
            continue
        title = (e.get('title', '') or '').upper()
        tl = (e.get('typeLabel', '') or '')
        types = e.get('types', [])

        # Skip completions, lapses
        if '完成' in e.get('title', '') or 'COMPLETION' in title or 'LAPSE' in title:
            continue

        is_placement = ('配售' in tl or '配股' in tl) and '供股' not in tl and '完成' not in tl
        is_rights = '供股' in tl or '供股' in types
        is_increase = '增持' in tl or '增持' in types

        if is_placement or is_rights or is_increase:
            candidates.append({
                'code': e['code'],
                'name': e['name'],
                'date': d,
                'typeLabel': tl,
                'types': types,
                'is_placement': is_placement,
                'is_rights': is_rights,
                'is_increase': is_increase,
            })

    # Remove duplicates by (code, date) — keep first
    seen = set()
    unique = []
    for c in candidates:
        key = (c['code'], c['date'])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    candidates = unique

    print(f"Target dates: {sorted(target_dates)}", flush=True)
    print(f"Candidates to check: {len(candidates)}", flush=True)
    for c in candidates:
        print(f"  {c['code']} {c['name']} | {c['date']} | {c['typeLabel']}", flush=True)
    print(f"\n{'='*70}", flush=True)

    results = []
    errors = []

    for c in candidates:
        code = c['code']
        ann_date = c['date']
        sym = yf_code(code)

        try:
            t = yf.Ticker(sym)
            hist = t.history(period='20d')
            if len(hist) < 3:
                print(f"  {sym}: insufficient data ({len(hist)} rows)", flush=True)
                continue

            closes = hist['Close']
            volumes = hist['Volume']

            # Find announcement day index
            ann_idx = None
            for i in range(len(hist)):
                if hist.index[i].strftime('%Y-%m-%d') == ann_date:
                    ann_idx = i
                    break

            if ann_idx is None:
                print(f"  {sym}: ann date {ann_date} not in history range", flush=True)
                continue

            ann_close = float(closes.iloc[ann_idx])

            best_alert = None
            best_info = None
            all_days = []

            for offset in range(1, 6):
                idx = ann_idx + offset
                if idx >= len(closes):
                    break

                t_close = float(closes.iloc[idx])
                jump = (t_close / ann_close - 1) * 100 if ann_close > 0 else 0
                t_vol = float(volumes.iloc[idx])

                # 5-day avg volume up to (but NOT including) the jump day
                avg_start = max(0, idx - 6)  # idx-6 to idx-1
                avg_end = idx
                avg_vol_slice = volumes.iloc[avg_start:avg_end]
                avg_vol = float(avg_vol_slice.mean()) if len(avg_vol_slice) > 0 and avg_vol_slice.mean() > 0 else 0
                vol_ratio = t_vol / avg_vol if avg_vol > 0 else 0
                t_date = hist.index[idx].strftime('%Y-%m-%d')

                if c['is_placement']:
                    if jump >= 8 and vol_ratio >= 1.5:
                        alert = 'RED'
                    elif jump >= 8 or vol_ratio >= 1.5:
                        alert = 'WATCH'
                    else:
                        alert = '-'
                else:
                    alert = 'WATCH'

                day_info = {
                    'offset': offset, 'date': t_date, 'jump': round(jump, 2),
                    'vol_ratio': round(vol_ratio, 2), 'close': round(t_close, 4),
                    'alert': alert
                }
                all_days.append(day_info)

                # Track BEST alert (RED > WATCH > -)
                if alert == 'RED' and best_alert != 'RED':
                    best_alert = 'RED'
                    best_info = (offset, t_date, round(jump, 2), round(vol_ratio, 2),
                                 round(t_close, 4), round(ann_close, 4))
                elif alert == 'WATCH' and best_alert is None:
                    best_alert = 'WATCH'
                    best_info = (offset, t_date, round(jump, 2), round(vol_ratio, 2),
                                 round(t_close, 4), round(ann_close, 4))

            result = {
                'code': code, 'name': c['name'], 'ann_date': ann_date,
                'typeLabel': c['typeLabel'],
                'is_placement': c['is_placement'],
                'is_rights': c['is_rights'],
                'is_increase': c['is_increase'],
                'best_alert': best_alert,
                'best_info': best_info,
                'all_days': all_days,
                'ann_close': round(ann_close, 4),
            }
            results.append(result)

            # Per-stock output
            for day in all_days:
                marker = '🔴' if day['alert'] == 'RED' else '🟡' if day['alert'] == 'WATCH' else '  '
                print(f"  {marker} {day['alert']:5s} | T+{day['offset']} ({day['date']}) | "
                      f"jump={day['jump']:+.1f}% | vol={day['vol_ratio']:.1f}x | close={day['close']}", flush=True)

            if best_alert == 'RED':
                bi = best_info
                print(f"  >>> FINAL: 🔴 RED ALERT — T+{bi[0]} jump={bi[2]:+.1f}% vol={bi[3]:.1f}x <<<", flush=True)
            elif best_alert == 'WATCH':
                print(f"  >>> FINAL: 🟡 WATCHLIST <<<", flush=True)
            else:
                print(f"  >>> FINAL: no trigger <<<", flush=True)

        except Exception as e:
            errors.append(f"{sym}: {e}")
            print(f"  {sym}: ERROR {e}", flush=True)

    # Summary
    reds = [r for r in results if r['best_alert'] == 'RED']
    watches = [r for r in results if r['best_alert'] == 'WATCH']
    nos = [r for r in results if r['best_alert'] is None]

    print(f"\n{'='*70}", flush=True)
    print(f"FINAL SUMMARY", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"🔴 RED ALERTS: {len(reds)}", flush=True)
    for r in reds:
        bi = r['best_info']
        print(f"  {r['code']} {r['name']} | ann={r['ann_date']} | {r['typeLabel']} | "
              f"T+{bi[0]} jump={bi[2]:+.1f}% vol={bi[3]:.1f}x", flush=True)
    print(f"🟡 WATCHLIST: {len(watches)}", flush=True)
    for r in watches:
        print(f"  {r['code']} {r['name']} | ann={r['ann_date']} | {r['typeLabel']}", flush=True)
    print(f"  No trigger: {len(nos)}", flush=True)
    if errors:
        print(f"  Errors: {len(errors)}", flush=True)
        for e in errors[:5]:
            print(f"    {e}", flush=True)

    # Save
    out_path = os.path.join(proj_dir, 'data', '_posthoc_8120_result.json')
    with open(out_path, 'w') as f:
        json.dump({
            'scan_date': today.strftime('%Y-%m-%d'),
            'results': results,
            'errors': errors,
            'reds': len(reds),
            'watches': len(watches),
            'no_trigger': len(nos),
        }, f, indent=2)
    print(f"\nSaved to {out_path}", flush=True)


if __name__ == '__main__':
    main()
