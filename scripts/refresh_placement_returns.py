#!/usr/bin/env python3
"""Refresh placements_enriched.json with latest raw close-based return fields."""

import glob
import json
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "placements_enriched.json"
RAW_DIR = BASE / "raw"


def load_latest_prices():
    """Load the most recent raw prices snapshot and return {code: (date, close)}."""
    snapshots = sorted(glob.glob(str(RAW_DIR / "prices_*.json")))
    if not snapshots:
        return {}, None

    latest_fp = snapshots[-1]
    m = re.search(r"prices_(\d{4})(\d{2})(\d{2})", os.path.basename(latest_fp))
    snap_date = None
    if m:
        snap_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    with open(latest_fp, encoding="utf-8") as f:
        doc = json.load(f)

    out = {}
    for code, val in doc.items():
        code5 = str(code).zfill(5)
        close = val.get("close", val) if isinstance(val, dict) else val
        try:
            close = float(close)
        except Exception:
            continue
        if close > 0:
            out[code5] = (snap_date, close)
    return out, snap_date


def main():
    if not DATA.exists():
        raise SystemExit(f"missing {DATA}")

    latest_prices, snap_date = load_latest_prices()
    if not latest_prices:
        print("No raw prices snapshot found; nothing to refresh.")
        return

    with open(DATA, encoding="utf-8") as f:
        placements = json.load(f)

    updated = 0
    for p in placements:
        code = str(p.get("code", "")).zfill(5)
        price_num = p.get("price_num") or 0
        info = latest_prices.get(code)
        if not info or price_num <= 0:
            continue
        latest_date, latest_close = info
        p["latest_date"] = latest_date
        p["latest_price"] = latest_close
        p["current_return_pct"] = round((latest_close / price_num - 1) * 100, 1)
        updated += 1

    tmp = DATA.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(placements, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA)
    print(f"Refreshed {updated} placements using raw snapshot {snap_date}")


if __name__ == "__main__":
    main()
