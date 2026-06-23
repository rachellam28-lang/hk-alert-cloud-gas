import yfinance as yf
from datetime import datetime

def hk_code_to_yahoo(code):
    return f"{code[-4:]}.HK"

candidates = [
    ("09677", "WEIHAI BANK", "2026-06-14", 5),
    ("01920", "JUNWEA GROUP", "2026-06-15", 4),
    ("01208", "MMG", "2026-06-16", 3),
    ("01869", "KAFELAKU COFFEE", "2026-06-16", 3),
    ("00148", "KINGBOARD HLDG", "2026-06-17", 2),
    ("01888", "KB LAMINATES", "2026-06-17", 2),
    ("02889", "PATEO", "2026-06-17", 2),
    ("02465", "LOPAL TECH", "2026-06-17", 2),
    ("01736", "PARENTING NET", "2026-06-17", 2),
    ("02349", "CH CITY INFRA", "2026-06-17", 2),
    ("02623", "HK GOLD IND GP", "2026-06-18", 1),
    ("09982", "CENTRALCHINA MT", "2026-06-18", 1),
    ("02592", "CLOUDBREAK-B", "2026-06-18", 1),
    ("06190", "BANKOFJIUJIANG", "2026-06-18", 1),
    ("00107", "SICHUAN EXPRESS", "2026-06-18", 1),
    ("02490", "LC LOGISTICS", "2026-06-12", 7),
]

results = []
for code, name, ann_date, tplus in candidates:
    try:
        tk = yf.Ticker(hk_code_to_yahoo(code))
        df = tk.history(period='1mo', timeout=15)
        if df.empty or len(df) < 2:
            results.append((code, name, ann_date, tplus, "NO_DATA", 0, 0, 0, 0))
            continue
        
        ann_dt = datetime.strptime(ann_date, "%Y-%m-%d")
        ann_dt_aware = ann_dt.replace(tzinfo=df.index.tz)
        
        if ann_dt_aware in df.index:
            ann_close = float(df.loc[ann_dt_aware, 'Close'])
        else:
            before = df.index[df.index <= ann_dt_aware]
            if len(before) == 0:
                before = df.index[:1]
            ann_close = float(df.loc[before[-1], 'Close'])
        
        latest_close = float(df['Close'].iloc[-1])
        latest_vol = float(df['Volume'].iloc[-1])
        avg_vol_20 = float(df['Volume'].tail(20).mean()) if len(df) >= 20 else float(df['Volume'].mean())
        vol_ratio = latest_vol / avg_vol_20 if avg_vol_20 > 0 else 0
        pct_change = (latest_close - ann_close) / ann_close * 100
        
        results.append((code, name, ann_date, tplus, "OK", round(pct_change,1), round(vol_ratio,2), round(ann_close,2), round(latest_close,2)))
    except Exception as e:
        results.append((code, name, ann_date, tplus, f"ERR:{str(e)[:50]}", 0, 0, 0, 0))

print("CODE | NAME | ANN | T+ | CHANGE% | VOL_RATIO | ANN_CLOSE | LATEST")
print("-" * 90)
for r in sorted(results, key=lambda x: x[3]):
    print(f"{r[0]} | {r[1][:22]:22s} | {r[2]} | T+{r[3]} | {r[5]:+7.1f}% | {r[6]:.2f}x | {r[7]:.2f} | {r[8]:.2f}  [{r[4]}]")

print("\n=== RED ALERT CANDIDATES (ALL 3 conditions) ===")
red = 0
for r in results:
    code, name, ann, tplus, status, pct, vol, ann_c, now_c = r
    if status == "OK":
        vol_ok = vol >= 1.5
        jump_ok = pct >= 8.0
        if vol_ok and jump_ok:
            print(f"🔴 {code} {name} | T+{tplus} | {pct:+.1f}% | {vol:.2f}x | ${ann_c:.2f}->${now_c:.2f}")
            red += 1
        elif vol_ok or jump_ok:
            flag = "vol" if vol_ok else "jump"
            print(f"🟡 {code} {name} | T+{tplus} | {pct:+.1f}% | {vol:.2f}x | partial ({flag})")

if red == 0:
    print("NO RED ALERTS (0 meet all 3 conditions)")

print(f"\nTotal red: {red}")
