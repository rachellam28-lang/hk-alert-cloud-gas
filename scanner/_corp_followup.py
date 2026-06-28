"""
Check past announcements (T-5 to T-1) for price jump ≥8% (T+1~T+5 from ann date).
"""
import os, sys, json, time
from datetime import datetime, timedelta
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PROJ_ROOT = THIS_DIR.parent
for p in (PROJ_ROOT, THIS_DIR):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

env_path = PROJ_ROOT / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ[key] = val.strip().strip('"').strip("'")

HKT_TZ = __import__('datetime', fromlist=['timezone']).timezone(timedelta(hours=8), name='HKT')

import pandas as pd
from hk_cloud_scanner import (
    fetch_corp_action_announcements,
    hk_code_to_hk_symbol,
    get_daily_history,
    compute_volume_ratio,
    VOLUME_MULTIPLIER,
)
from local_alert_store import store_alert

def main():
    today = datetime.now(HKT_TZ).strftime("%Y-%m-%d")
    print(f"=== Price Jump Follow-up — {today} ===")

    print("[1] Fetching announcements...")
    raw_anns = fetch_corp_action_announcements()
    print(f"Got {len(raw_anns)} total")

    # Filter to past 5 days (T-5 to T-1) with 配股/配售 type
    candidates = []
    today_dt = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=HKT_TZ)
    
    for ann in raw_anns:
        rd = ann.get("release_date")
        if not rd:
            continue
        try:
            ann_dt = datetime.strptime(rd, "%Y-%m-%d").replace(tzinfo=HKT_TZ)
        except ValueError:
            continue
        
        days_ago = (today_dt - ann_dt).days
        if not (1 <= days_ago <= 5):
            continue
        
        types = ann.get("types", [])
        if "配股" not in types and "配售" not in types:
            continue
        
        candidates.append(ann)
    
    print(f"[2] Past 1-5 day placement candidates: {len(candidates)}")
    
    results = []
    for ann in candidates:
        code = ann["code"]
        name = ann["name"]
        types_str = " / ".join(ann["types"])
        ann_date = ann.get("release_date", "")
        title = ann["title"]
        
        print(f"\n[3] Checking {code} {name} | {types_str} | ann={ann_date}")
        
        try:
            df = get_daily_history(code, "3mo")
            if df.empty:
                print(f"  No price data")
                continue
            
            vol_ratio = compute_volume_ratio(df)
            vol_str = f"{vol_ratio:.1f}x" if vol_ratio is not None else "N/A"
            
            ann_dt = datetime.strptime(ann_date, "%Y-%m-%d").replace(tzinfo=HKT_TZ)
            close_on_ann = None
            max_close = None
            max_day = 0
            today_close = None
            
            for _, row in df.iterrows():
                d = row.get("date")
                if d is None:
                    continue
                if isinstance(d, datetime):
                    dt = d.replace(tzinfo=HKT_TZ) if d.tzinfo is None else d
                else:
                    try:
                        dt = pd.Timestamp(d).to_pydatetime().replace(tzinfo=HKT_TZ)
                    except:
                        continue
                
                c = float(row["close"])
                if dt.date() == ann_dt.date():
                    close_on_ann = c
                elif dt.date() == today_dt.date():
                    today_close = c
                
                if dt.date() > ann_dt.date():
                    days = (dt.date() - ann_dt.date()).days
                    if 1 <= days <= 5:
                        pct = (c / close_on_ann - 1) * 100 if close_on_ann else 0
                        if max_close is None or pct > ((max_close / close_on_ann - 1) * 100):
                            max_close = c
                            max_day = days
            
            if close_on_ann and max_close:
                price_jump_pct = round((max_close / close_on_ann - 1) * 100, 1)
                jump_met = price_jump_pct >= 8.0
                vol_met = vol_ratio is not None and vol_ratio >= 1.5
                
                entry = {
                    "code": code,
                    "name": name,
                    "types": ann["types"],
                    "ann_date": ann_date,
                    "days_ago": (today_dt - ann_dt).days,
                    "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
                    "close_on_ann": round(close_on_ann, 3),
                    "max_close_after": round(max_close, 3),
                    "peak_day": max_day,
                    "price_jump_pct": price_jump_pct,
                    "today_close": round(today_close, 3) if today_close else None,
                    "vol_met": vol_met,
                    "jump_met": jump_met,
                    "red": vol_met and jump_met,
                    "title": title,
                    "url": ann.get("url", ""),
                }
                
                print(f"  T+{max_day} jump: {price_jump_pct}% (ann close={close_on_ann:.3f}, peak={max_close:.3f})")
                print(f"  Vol={vol_str} met={vol_met} | Jump met={jump_met} | RED={vol_met and jump_met}")
                
                results.append(entry)
            else:
                print(f"  Insufficient post-ann data (close_on_ann={close_on_ann}, max_close={max_close})")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    reds = [r for r in results if r["red"]]
    watches = [r for r in results if not r["red"]]
    print(f"Past placements checked: {len(results)}")
    print(f"🔴 RED (vol≥1.5x + jump≥8%): {len(reds)}")
    print(f"🟡 WATCH: {len(watches)}")
    
    print("\n__FOLLOWUP_JSON__")
    print(json.dumps({"red": reds, "watch": watches, "summary": {
        "date": today,
        "past_placement_count": len(candidates),
        "red": len(reds),
        "watch": len(watches),
    }}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
