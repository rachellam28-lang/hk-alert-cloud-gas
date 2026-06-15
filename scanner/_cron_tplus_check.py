"""Cron helper: T+1~T+5 placement tracking for HK Corp scanner"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from hk_cloud_scanner import hk_code_to_yahoo

watchlist_placements = [
    ("00700", "騰訊", "2026-06-05", "配售"),
    ("01912", "CONTEL", "2026-06-08", "配股"),
    ("09936", "XIMEI RESOURCES", "2026-06-08", "配股"),
    ("01815", "EVEREST GOLD", "2026-06-08", "配股"),
    ("00994", "CT VISION", "2026-06-08", "配股"),
    ("02186", "LUYE PHARMA", "2026-06-08", "配股"),
    ("00953", "SHAW BROTHERS", "2026-06-08", "配股"),
    ("00254", "NUR HOLDINGS", "2026-06-08", "配股"),
]

print("=== T+1~T+5 Placement Tracking ===")
print()

results = []
for code, name, ann_date, ctype in watchlist_placements:
    yahoo_code = hk_code_to_yahoo(code)
    ann_dt = datetime.strptime(ann_date, "%Y-%m-%d")
    t_plus = (datetime.now() - ann_dt).days
    if t_plus == 0:
        continue
    
    try:
        import yfinance as yf
        tk = yf.Ticker(yahoo_code)
        
        # Get 2 weeks of daily data
        df = tk.history(period="2wk", timeout=15)
        if df.empty or len(df) < 2:
            print(f"{code} {name}: No price data")
            continue
        
        close_now = df['Close'].iloc[-1]
        close_ann = df['Close'].iloc[0]
        pct_change = (float(close_now) - float(close_ann)) / float(close_ann) * 100
        
        # Get 1mo for volume average
        df_mo = tk.history(period="1mo", timeout=15)
        if not df_mo.empty and len(df_mo) >= 5:
            vol_latest = float(df_mo['Volume'].iloc[-1])
            vols = df_mo['Volume'].tail(20)
            vol_avg = float(vols.mean())
            vol_ratio = vol_latest / vol_avg if vol_avg > 0 else 0
        else:
            vol_ratio = 0
        
        is_red = (
            ctype in ('配股', '配售') and
            vol_ratio >= 1.5 and
            abs(pct_change) >= 8.0
        )
        status = "RED" if is_red else ("partial" if abs(pct_change) >= 8.0 or vol_ratio >= 1.5 else "none")
        
        line = f"{code} {name:<25}| T+{t_plus} | {ctype} | 變幅:{pct_change:+.1f}% | 量比:{vol_ratio:.1f}x | {status}"
        print(line)
        results.append({
            'code': code, 'name': name, 't_plus': t_plus,
            'ctype': ctype, 'pct_change': round(pct_change, 1),
            'vol_ratio': round(vol_ratio, 1), 'is_red': is_red
        })
        
    except Exception as e:
        print(f"{code} {name}: Error - {type(e).__name__}: {e}")

print()
red_count = sum(1 for r in results if r['is_red'])
print(f"Total tracked: {len(results)}, RED alerts: {red_count}")

print("\nJSON_START")
print(json.dumps(results, ensure_ascii=False, default=str))
print("JSON_END")
