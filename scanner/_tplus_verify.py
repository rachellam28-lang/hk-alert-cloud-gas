"""Precise T+1~T+5 close-to-close verification for HK Corp Scanner"""
import json
import yfinance as yf
from datetime import datetime, timedelta

candidates = [
    ("00700", "騰訊", "2026-06-05", "配售"),
    ("01912", "CONTEL", "2026-06-08", "配股"),
    ("00953", "SHAW BROTHERS", "2026-06-08", "配股"),
    ("09936", "XIMEI RESOURCES", "2026-06-08", "配股"),
    ("01815", "EVEREST GOLD", "2026-06-08", "配股"),
    ("00994", "CT VISION", "2026-06-08", "配股"),
    ("00254", "NUR HOLDINGS", "2026-06-08", "配股"),
]

def hk_code_to_yahoo(code):
    code = code.zfill(5)
    num = int(code)
    return f"{num:04d}.HK" if num <= 999 else f"{num:05d}.HK"

print("=== Precise T+1~T+5 Close-to-Close Verification ===\n")

results = []
for code, name, ann_date_str, ctype in candidates:
    yahoo_code = hk_code_to_yahoo(code)
    ann_date = datetime.strptime(ann_date_str, "%Y-%m-%d")
    
    try:
        tk = yf.Ticker(yahoo_code)
        start = (ann_date - timedelta(days=30)).strftime('%Y-%m-%d')
        end = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
        
        df = tk.history(start=start, end=end, timeout=15)
        if df.empty or len(df) < 2:
            print(f"{code} {name}: No price data")
            continue
        
        df_dates = [d.strftime('%Y-%m-%d') for d in df.index]
        
        # Find ann day close
        ann_close = None
        ann_vol_ratio = 0
        for i, d in enumerate(df_dates):
            if d == ann_date_str:
                ann_close = float(df['Close'].iloc[i])
                ann_vol = float(df['Volume'].iloc[i])
                vol_window = df['Volume'].iloc[max(0,i-20):i]
                if len(vol_window) >= 5:
                    vol_avg = float(vol_window.mean())
                    ann_vol_ratio = ann_vol / vol_avg if vol_avg > 0 else 0
                break
        
        if ann_close is None:
            # Find next trading day
            for i, d in enumerate(df_dates):
                if d >= ann_date_str:
                    ann_close = float(df['Close'].iloc[i])
                    ann_vol = float(df['Volume'].iloc[i])
                    vol_window = df['Volume'].iloc[max(0,i-20):i]
                    if len(vol_window) >= 5:
                        vol_avg = float(vol_window.mean())
                        ann_vol_ratio = ann_vol / vol_avg if vol_avg > 0 else 0
                    ann_date_str = d
                    break
        
        if ann_close is None:
            print(f"{code} {name}: Cannot determine ann close")
            continue
        
        ann_idx = df_dates.index(ann_date_str)
        
        tplus_days = []
        for offset in range(1, 6):
            idx = ann_idx + offset
            if idx < len(df):
                day_date = df_dates[idx]
                day_close = float(df['Close'].iloc[idx])
                day_jump = (day_close - ann_close) / ann_close * 100
                tplus_days.append((offset, day_date, day_close, day_jump))
        
        max_jump = max((d[3] for d in tplus_days), default=0) if tplus_days else 0
        max_jump_t = next((d[0] for d in tplus_days if d[3] == max_jump), None)
        is_penny = ann_close < 0.50
        
        print(f"{code} {name} | {ctype} | Ann: {ann_date_str} close={ann_close:.3f} vol_ratio={ann_vol_ratio:.1f}x")
        for t, td, tc, tj in tplus_days:
            marker = " ← MAX" if tj == max_jump and len(tplus_days) > 1 else ""
            print(f"  T+{t} ({td}): close={tc:.3f}, jump={tj:+.1f}%{marker}")
        
        is_placement = ctype in ('配售', '配股')
        vol_ok = ann_vol_ratio >= 1.5
        jump_ok = max_jump >= 8.0
        
        if not is_placement:
            skip = "type=非配售"
        elif not vol_ok:
            skip = f"vol={ann_vol_ratio:.1f}x<1.5x"
        elif not jump_ok:
            skip = f"jump={max_jump:.1f}%<8%"
        else:
            skip = ""
        
        alert_level = "RED" if (is_placement and vol_ok and jump_ok) else "WATCHLIST"
        
        print(f"  → {alert_level} | skip: {skip} | penny={'⚠️' if is_penny else 'no'}")
        print()
        
        results.append({
            'code': code, 'name': name, 'ctype': ctype,
            'ann_date': ann_date_str, 'ann_close': round(ann_close, 4),
            'ann_vol_ratio': round(ann_vol_ratio, 1),
            'max_jump': round(max_jump, 1), 'max_jump_t': max_jump_t,
            'tplus_data': [(t, td, round(tc, 4), round(tj, 1)) for t, td, tc, tj in tplus_days],
            'is_red': alert_level == 'RED',
            'skip_reason': skip,
            'is_penny': is_penny,
        })
    except Exception as e:
        print(f"{code} {name}: Error - {type(e).__name__}: {e}\n")

print("=== SUMMARY ===")
reds = [r for r in results if r['is_red']]
watches = [r for r in results if not r['is_red']]
print(f"RED: {len(reds)} | WATCHLIST: {len(watches)}")
for r in results:
    print(f"  {r['code']} {r['name']}: {'🔴 RED' if r['is_red'] else '🟡 WATCH'} | {r['skip_reason']}")

with open('/c/Users/Administrator/Desktop/automatic/ccass-debug/scanner/_tplus_verify.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nSaved to _tplus_verify.json")
