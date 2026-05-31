"""
HK Cloud Scanner - Corp Actions detail dump for Cron Reports.
Fetches today's HKEX corporate action announcements with full detail:
stock names, types, titles, volume ratios, year-open status, stop-loss levels.
No Telegram, no GAS, no charts, no breakthrough export — just the data.

Usage:
    cd /c/Users/Administrator/Desktop/automatic/ccass-debug
    python run_corp_detail.py 2>&1

Output:
    JSON array to stdout (parse with jq or Python json.loads)
    Human-readable progress to stderr

Requirements: dotenv, yfinance, pandas, requests, bs4, matplotlib (in venv)
"""
import sys, os, json

# ── Load .env ──
env_path = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\.env"
if os.path.exists(env_path):
    from dotenv import load_dotenv
    load_dotenv(env_path)
    print(f"[dotenv] loaded {env_path}", file=sys.stderr)

# ── Add scanner dir to path ──
proj = r"C:\Users\Administrator\Desktop\automatic\ccass-debug"
if proj not in sys.path:
    sys.path.insert(0, proj)

# ── Monkey-patch breakthrough exports to skip (saves ~4 min) ──
import scanner.breakthrough_detector as btd
btd.export_breakthroughs_json = lambda: print("[breakthrough] export skipped (cron)", file=sys.stderr)
btd.add_prices_from_announcements = lambda anns: 0

# ── Import scanner ──
os.environ.setdefault("MAX_STOCKS", "0")
os.environ.setdefault("VOLUME_MULTIPLIER", "1.5")
os.environ.setdefault("VOLUME_AVG_DAYS", "20")
os.environ.setdefault("ANNOUNCEMENT_RANGE_DAYS", "7")

from scanner.hk_cloud_scanner import (
    fetch_corp_action_announcements, hkt_today_str, HKT_TZ,
    compute_volume_ratio, format_volume_ratio,
    get_daily_history, get_prev_week_low, sl_yr_line,
    VOLUME_MULTIPLIER, VOLUME_AVG_DAYS,
)
from datetime import datetime

today_hkt = hkt_today_str()
print(f"TODAY: {today_hkt} ({datetime.now(HKT_TZ).strftime('%A')})", file=sys.stderr)

raw_anns = fetch_corp_action_announcements()

# Filter same-day, dedup
anns = []
seen = set()
skipped_old = 0
for ann in raw_anns:
    rd = ann.get("release_date")
    if rd != today_hkt:
        skipped_old += 1
        continue
    key = f"{ann.get('code')}|{ann.get('url')}"
    if key in seen:
        continue
    seen.add(key)
    anns.append(ann)

print(f"RAW: {len(raw_anns)} total, {len(anns)} today, {skipped_old} old", file=sys.stderr)

# Load FVG data for cross-reference
fvg_map = {}
fvg_path = os.path.join(proj, "fvg.json")
if os.path.exists(fvg_path):
    try:
        with open(fvg_path, "r") as f:
            fvg_data = json.load(f)
        for a in fvg_data.get("alerts", []):
            c = str(a.get("code", "")).zfill(5)
            pct = a.get("fvg_pct", a.get("gap_pct", 0))
            if c not in fvg_map:
                fvg_map[c] = pct
    except Exception:
        pass

def compute_gap(df):
    """Compute today's gap: (today_open - prev_close) / prev_close * 100"""
    if df is None or df.empty or len(df) < 2:
        return None
    prev_close = float(df.iloc[-2]["close"])
    today_open = float(df.iloc[-1]["open"])
    if prev_close == 0:
        return None
    return round((today_open - prev_close) / prev_close * 100, 2)

# Compute volume ratios for each
results = []
for ann in anns:
    code = ann["code"]
    name = ann["name"]
    types_list = ann["types"]
    title_cn = ann["title"]
    release_time = ann.get("release_time", "")

    df = get_daily_history(code, "1y")
    vol_ratio = compute_volume_ratio(df) if not df.empty else None
    pw_low = get_prev_week_low(df) if not df.empty else None
    cur_price = float(df.iloc[-1]["close"]) if not df.empty else 0.0
    sl = sl_yr_line(pw_low, cur_price, df) if not df.empty else ""
    gap_pct = compute_gap(df) if not df.empty else None
    fvg_pct = fvg_map.get(code)

    results.append({
        "code": code,
        "name": name,
        "types": types_list,
        "title_cn": title_cn,
        "title_en": ann.get("title_en", ""),
        "release_time": release_time,
        "vol_ratio": vol_ratio,
        "sl_yr_line": sl,
        "gap_pct": gap_pct,
        "fvg_pct": fvg_pct,
        "url": ann.get("url", ""),
    })

    extras = []
    if gap_pct is not None:
        extras.append(f"gap={gap_pct:+.1f}%")
    if fvg_pct is not None:
        extras.append(f"fvg={fvg_pct:.1f}%")
    extra_str = f" | {' '.join(extras)}" if extras else ""
    print(f"[corp] {code} | {name} | {' / '.join(types_list)} | vol={vol_ratio}x | {sl}{extra_str}", file=sys.stderr)

# Print JSON for parsing by calling script
print(json.dumps(results, ensure_ascii=False, indent=2))
