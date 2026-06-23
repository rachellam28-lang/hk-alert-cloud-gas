"""Post-hoc 8120 verification for June 22 cron run — checks T-1~T-5 (Jun 15-19)."""
import json, sys, os, time
from datetime import datetime

proj_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(proj_dir)

# Load .env
env_path = os.path.join(proj_dir, '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

import yfinance as yf

def yf_code(hkex_5digit):
    return f'{int(hkex_5digit):04d}.HK'

# Load announcements
with open('data/announcements.json', 'r') as f:
    all_anns = json.load(f)

target_dates = ['2026-06-15', '2026-06-16', '2026-06-17', '2026-06-18', '2026-06-19']

candidates = []
for e in all_anns:
    d = e.get('date', '')
    if d not in target_dates:
        continue
    title = (e.get('title', '') or '').upper()
    tl = (e.get('typeLabel', '') or '')
    types = e.get('types', [])
    if '完成' in e.get('title', '') or 'COMPLETION' in title or 'LAPSE' in title:
        continue
    if '復牌' in tl or 'resume' in e.get('type', ''):
        continue
    is_placement = any(kw in tl for kw in ['配售', '配股']) and '供股' not in tl
    is_rights = '供股' in tl or '供股' in types
    is_increase = '增持' in tl or '增持' in types
    if is_placement or is_rights or is_increase:
        candidates.append({
            'code': e['code'], 'name': e['name'], 'date': d,
            'typeLabel': tl, 'is_placement': is_placement and not is_rights,
            'is_rights': is_rights, 'is_increase': is_increase,
        })

print(f"Candidates: {len(candidates)}", flush=True)

results, errors = [], []

for c in candidates:
    code, ann_date, sym = c['code'], c['date'], yf_code(c['code'])
    try:
        t = yf.Ticker(sym)
        hist = t.history(period='30d')
        if len(hist) < 3:
            errors.append(f"{sym}: insuff data ({len(hist)})")
            continue
        closes, volumes = hist['Close'], hist['Volume']
        ann_idx = next((i for i in range(len(hist)) if hist.index[i].strftime('%Y-%m-%d') == ann_date), None)
        if ann_idx is None:
            errors.append(f"{sym}: date not found")
            continue

        ann_close = closes.iloc[ann_idx]
        best_alert, best_info, all_days = None, None, []

        for offset in range(1, 6):
            idx = ann_idx + offset
            if idx >= len(closes):
                break
            t_close = closes.iloc[idx]
            jump = (t_close / ann_close - 1) * 100 if ann_close > 0 else 0
            t_vol = volumes.iloc[idx]
            avg_start = max(0, idx - 5)
            avg_vol = volumes.iloc[avg_start:idx].mean() if idx > avg_start else 0
            vol_ratio = t_vol / avg_vol if avg_vol and avg_vol > 0 else 0
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

            day_info = {'offset': offset, 'date': t_date, 'jump': round(jump,2),
                       'vol_ratio': round(vol_ratio,2), 'close': round(float(t_close),4), 'alert': alert}
            all_days.append(day_info)

            if alert == 'RED' and best_alert != 'RED':
                best_alert = 'RED'
                best_info = [offset, t_date, round(jump,2), round(vol_ratio,2),
                            round(float(t_close),4), round(float(ann_close),4)]
            elif alert == 'WATCH' and best_alert is None:
                best_alert = 'WATCH'
                best_info = [offset, t_date, round(jump,2), round(vol_ratio,2),
                            round(float(t_close),4), round(float(ann_close),4)]

        results.append({
            'code': code, 'name': c['name'], 'ann_date': ann_date,
            'typeLabel': c['typeLabel'], 'is_placement': c['is_placement'],
            'is_rights': c['is_rights'], 'is_increase': c['is_increase'],
            'best_alert': best_alert, 'best_info': best_info, 'all_days': all_days,
            'ann_close': round(float(ann_close), 4),
        })

        for day in all_days:
            m = 'R' if day['alert'] == 'RED' else 'W' if day['alert'] == 'WATCH' else '-'
            print(f"  [{m}] {code} {c['name']} | T+{day['offset']} ({day['date']}) | jump={day['jump']:+.1f}% vol={day['vol_ratio']:.1f}x", flush=True)
        if best_alert:
            print(f"  >>> {best_alert}: {code} {c['name']} | T+{best_info[0]} jump={best_info[2]:+.1f}% vol={best_info[3]:.1f}x <<<", flush=True)

        time.sleep(1)
    except Exception as e:
        errors.append(f"{sym}: {e}")

reds = [r for r in results if r['best_alert'] == 'RED']
watches = [r for r in results if r['best_alert'] == 'WATCH']
nos = [r for r in results if r['best_alert'] is None]

print(f"\n=== SUMMARY ===", flush=True)
print(f"RED: {len(reds)}", flush=True)
for r in reds:
    bi = r['best_info']
    print(f"  {r['code']} {r['name']} | ann={r['ann_date']} | T+{bi[0]} jump={bi[2]:+.1f}% vol={bi[3]:.1f}x", flush=True)
print(f"WATCH: {len(watches)}", flush=True)
for r in watches:
    print(f"  {r['code']} {r['name']} | ann={r['ann_date']} | {r['typeLabel']}", flush=True)
print(f"NO TRIGGER: {len(nos)}", flush=True)
print(f"ERRORS: {len(errors)}", flush=True)

out = {'scan_date': '2026-06-22', 'results': results, 'errors': errors,
       'reds': len(reds), 'watches': len(watches), 'no_trigger': len(nos)}
with open('data/_posthoc_8120_result.json', 'w') as f:
    json.dump(out, f, indent=2)
print(f"Saved to data/_posthoc_8120_result.json", flush=True)
