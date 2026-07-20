"""Self-contained corp grading: scrape HKEXnews + grade with yfinance.
Replaces _corp_graded_scan.py (Futu) + _corp_followup.py for when Futu API returns empty.
"""
import json, sys, os
from datetime import datetime, timedelta, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PROJ = THIS_DIR.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(THIS_DIR))

# Load .env
env_path = PROJ / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val

import yfinance as yf
import pandas as pd

HKT = timezone(timedelta(hours=8))
HKT_TODAY = datetime.now(HKT).strftime("%Y-%m-%d")
HKT_DT = datetime.now(HKT)
HKT_WEEKDAY = HKT_DT.strftime("%A")

# ============ Step 1: Scrape announcements ============
print(f"=== HK Corp Graded Scan (yfinance live) === {HKT_TODAY} ({HKT_WEEKDAY}) ===", flush=True)

from hk_cloud_scanner import fetch_corp_action_announcements

print("[1] Fetching announcements from HKEXnews...", flush=True)
raw_anns = fetch_corp_action_announcements()
print(f"    Got {len(raw_anns)} raw announcements", flush=True)

# Normalize: ensure 'date' field
for a in raw_anns:
    if 'date' not in a and 'release_date' in a:
        a['date'] = a['release_date']

# ============ Helpers ============

def hk_code_to_yahoo(code):
    return f"{int(code):04d}.HK"

def get_yf_ohlcv(code, start, end):
    ticker = hk_code_to_yahoo(code)
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None

def _get_col(df, col_name):
    if isinstance(df.columns, pd.MultiIndex):
        for c in df.columns:
            if str(c[0]).lower() == col_name.lower():
                return df[c]
    if col_name in df.columns:
        return df[col_name]
    cols_lower = {str(c).lower(): c for c in df.columns}
    if col_name.lower() in cols_lower:
        return df[cols_lower[col_name.lower()]]
    return None

def compute_vol_ratio(df, ann_date_str):
    ann_date = pd.Timestamp(ann_date_str)
    if df.index.tz is not None:
        df = df.tz_localize(None)
    before = df[df.index < ann_date].tail(20)
    if len(before) < 10:
        return None
    vol_series = _get_col(before, "Volume")
    if vol_series is None:
        return None
    avg_vol = float(vol_series.mean())
    if avg_vol == 0:
        return None
    ann_rows = df[df.index.date == ann_date.date()]
    if ann_rows.empty:
        return None
    avs = _get_col(ann_rows.iloc[-1:], "Volume")
    if avs is None:
        return None
    ann_vol = float(avs.iloc[-1])
    if ann_vol == 0:
        return None
    return round(ann_vol / avg_vol, 3)

def compute_tplus_jump(df, ann_date_str):
    """Max close-to-close jump T+1~T+5. Returns (pct, day, ann_close)."""
    ann_date = pd.Timestamp(ann_date_str)
    if df.index.tz is not None:
        df = df.tz_localize(None)
    t0_rows = df[df.index.date == ann_date.date()]
    if t0_rows.empty:
        return 0.0, 0, None, "no T+0 data"
    close_s = _get_col(t0_rows.iloc[-1:], "Close")
    if close_s is None:
        return 0.0, 0, None, "no close col"
    t0_close = float(close_s.iloc[-1])

    t5 = ann_date + timedelta(days=5)
    post = df[(df.index > ann_date) & (df.index <= t5 + timedelta(days=3))]
    max_jump = 0.0
    best_day = 0
    post_close = _get_col(post, "Close")
    if post_close is not None:
        for idx, c_val in post_close.items():
            c = float(c_val)
            jump = (c / t0_close - 1) * 100
            if jump > max_jump:
                max_jump = jump
                best_day = (idx.date() - ann_date.date()).days
    return round(max_jump, 2), best_day, round(t0_close, 3), ""

def has_type(ann, target):
    types = ann.get("types", [])
    for t in types:
        if target in t:
            return True
    return False

CB_KEYWORDS = ["CONVERTIBLE BOND", "CONVERTIBLE BONDS", "可換股", "可换股"]

def is_cb(title):
    t = (title or "").upper()
    return any(kw.upper() in t for kw in CB_KEYWORDS)

def is_complete_or_lapse(title):
    raw = title or ""
    t = raw.upper()
    if "未完成" in raw:
        return False
    return ("完成" in raw) or ("COMPLETION" in t) or ("LAPSE" in t)

# ============ Step 2: Classify ============

# Same-day announcements
same_day = [a for a in raw_anns if a.get('date') == HKT_TODAY]
# Past 5 days
past_5d = []
for a in raw_anns:
    d = a.get('date', '')
    if not d:
        continue
    try:
        ad = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=HKT)
        delta = (HKT_DT - ad).days
        if 1 <= delta <= 5:
            past_5d.append(a)
    except ValueError:
        continue

print(f"[2] Same-day: {len(same_day)} | Past 5d: {len(past_5d)}", flush=True)

# Combine all relevant for grading
all_candidates = []

# Same-day: all types go to watchlist (no post-ann data yet)
for a in same_day:
    code = a.get('code', '')
    name = a.get('name', '')
    date = a.get('date', '')
    types_str = " / ".join(a.get("types", []))
    title = a.get("title", "") or ""
    url = a.get("url", "")

    all_candidates.append({
        "code": code, "name": name, "date": date, "types_str": types_str,
        "title": title, "url": url, "is_today": True,
        "is_placement": has_type(a, "配股") or has_type(a, "配售"),
        "is_increase": has_type(a, "增持"),
        "is_rights": has_type(a, "供股"),
    })

# Past 5d: only placements that aren't 完成/LAPSE/CB
for a in past_5d:
    code = a.get('code', '')
    name = a.get('name', '')
    date = a.get('date', '')
    title = a.get("title", "") or ""
    url = a.get("url", "")

    if not (has_type(a, "配股") or has_type(a, "配售")):
        continue
    if is_complete_or_lapse(title):
        continue
    if is_cb(title):
        continue

    all_candidates.append({
        "code": code, "name": name, "date": date, "types_str": " / ".join(a.get("types", [])),
        "title": title, "url": url, "is_today": False,
        "is_placement": True, "is_increase": False, "is_rights": False,
    })

# Dedup by code (keep earliest non-today first, then today)
seen = {}
for c in sorted(all_candidates, key=lambda x: (x["is_today"], x["date"])):
    if c["code"] not in seen:
        seen[c["code"]] = c
candidates = list(seen.values())

print(f"[3] Candidates to grade: {len(candidates)}", flush=True)

# ============ Step 3: Grade ============

red_alerts = []
watchlist = []
skip_reasons = {
    "type=增持": 0,
    "type=供股": 0,
    "type=其他": 0,
    "vol<1.5x": 0,
    "jump<8%": 0,
    "no_yf_data": 0,
    "today_no_post": 0,
    "完成/LAPSE": 0,
    "CB/可換股": 0,
}

# Count same-day by type for skip breakdown
for a in same_day:
    if has_type(a, "增持"):
        skip_reasons["type=增持"] += 1
    elif has_type(a, "供股"):
        skip_reasons["type=供股"] += 1

for i, c in enumerate(candidates):
    code = c["code"]
    name = c["name"]
    date = c["date"]
    types_str = c["types_str"]
    title = c["title"]
    url = c["url"]
    is_today = c["is_today"]
    is_placement = c["is_placement"]
    is_increase = c["is_increase"]
    is_rights = c["is_rights"]

    print(f"\n[{i+1}/{len(candidates)}] {code} {name} | {date} | {types_str}", flush=True)

    # Non-placement + non-today → skip reasons
    if is_today and not is_placement:
        skip_reasons["type=其他"] += 1
        watchlist.append({
            "code": code, "name": name, "date": date,
            "types": types_str, "skip": f"type=其他", "watch_type": "其他"
        })
        print(f"  → 🟡 WATCHLIST (type=其他)", flush=True)
        continue

    if is_today and is_increase:
        watchlist.append({
            "code": code, "name": name, "date": date,
            "types": types_str, "skip": "type=增持 (backtest pending)", "watch_type": "增持"
        })
        print(f"  → 🟡 WATCHLIST (type=增持)", flush=True)
        continue

    if is_today and is_rights:
        watchlist.append({
            "code": code, "name": name, "date": date,
            "types": types_str, "skip": "type=供股 (backtest pending)", "watch_type": "供股"
        })
        print(f"  → 🟡 WATCHLIST (type=供股)", flush=True)
        continue

    # Today's placements → watchlist (no post-ann data yet)
    if is_today:
        skip_reasons["today_no_post"] += 1
        watchlist.append({
            "code": code, "name": name, "date": date,
            "types": types_str, "skip": "today_no_post (T+0, no post-ann data)",
            "watch_type": "配售"
        })
        print(f"  → 🟡 WATCHLIST (today, pending T+1~T+5)", flush=True)
        continue

    # Past placements → full grade
    # Fetch price data
    start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")

    df = get_yf_ohlcv(code, start, end)
    if df is None or df.empty:
        skip_reasons["no_yf_data"] += 1
        watchlist.append({
            "code": code, "name": name, "date": date,
            "types": types_str, "skip": "no_yf_data", "watch_type": "配售"
        })
        print(f"  → 🟡 WATCHLIST (no yfinance data)", flush=True)
        continue

    vol_r = compute_vol_ratio(df, date)
    tplus, best_day, t0_close, err = compute_tplus_jump(df, date)

    vol_str = f"{vol_r:.2f}x" if vol_r is not None else "N/A"
    print(f"  Vol ratio: {vol_str} | T+{best_day} jump: {tplus}% (ann close={t0_close})", flush=True)

    # === GRADING ===
    if vol_r is not None and vol_r >= 1.5 and tplus >= 8.0:
        # Compute approximate discount from title
        red_alerts.append({
            "code": code, "name": name, "types": types_str, "date": date,
            "vol_ratio": vol_r, "tplus_jump": tplus, "tplus_day": best_day,
            "ann_close": t0_close, "title": title, "url": url,
        })
        print(f"  🔴 RED ALERT — 8120 triggered!", flush=True)
    else:
        reasons = []
        if vol_r is None or vol_r < 1.5:
            reasons.append(f"vol={vol_str}<1.5x")
            skip_reasons["vol<1.5x"] += 1
        if tplus < 8.0:
            reasons.append(f"jump={tplus}%<8%")
            skip_reasons["jump<8%"] += 1
        watchlist.append({
            "code": code, "name": name, "date": date,
            "types": types_str, "vol_ratio": vol_r, "tplus_jump": tplus,
            "skip": "; ".join(reasons) if reasons else "partial match",
            "watch_type": "配售"
        })
        print(f"  🟡 WATCHLIST — {'; '.join(reasons) if reasons else 'partial'}", flush=True)

# Add past-5d 增持/供股 to watchlist (dedup)
past_zengchi = {}
past_gonggu = {}
for a in past_5d:
    code = a.get('code', '')
    if has_type(a, "增持") and not has_type(a, "配股") and not has_type(a, "配售"):
        if code not in past_zengchi:
            past_zengchi[code] = a
    if has_type(a, "供股") and not has_type(a, "配股") and not has_type(a, "配售"):
        if code not in past_gonggu:
            past_gonggu[code] = a

skip_reasons["type=增持"] += len(past_zengchi)
skip_reasons["type=供股"] += len(past_gonggu)

for a in past_zengchi.values():
    watchlist.append({
        "code": a.get("code"), "name": a.get("name"), "date": a.get("date"),
        "types": " / ".join(a.get("types", [])),
        "skip": "type=增持 (backtest pending)", "watch_type": "增持"
    })
for a in past_gonggu.values():
    watchlist.append({
        "code": a.get("code"), "name": a.get("name"), "date": a.get("date"),
        "types": " / ".join(a.get("types", [])),
        "skip": "type=供股 (backtest pending)", "watch_type": "供股"
    })

# Final dedup: keep placement entries over non-placement
seen_wl = {}
for w in watchlist:
    c = w["code"]
    if c not in seen_wl:
        seen_wl[c] = w
    elif w.get("watch_type") == "配售":
        seen_wl[c] = w
watch_unique = list(seen_wl.values())

# ============ Summary ============
print(f"\n{'='*60}")
print(f"SCAN COMPLETE — {HKT_TODAY} ({HKT_WEEKDAY})")
print(f"Total raw: {len(raw_anns)} | Same-day: {len(same_day)}")
print(f"🔴 RED: {len(red_alerts)} | 🟡 WATCHLIST: {len(watch_unique)}")
print(f"Skip: {skip_reasons}")
print(f"{'='*60}")

result = {
    "scan_date": HKT_TODAY,
    "scan_time": HKT_DT.strftime("%H:%M:%S"),
    "weekday": HKT_WEEKDAY,
    "total_raw": len(raw_anns),
    "total_same_day": len(same_day),
    "red_alerts": red_alerts,
    "watchlist": watch_unique,
    "skip_reasons": skip_reasons,
}

out_path = PROJ / "data" / "corp_graded_result_yf.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)

print(f"\n__RESULTS_JSON__")
print(json.dumps(result, ensure_ascii=False, default=str))
