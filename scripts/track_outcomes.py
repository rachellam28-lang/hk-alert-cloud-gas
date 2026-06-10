# -*- coding: utf-8 -*-
"""
track_outcomes.py — Daily forward return backfill using git-derived raw/ price data.
Format B: raw/prices_YYYYMMDD.json → {code: {close, vol, hi52, lo52} | float}
Supports both legacy (flat price) and new (dict) formats.

Usage:
    python scripts/track_outcomes.py
    python scripts/track_outcomes.py --report
"""

import argparse
import glob
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATHS = {
    "events":    os.path.join(BASE, "events.json"),
    "raw":       os.path.join(BASE, "raw"),
    "holdings":  os.path.join(BASE, "holdings.json"),
}

MC_BUCKETS = [(20, "nano"), (100, "micro"), (500, "small"), (2000, "mid"), (float("inf"), "large")]


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def mc_bucket(mc):
    if mc is None:
        return None
    for ceil, name in MC_BUCKETS:
        if mc < ceil:
            return name
    return "large"


def load_price_history():
    """raw/prices_YYYYMMDD.json → {code: {date: close}}.
    Handles both legacy flat format (code→price) and new dict format (code→{close,...})."""
    hist = defaultdict(dict)
    all_dates = []
    
    for fp in sorted(glob.glob(os.path.join(PATHS["raw"], "prices_*.json"))):
        fname = os.path.basename(fp)
        date = f"{fname[7:11]}-{fname[11:13]}-{fname[13:15]}"
        try:
            day = load_json(fp, default={})
            if not day:
                continue
            all_dates.append(date)
            for code, val in day.items():
                code5 = str(code).zfill(5)
                if isinstance(val, dict):
                    px = val.get("close") or val.get("lp")
                else:
                    px = val
                if px is not None and float(px) > 0.0001:
                    hist[code5][date] = float(px)
        except Exception:
            continue
    
    return hist, all_dates


def backfill(events, holdings):
    """Fill entry_price + mc_bucket, then compute forward returns from raw/ price history."""
    hist, all_dates = load_price_history()
    
    mc_by_code = {}
    for s in (holdings or {}).get("stocks", []):
        mc_by_code[str(s.get("c", "")).zfill(5)] = s.get("mc")

    filled = 0
    today = datetime.now().strftime("%Y-%m-%d")

    for e in events:
        o = e["outcome"]
        code = e["code"]
        pxs = hist.get(code, {})

        # entry_price
        if o.get("entry_price") is None:
            px = e.get("price_at_alert") or pxs.get(e.get("alert_date", ""))
            if px:
                o["entry_price"] = float(px)
                filled += 1

        # mc_bucket
        if o.get("mc_bucket") is None:
            mc = mc_by_code.get(code)
            if mc is not None:
                o["mc_bucket"] = mc_bucket(mc)
                filled += 1

        # Forward returns — using raw/ date files
        entry = o.get("entry_price")
        t0 = e.get("alert_date", "")
        if not entry or not t0 or t0 not in all_dates:
            continue

        try:
            idx0 = all_dates.index(t0)
        except ValueError:
            continue

        for horizon_days, field in [(5, "fwd_5d"), (20, "fwd_20d"), (60, "fwd_60d")]:
            if o.get(field) is not None:
                continue
            tgt_idx = idx0 + horizon_days
            if tgt_idx >= len(all_dates):
                continue
            tgt_date = all_dates[tgt_idx]
            tgt_px = pxs.get(tgt_date)
            if tgt_px is None:
                # Stock missing on that date → suspended
                o["suspended"] = True
                filled += 1
                continue
            if tgt_px > 0.0001 and entry > 0.0001:
                o[field] = round(tgt_px / entry - 1, 4)
                filled += 1

        # max_gain_20d / max_dd_20d
        if o.get("max_gain_20d") is None and o.get("fwd_20d") is not None:
            window_prices = []
            for offset in range(1, 21):
                tgt_idx = idx0 + offset
                if tgt_idx >= len(all_dates):
                    break
                tgt_px = pxs.get(all_dates[tgt_idx])
                if tgt_px is not None and tgt_px > 0.0001:
                    window_prices.append(tgt_px)
            if window_prices and entry > 0.0001:
                o["max_gain_20d"] = round(max(window_prices) / entry - 1, 4)
                o["max_dd_20d"] = round(min(window_prices) / entry - 1, 4)
                filled += 1

        o["filled_at"] = today

    print(f"  backfilled: {filled} fields, hist dates: {len(all_dates)}")
    return events


def report(events):
    groups = {}
    for e in events:
        o = e["outcome"]
        key = (e["signal_type"], o.get("mc_bucket") or "?")
        groups.setdefault(key, []).append(e)

    rows = []
    for (stype, bucket), es in sorted(groups.items()):
        n = len(es)
        f20 = [e["outcome"]["fwd_20d"] for e in es if e["outcome"].get("fwd_20d") is not None]
        dds = [e["outcome"]["max_dd_20d"] for e in es if e["outcome"].get("max_dd_20d") is not None]
        rows.append({
            "signal": stype, "bucket": bucket, "n": n,
            "fwd20_done": len(f20),
            "med_fwd20": round(statistics.median(f20) * 100, 1) if f20 else None,
            "med_maxdd": round(statistics.median(dds) * 100, 1) if dds else None,
            "verdict": "未夠數" if n < 30 else ("" if f20 else "pending"),
        })

    if not rows:
        print("  (no events with outcomes)")
        return

    hdr = f"{'signal':<18}{'bucket':<8}{'n':>5}{'done':>6}{'fwd20%':>8}{'maxDD%':>8}  note"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['signal']:<18}{r['bucket']:<8}{r['n']:>5}{r['fwd20_done']:>6}"
              f"{str(r['med_fwd20']):>8}{str(r['med_maxdd']):>8}  {r['verdict']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    events = load_json(PATHS["events"], default=[])
    if isinstance(events, dict):
        events = events.get("events", [])

    if not events:
        print("events.json empty — run build_signals.py first")
        return 1 if not args.report else 0

    holdings = load_json(PATHS["holdings"], default={})

    print(f"Processing {len(events)} events...")
    events = backfill(events, holdings)
    atomic_write(PATHS["events"], events)
    print(f"✅ written: {PATHS['events']}")

    if args.report:
        print()
        report(events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
