"""Graded corp analysis using yfinance for price data."""
import json, sys, os
from datetime import datetime, timedelta, timezone
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PROJ = _THIS_DIR.parent
sys.path.insert(0, str(_PROJ))
sys.path.insert(0, str(_THIS_DIR))

import yfinance as yf
import pandas as pd

HKT = timezone(timedelta(hours=8))

def hkt_today_str():
    return datetime.now(HKT).strftime("%Y-%m-%d")

def load_announcements():
    path = _PROJ / "data" / "announcements.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _flatten_yf_df(df):
    """Flatten MultiIndex columns from yfinance to simple column names."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        # yfinance returns ('Close', 'TICKER.HK'), ('Volume', 'TICKER.HK'), etc.
        # Use level 0 (field name) for the flattened column names
        df.columns = df.columns.get_level_values(0)
    return df

def _get_col(df, col_name):
    """Safely get a column, handling both Series and MultiIndex DataFrames."""
    if isinstance(df, pd.DataFrame) and isinstance(df.columns, pd.MultiIndex):
        for c in df.columns:
            if str(c[0]).lower() == col_name.lower():
                return df[c]
    if col_name in df.columns:
        return df[col_name]
    cols_lower = {str(c).lower(): c for c in df.columns}
    if col_name.lower() in cols_lower:
        return df[cols_lower[col_name.lower()]]
    return None

def get_yf_ohlcv(code, start, end):
    """Fetch OHLCV from Yahoo Finance for HK stock."""
    ticker = f"{int(code):04d}.HK"
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty:
            return None
        df = _flatten_yf_df(df)
        return df
    except Exception:
        return None

def compute_volume_ratio_yf(df, ann_date_str):
    """Volume ratio: ann day vs 20-day avg (excl ann day)."""
    if df.empty or len(df) < 5:
        return None
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
    ann_vol_series = _get_col(ann_rows.iloc[-1:], "Volume")
    if ann_vol_series is None:
        return None
    ann_vol = float(ann_vol_series.iloc[-1])
    if ann_vol == 0:
        return None
    return round(ann_vol / avg_vol, 3)

def compute_tplus_jump_yf(df, ann_date_str):
    """Max close-to-close jump from T+1 to T+5."""
    ann_date = pd.Timestamp(ann_date_str)
    if df.index.tz is not None:
        df = df.tz_localize(None)
    t0_rows = df[df.index.date == ann_date.date()]
    if t0_rows.empty:
        return 0.0, "no T+0 data"
    close_series = _get_col(t0_rows.iloc[-1:], "Close")
    if close_series is None:
        return 0.0, "no close col"
    t0_close = float(close_series.iloc[-1])
    
    t5 = ann_date + timedelta(days=5)
    post = df[(df.index > ann_date) & (df.index <= t5 + timedelta(days=3))]
    
    max_jump = 0.0
    best_t = ""
    post_close = _get_col(post, "Close")
    if post_close is not None:
        for idx, c_val in post_close.items():
            c = float(c_val)
            jump = (c - t0_close) / t0_close * 100
            if jump > max_jump:
                max_jump = jump
                days = (idx.date() - ann_date.date()).days
                best_t = f"T+{days}"
    return round(max_jump, 2), best_t

def load_volume_ratio_from_stock_prices():
    """Load vr from stock_prices.json as fallback."""
    path = _PROJ / "data" / "stock_prices.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    today = hkt_today_str()
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    cutoff = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    
    anns_raw = load_announcements()
    recent = [a for a in anns_raw if a["date"] >= cutoff]
    
    def has_type(ann, target):
        types = ann.get("types", [])
        for t in types:
            if target in t:
                return True
        return ann.get("type", "") == target
    
    placements_raw = [a for a in recent if has_type(a, "配股") or a.get("type") == "placement"]
    zengchi_raw = [a for a in recent if has_type(a, "增持") and not has_type(a, "配股")]
    gonggu_raw = [a for a in recent if has_type(a, "供股") and not has_type(a, "配股")]
    
    def dedup(anns):
        seen = {}
        for a in sorted(anns, key=lambda x: x["date"]):
            code = a["code"]
            if code not in seen:
                seen[code] = a
        return list(seen.values())
    
    placements = dedup(placements_raw)
    zengchi = dedup(zengchi_raw)
    gonggu = dedup(gonggu_raw)
    
    print(f"Cutoff: {cutoff} → {today}")
    print(f"Raw recent: {len(recent)} | Placements: {len(placements)} | 增持: {len(zengchi)} | 供股: {len(gonggu)}")
    
    sp = load_volume_ratio_from_stock_prices()
    
    # Title-based filters: exclude completions, lapses, CB
    def _title_flags(title):
        flags = []
        t = (title or "").upper()
        if "完成" in title and "未完成" not in title:
            flags.append("完成")
        if "LAPSE" in t:
            flags.append("LAPSE")
        if "CONVERTIBLE BOND" in t or "CONVERTIBLE BONDS" in t or "可換股" in title:
            flags.append("CB")
        return flags
    
    red = []
    watch = []
    skip = {"type=增持": len(zengchi), "vol<1.5x": 0, "jump<8%": 0, "no_data": 0,
            "today_no_post": 0, "完成/LAPSE": 0, "CB": 0}
    
    for ann in placements:
        code = ann["code"]
        name = ann["name"]
        date = ann["date"]
        types = " / ".join(ann.get("types", []))
        
        if date >= today:
            skip["today_no_post"] += 1
            watch.append({"code": code, "name": name, "date": date, "types": types, "skip": "today_no_post", "watch_type": "配股"})
            print(f"\n{code} {name} | {date} → today, watchlist only")
            continue
        
        # Title-based filtering: skip completions, lapses; flag CB as watchlist
        title = ann.get("title", "") or ""
        flags = _title_flags(title)
        if "完成" in flags or "LAPSE" in flags:
            skip["完成/LAPSE"] += 1
            print(f"\n{code} {name} | {date} | {types} → SKIP ({'/'.join(flags)})")
            continue
        if "CB" in flags:
            skip["CB"] += 1
            watch.append({"code": code, "name": name, "date": date, "types": types,
                          "skip": "type=CB/可換股", "watch_type": "配股"})
            print(f"\n{code} {name} | {date} | {types} → WATCHLIST (CB/可換股)")
            continue
        
        start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
        end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
        
        df = get_yf_ohlcv(code, start, end)
        if df is None or df.empty:
            sp_data = sp.get(code, {})
            vr = sp_data.get("vr")
            skip["no_data"] += 1
            if vr is not None:
                print(f"\n{code} {name} | {date} → yf no data, stock_prices vr={vr:.1f}x → watchlist")
            else:
                print(f"\n{code} {name} | {date} → NO PRICE DATA")
            watch.append({"code": code, "name": name, "date": date, "types": types, "skip": "no_yf_data", "watch_type": "配股", "vr_fallback": vr})
            continue
        
        vol_r = compute_volume_ratio_yf(df, date)
        tplus, tlabel = compute_tplus_jump_yf(df, date)
        
        print(f"\n{code} {name} | {date} | {types}")
        print(f"  Vol ratio: {vol_r:.1f}x" if vol_r else f"  Vol ratio: N/A")
        print(f"  T+ jump: {tplus}% ({tlabel})")
        
        if vol_r is not None and vol_r >= 1.5 and tplus >= 8.0:
            red.append({
                "code": code, "name": name, "types": types, "date": date,
                "vol_ratio": vol_r, "tplus_jump": tplus, "tplus_label": tlabel,
            })
            print(f"  🔴 RED ALERT")
        else:
            if vol_r is None or vol_r < 1.5:
                skip["vol<1.5x"] += 1
            if tplus < 8.0:
                skip["jump<8%"] += 1
            watch.append({
                "code": code, "name": name, "date": date, "types": types,
                "vol_ratio": vol_r, "tplus_jump": tplus, "tplus_label": tlabel,
                "skip": f"vol={vol_r}x jump={tplus}%" if vol_r is not None else f"no_data jump={tplus}%", "watch_type": "配股",
            })
            print(f"  🟡 WATCHLIST")
    
    for ann in zengchi:
        watch.append({"code": ann["code"], "name": ann["name"], "date": ann["date"],
                      "types": " / ".join(ann.get("types", [])), "skip": "type=增持", "watch_type": "增持"})
    for ann in gonggu:
        watch.append({"code": ann["code"], "name": ann["name"], "date": ann["date"],
                      "types": " / ".join(ann.get("types", [])), "skip": "type=供股", "watch_type": "供股"})
    
    seen_wl = {}
    for w in watch:
        c = w["code"]
        if c not in seen_wl or w.get("watch_type") == "配股":
            seen_wl[c] = w
    watch_unique = list(seen_wl.values())
    
    print(f"\n{'='*60}")
    print(f"RESULTS: {today} ({today_dt.strftime('%A')})")
    print(f"🔴 RED: {len(red)} | 🟡 WATCHLIST: {len(watch_unique)}")
    print(f"Skip: {skip}")
    
    result = {
        "date": today, "date_iso": today, "weekday": today_dt.strftime("%A"),
        "total_raw": len(recent), "red_alerts": red, "watchlist": watch_unique,
        "skip_reasons": skip,
    }
    
    out_path = _THIS_DIR / "corp_graded_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nWritten: {out_path}")

if __name__ == "__main__":
    main()
