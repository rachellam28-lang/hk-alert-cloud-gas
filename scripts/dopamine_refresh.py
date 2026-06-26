"""
dopamine_refresh.py — Refresh dopamine market state (v5 Futu 100%) → market.json

1. Runs ccass/src/dopamine.py v5 (Futu 港股通 snapshots) to get fresh dopamine
2. Updates market.json with current dopamine, HSI price, and timestamp
3. Merges dopamine.json into market.json for dashboard consumption
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root (where market.json lives)
PROJECT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT / "data"

# ── Step 1: Run v5 Futu dopamine ──
print("[dopamine_refresh] Running v5 Futu dopamine...", file=sys.stderr)
sys.path.insert(0, str(PROJECT / "ccass" / "src"))
try:
    from dopamine import compute_dopamine, save_dopamine
    dopa_result = compute_dopamine()
    dopa_path = save_dopamine(dopa_result)
    print(f"[dopamine_refresh] v5 dopamine={dopa_result['dopamine']:.1f} saved to {dopa_path}", file=sys.stderr)
except Exception as e:
    print(f"[dopamine_refresh] v5 dopamine FAILED: {e}", file=sys.stderr)
    # Fallback: try loading existing dopamine.json
    dopa_result = None
    for f in [PROJECT / "ccass" / "data" / "dopamine.json", PROJECT / "data" / "dopamine.json"]:
        if f.exists():
            with open(f) as fh:
                dopa_result = json.load(fh)
            print(f"[dopamine_refresh] loaded fallback dopamine from {f}", file=sys.stderr)
            break
    if dopa_result is None:
        dopa_result = {"dopamine": 50.0, "level": "normal", "error": str(e)}

# ── Step 2: Load existing market.json ──
market_path = PROJECT / "market.json"
if market_path.exists():
    with open(market_path, encoding="utf-8") as f:
        market = json.load(f)
    print(f"[dopamine_refresh] Loaded existing market.json (updated: {market.get('updated_at','?')})", file=sys.stderr)
else:
    market = {}
    print("[dopamine_refresh] No existing market.json, creating new", file=sys.stderr)

# ── Step 3: Update market.json ──
# Inject dopamine data
market["dopamine"] = {
    "score": dopa_result.get("dopamine", 50.0),
    "level": dopa_result.get("level", "normal"),
    "level_emoji": dopa_result.get("level_emoji", ""),
    "level_desc": dopa_result.get("level_desc", ""),
    "version": dopa_result.get("version", 5),
    "source": dopa_result.get("source", "futu"),
    "updated": datetime.now(timezone.utc).isoformat(),
}
if "components" in dopa_result:
    c = dopa_result["components"]
    market["dopamine"]["breadth_pct"] = c.get("breadth_pct")
    market["dopamine"]["stocks_sampled"] = c.get("stocks_sampled")

# Update timestamp
market["updated_at"] = datetime.now(timezone.utc).isoformat()

# ── Step 4: Save market.json ──
DATA_DIR.mkdir(parents=True, exist_ok=True)
data_market_path = DATA_DIR / "market.json"
for path in (market_path, data_market_path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(market, f, ensure_ascii=False, indent=2)
    print(f"[dopamine_refresh] market.json written -> {path} ({path.stat().st_size} bytes)", file=sys.stderr)

# ── Summary ──
print(json.dumps({
    "dopamine": market.get("dopamine", {}).get("score"),
    "level": market.get("dopamine", {}).get("level"),
    "hsi": market.get("hsi", {}).get("value"),
    "hsi_m2": market.get("hsi_m2", {}).get("value"),
    "updated": market["updated_at"],
}, ensure_ascii=False))
