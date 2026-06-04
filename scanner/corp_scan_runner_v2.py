"""Enhanced corp scan runner with gap + FVG computation."""
import json, sys, os, time
from datetime import datetime, timezone, timedelta
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HKT_TZ = timezone(timedelta(hours=8))

from scanner.hk_cloud_scanner import (
    fetch_corp_action_announcements,
    get_daily_history,
    compute_volume_ratio,
    VOLUME_MULTIPLIER,
    WATCHLIST_EXPIRY_DAYS,
    _IMMEDIATE_ALERT_TYPES,
    _CORP_TYPE_PRIORITY,
    get_year_open_price,
    get_prev_week_low,
    sl_yr_line,
    tradingview_url,
    hk_code_to_yahoo,
    hkt_today_str,
)

today_hkt_str_val = hkt_today_str()
now_hkt = datetime.now(HKT_TZ)
weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][now_hkt.weekday()]
date_display = now_hkt.strftime("%Y/%m/%d")

print(f"=== HK Corp Scanner Start: {date_display} 星期{weekday_cn} ===", flush=True)
print(f"Volume multiplier: {VOLUME_MULTIPLIER}x", flush=True)

raw_anns = fetch_corp_action_announcements()

# Same-day filter
anns = []
skipped_old = 0
seen = set()
for ann in raw_anns:
    rd = ann.get("release_date")
    if rd is None:
        continue
    if rd != today_hkt_str_val:
        skipped_old += 1
        continue
    key = f"{ann.get('code','')}|{ann.get('url','')}"
    if key in seen:
        continue
    seen.add(key)
    anns.append(ann)

print(f"Total raw: {len(raw_anns)}, Today ({today_hkt_str_val}): {len(anns)}, Skipped old: {skipped_old}", flush=True)


def compute_gap(df: pd.DataFrame) -> dict | None:
    """Compute today's gap: (today_open - prev_close) / prev_close * 100."""
    if df.empty or len(df) < 2:
        return None
    prev = df.iloc[-2]
    today = df.iloc[-1]
    if pd.isna(prev.get("close")) or pd.isna(today.get("open")):
        return None
    try:
        prev_close = float(prev["close"])
        today_open = float(today["open"])
        if prev_close <= 0:
            return None
        gap_pct = round((today_open - prev_close) / prev_close * 100, 2)
        direction = "🔼" if gap_pct > 0 else "🔽" if gap_pct < 0 else ""
        return {"pct": gap_pct, "direction": direction}
    except Exception:
        return None


def compute_fvg(df: pd.DataFrame) -> dict | None:
    """Detect bullish FVG on daily: 3 candles where high[i-2] < low[i], gap=(high[i-2], low[i]).
       Returns the most recent fresh FVG."""
    if df.empty or len(df) < 3:
        return None
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    # Scan from most recent back through last 60 candles
    start = max(0, n - 60)
    for i in range(n - 1, start + 1, -1):
        if highs[i - 2] < lows[i]:
            fvg_top = lows[i]
            fvg_bottom = highs[i - 2]
            current_price = closes[-1]
            # Check freshness: no subsequent candle low has crossed below midpoint
            midpoint = (fvg_top + fvg_bottom) / 2
            crossed = False
            for j in range(i + 1, n):
                if lows[j] < midpoint:
                    crossed = True
                    break
            if crossed:
                continue
            # FVG size as % of current price
            size_pct = round((fvg_top - fvg_bottom) / fvg_bottom * 100, 2)
            # Distance from current price to FVG top
            dist_pct = round((fvg_top - current_price) / current_price * 100, 2)
            return {
                "top": round(fvg_top, 4),
                "bottom": round(fvg_bottom, 4),
                "idx": i,
                "size_pct": size_pct,
                "dist_pct": dist_pct,
            }
    return None


results = {"alerted": [], "watchlisted": [], "summary": {
    "date": date_display,
    "date_iso": today_hkt_str_val,
    "weekday": f"星期{weekday_cn}",
    "total_raw": len(raw_anns),
    "today_count": len(anns),
    "volume_multiplier": VOLUME_MULTIPLIER,
}}

for ann in anns:
    code = ann["code"]
    types_list = ann["types"]
    types_str = " / ".join(types_list)
    title_cn = ann["title"]
    ann_date = ann.get("release_date", "")
    release_time = ann.get("release_time", "")
    url = ann.get("url", "")
    tv_url = tradingview_url(code)

    priority = max((_CORP_TYPE_PRIORITY.get(t, 1) for t in types_list), default=1)
    immediate = any(t in _IMMEDIATE_ALERT_TYPES for t in types_list)

    vol_ratio = None
    cur_price = 0.0
    pw_low = None
    yr_open = None
    yr_open_rel = ""
    gap_info = None
    fvg_info = None
    try:
        df = get_daily_history(code, "1y")
        if not df.empty:
            vol_ratio = compute_volume_ratio(df)
            cur_price = float(df.iloc[-1]["close"])
            pw_low = get_prev_week_low(df)
            yr_open_val = get_year_open_price(df)
            if yr_open_val is not None:
                yr_open = round(yr_open_val, 4)
                yr_open_rel = "🔺高於年開" if cur_price > yr_open_val else "🔻低於年開"
            if vol_ratio is not None and vol_ratio >= VOLUME_MULTIPLIER:
                immediate = True
            gap_info = compute_gap(df)
            fvg_info = compute_fvg(df)
    except Exception as exc:
        print(f"[corp] price fetch failed for {code}: {exc}", flush=True)

    entry = {
        "code": code,
        "name": ann["name"],
        "types": types_str,
        "types_list": types_list,
        "title_cn": title_cn,
        "volume_ratio": vol_ratio,
        "cur_price": cur_price,
        "prev_week_low": pw_low,
        "year_open": yr_open,
        "year_open_rel": yr_open_rel,
        "gap": gap_info,
        "fvg": fvg_info,
        "release_time": release_time,
        "url": url,
        "tv_url": tv_url,
        "priority": priority,
        "immediate": immediate,
    }

    if immediate:
        results["alerted"].append(entry)
    else:
        results["watchlisted"].append(entry)

    vol_str = f"{vol_ratio:.1f}x" if vol_ratio is not None else "N/A"
    gap_str = f" gap={gap_info['pct']}%" if gap_info else ""
    fvg_str = f" FVG={fvg_info['size_pct']}%" if fvg_info else ""
    status = "ALERT" if immediate else "WATCH"
    print(f"  [{status}] {code} {ann['name']} | {types_str} | vol={vol_str} | yr_open={yr_open}{gap_str}{fvg_str} | {title_cn[:80]}", flush=True)
    time.sleep(0.3)

results["summary"]["alerted_count"] = len(results["alerted"])
results["summary"]["watchlisted_count"] = len(results["watchlisted"])

out_path = os.path.join(os.path.dirname(__file__), "corp_scan_result.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print(f"\n=== Done ===", flush=True)
print(f"Alerts: {len(results['alerted'])}, Watchlist: {len(results['watchlisted'])}", flush=True)
print(f"Output: {out_path}", flush=True)
