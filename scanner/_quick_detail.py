"""Fetch detailed data for corp action stocks."""
import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hk_cloud_scanner import (
    fetch_corp_action_announcements, hkt_today_str,
    get_daily_history, compute_volume_ratio, format_volume_ratio,
    get_prev_week_low, sl_yr_line, check_year_open_breakout,
    compute_sma_stop_loss, compute_target_prices, format_risk_stop_target,
    VOLUME_MULTIPLIER, WATCHLIST_EXPIRY_DAYS,
)

today_hkt = hkt_today_str()
print(f"=== HK Cloud Scanner Report ===")
print(f"TODAY={today_hkt}")
print(f"VOLUME_MULTIPLIER={VOLUME_MULTIPLIER}")
print(f"WATCHLIST_EXPIRY_DAYS={WATCHLIST_EXPIRY_DAYS}")
print()

raw = fetch_corp_action_announcements()
total_raw = len(raw)

today_anns = []
for ann in raw:
    if ann.get("release_date") == today_hkt:
        today_anns.append(ann)

print(f"TOTAL_RAW={total_raw}")
print(f"TODAY_COUNT={len(today_anns)}")
print()

alerts = []
watchlist = []

for i, ann in enumerate(today_anns):
    code = ann["code"]
    name = ann["name"]
    types_list = ann["types"]
    types_str = " / ".join(types_list)
    title = ann["title"]
    url = ann["url"]
    rel_time = ann.get("release_time", "")
    
    print(f"--- Processing {code} {name} ---")
    
    # Fetch price history
    vol_ratio = None
    df = None
    try:
        df = get_daily_history(code, "1y")
        if df is not None and not df.empty:
            vol_ratio = compute_volume_ratio(df)
    except Exception as exc:
        print(f"  Price fetch failed: {exc}")
    
    vol_str = format_volume_ratio(vol_ratio) if vol_ratio is not None else "N/A"
    vol_val = vol_ratio if vol_ratio is not None else 0
    print(f"  Volume ratio: {vol_str} (raw={vol_val})")
    
    # Check if immediate alert
    immediate = vol_ratio is not None and vol_ratio >= VOLUME_MULTIPLIER
    
    # Year open check
    yo_info = {}
    if df is not None and not df.empty:
        try:
            yo = check_year_open_breakout(code, name, df)
            if yo:
                yo_info = {
                    "year_open": str(yo.get("Year Open", "")),
                    "year_open_date": str(yo.get("Year Open Date", "")),
                    "break_pct": yo.get("Break %", 0),
                    "today_close": yo.get("Today Close", ""),
                    "break_value": yo.get("Break Value", ""),
                }
        except Exception as e:
            print(f"  Year open check failed: {e}")
    
    # Stop loss
    sl_info = ""
    if df is not None and not df.empty:
        pw_low = get_prev_week_low(df)
        cur_price = float(df.iloc[-1]["close"])
        sl = sl_yr_line(pw_low, cur_price, df)
        if sl:
            sl_info = sl.strip()
    
    rst_info = ""
    if df is not None and not df.empty:
        cur_price_f = float(df.iloc[-1]["close"])
        sma5 = compute_sma_stop_loss(df)
        hi52, hi3y = compute_target_prices(df)
        rst = format_risk_stop_target(cur_price_f, sma5, hi52, hi3y)
        if rst:
            rst_info = rst.strip()
    
    entry = {
        "code": code,
        "name": name,
        "types": types_str,
        "title": title,
        "url": url,
        "rel_time": rel_time,
        "vol_ratio": vol_ratio,
        "vol_str": vol_str,
        "immediate": immediate,
        "yo_info": yo_info,
        "sl_info": sl_info,
        "rst_info": rst_info,
    }
    
    if immediate:
        alerts.append(entry)
        print(f"  -> ALERT (volume >= threshold)")
    else:
        watchlist.append(entry)
        print(f"  -> WATCHLIST")
    
    print(f"  YearOpen: {json.dumps(yo_info, ensure_ascii=False) if yo_info else 'none'}")
    print(f"  SL: {sl_info}")
    print(f"  RST: {rst_info}")
    print()

print("=== SUMMARY ===")
print(f"Alerts: {len(alerts)}")
print(f"Watchlist: {len(watchlist)}")
print()

# Output structured JSON for report
result = {
    "today": today_hkt,
    "total_raw": total_raw,
    "today_count": len(today_anns),
    "volume_multiplier": VOLUME_MULTIPLIER,
    "watchlist_expiry_days": WATCHLIST_EXPIRY_DAYS,
    "alerts": alerts,
    "watchlist": watchlist,
}
print("JSON_START")
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
print("JSON_END")
