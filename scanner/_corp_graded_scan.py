"""
Strict corp action scan — applies new ALERT GRADING RULES (2026-06-10).
- 🔴 RED: placement + vol≥1.5x + price jump≥8% within T+1~T+5
- 🟡 WATCHLIST: everything else (silent, store only)
- 🚫 EXCLUDED: FVG, POC, year-open (proven zero edge)
"""
import os, sys, json, time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# Setup path
THIS_DIR = Path(__file__).resolve().parent
PROJ_ROOT = THIS_DIR.parent
for p in (PROJ_ROOT, THIS_DIR):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

# Load .env
env_path = PROJ_ROOT / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val

HKT_TZ = __import__('datetime', fromlist=['timezone']).timezone(timedelta(hours=8), name='HKT')

def hkt_today_str():
    return datetime.now(HKT_TZ).strftime("%Y-%m-%d")

def hkt_now():
    return datetime.now(HKT_TZ)

today = hkt_today_str()
print(f"=== HK Corp Graded Scan === {today} ===", flush=True)

# Import scanner functions
print("[1] Importing scanner modules...", flush=True)
from hk_cloud_scanner import (
    fetch_corp_action_announcements,
    hk_code_to_hk_symbol,
    get_daily_history,
    compute_volume_ratio,
    VOLUME_MULTIPLIER,
)
from local_alert_store import store_alert, add_to_watchlist

print("[2] Fetching announcements from HKEXnews...", flush=True)
raw_anns = fetch_corp_action_announcements()
print(f"[2a] Got {len(raw_anns)} raw announcements", flush=True)

# Filter same-day
same_day = []
skipped_old = 0
skipped_unknown = 0
seen = set()
for ann in raw_anns:
    rd = ann.get("release_date")
    if rd is None:
        skipped_unknown += 1
        continue
    if rd != today:
        skipped_old += 1
        continue
    key = f"{ann.get('code','')}|{ann.get('url','')}"
    if key in seen:
        continue
    seen.add(key)
    same_day.append(ann)

print(f"[3] Same-day filter: kept={len(same_day)} skipped_old={skipped_old} skipped_unknown={skipped_unknown}", flush=True)

# Process each announcement
results = []
red_alerts = []
watchlist = []

for i, ann in enumerate(same_day):
    code = ann["code"]
    name = ann["name"]
    types_list = ann["types"]
    types_str = " / ".join(types_list)
    title = ann["title"]
    ann_date = ann.get("release_date", "")
    rel_time = ann.get("release_time", "")
    url = ann.get("url", "")
    
    print(f"\n[4.{i+1}/{len(same_day)}] {code} {name} | {types_str}", flush=True)
    
    # Check if it's a placement type (配售)
    is_placement = "配售" in types_list or "配股" in types_list
    is_increase = "增持" in types_list or "股東增持" in types_list
    is_rights = "供股" in types_list
    is_block_trade = "轉倉" in types_list or "大手轉倉" in types_list
    
    # Fetch price data
    df = None
    vol_ratio = None
    price_jump_pct = None
    jump_detail = ""
    
    try:
        df = get_daily_history(code, "3mo")  # enough for T+5 check
        if not df.empty:
            vol_ratio = compute_volume_ratio(df)
            
            # Check price jump for placement types
            if is_placement and vol_ratio is not None and vol_ratio >= 1.5:
                # Check T+1 to T+5 price jump from announcement date
                try:
                    ann_dt = datetime.strptime(ann_date, "%Y-%m-%d").replace(tzinfo=HKT_TZ)
                except ValueError:
                    ann_dt = None
                
                if ann_dt:
                    close_on_ann = None
                    close_after = None
                    days_after = 0
                    
                    for _, row in df.iterrows():
                        d = row.get("date")
                        if d is None:
                            continue
                        if isinstance(d, datetime):
                            dt = d.replace(tzinfo=HKT_TZ) if d.tzinfo is None else d
                        else:
                            try:
                                dt = pd.Timestamp(d).to_pydatetime().replace(tzinfo=HKT_TZ)
                            except Exception:
                                continue
                        
                        if dt.date() == ann_dt.date():
                            close_on_ann = float(row["close"])
                        elif dt.date() > ann_dt.date():
                            days_diff = (dt.date() - ann_dt.date()).days
                            if 1 <= days_diff <= 5:
                                if close_after is None or (float(row["close"]) / close_on_ann - 1) > (close_after / close_on_ann - 1):
                                    close_after = float(row["close"])
                                    days_after = days_diff
                    
                    if close_on_ann is not None and close_after is not None:
                        price_jump_pct = round((close_after / close_on_ann - 1) * 100, 1)
                        jump_detail = f"T+{days_after} close {close_after:.2f} vs ann close {close_on_ann:.2f}"
    except Exception as exc:
        print(f"  [WARN] price fetch failed for {code}: {exc}", flush=True)
    
    vol_str = f"{vol_ratio:.1f}x" if vol_ratio is not None else "N/A"
    
    # === GRADING LOGIC ===
    red = False
    watch = False
    skip_reason = ""
    
    # Check 8120 pattern: 配售 + vol≥1.5x + jump≥8%
    if is_placement and vol_ratio is not None and vol_ratio >= 1.5 and price_jump_pct is not None and price_jump_pct >= 8.0:
        red = True
        grade = "🔴 RED"
    elif is_placement:
        # Placement but missing vol or jump
        watch = True
        grade = "🟡 WATCHLIST"
        reasons = []
        if vol_ratio is None or vol_ratio < 1.5:
            reasons.append(f"vol={vol_str}<1.5x")
        if price_jump_pct is None:
            reasons.append("jump=N/A (insufficient history)")
        elif price_jump_pct < 8.0:
            reasons.append(f"jump={price_jump_pct}%<8%")
        skip_reason = "; ".join(reasons) if reasons else "partial match"
    elif is_increase:
        watch = True
        grade = "🟡 WATCHLIST"
        skip_reason = "type=增持 (backtest pending)"
    elif is_rights:
        watch = True
        grade = "🟡 WATCHLIST"
        skip_reason = "type=供股 (backtest pending)"
    elif is_block_trade:
        watch = True
        grade = "🟡 WATCHLIST"
        skip_reason = "type=轉倉/大手上板"
    else:
        watch = True
        grade = "🟡 WATCHLIST"
        skip_reason = f"type={types_str}"
    
    entry = {
        "code": code,
        "name": name,
        "types": types_list,
        "types_str": types_str,
        "title": title,
        "ann_date": ann_date,
        "rel_time": rel_time,
        "url": url,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "price_jump_pct": price_jump_pct,
        "jump_detail": jump_detail,
        "grade": grade,
        "red": red,
        "watch": watch,
        "skip_reason": skip_reason if not red else "",
        "placement": is_placement,
        "increase": is_increase,
        "rights": is_rights,
    }
    
    if red:
        red_alerts.append(entry)
        # Store alert
        try:
            store_alert({
                "source": "hkexnews",
                "category": "corp_action_8120",
                "code": code,
                "symbol": hk_code_to_hk_symbol(code),
                "name": name,
                "signal": f"8120·{types_str}",
                "timeframe": "T+{days_after}D",
                "message": f"配售+量比{vol_str}+跳升{price_jump_pct}% {title}",
                "strategy": "8120 Corp Action",
                "chart_url": "",
                "source_url": url,
                "announcement_date": ann_date,
                "release_time": rel_time,
                "tags": ["8120", "紅警", *types_list],
                "priority": 5,
                "raw": json.dumps(entry, ensure_ascii=False),
            })
        except Exception as exc:
            print(f"  [WARN] store_alert failed: {exc}", flush=True)
    elif watch:
        watchlist.append(entry)
        # Store watchlist entry
        try:
            add_to_watchlist(code, name, types_list, ann_date)
        except Exception as exc:
            print(f"  [WARN] add_to_watchlist failed: {exc}", flush=True)
    
    print(f"  → {grade} | vol={vol_str} | jump={price_jump_pct}% | reason={skip_reason}", flush=True)
    results.append(entry)

# Summary
n_red = len(red_alerts)
n_watch = len(watchlist)

# Save results
out_path = PROJ_ROOT / "data" / "corp_graded_scan.json"
os.makedirs(out_path.parent, exist_ok=True)
output = {
    "scan_date": today,
    "scan_time": hkt_now().strftime("%H:%M:%S"),
    "total_raw": len(raw_anns),
    "same_day": len(same_day),
    "red_alerts": n_red,
    "watchlist": n_watch,
    "results": results,
}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"SCAN COMPLETE — {today}")
print(f"Total raw: {len(raw_anns)} | Same-day: {len(same_day)}")
print(f"🔴 RED: {n_red} | 🟡 WATCHLIST: {n_watch}")
print(f"Output: {out_path}")
print(f"{'='*60}")

# Print results as JSON for parsing
print("\n__RESULTS_JSON__")
print(json.dumps({"red": red_alerts, "watch": watchlist, "summary": {
    "date": today,
    "total_raw": len(raw_anns),
    "same_day": len(same_day),
    "red": n_red,
    "watch": n_watch,
}}, ensure_ascii=False))
