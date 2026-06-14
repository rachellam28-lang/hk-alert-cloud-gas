"""Merge market-cap caches from Futu / Longbridge.

This script is intentionally cache-only. The daily runner must never block
on market-cap fetches, and we rely on Futu / Longbridge caches for this field.

Inputs:
  - ccass/cache/market_caps.json              (Futu cache format)
  - ccass/data/market_caps.json               (Longbridge output format)

Output:
  - ccass/cache/market_caps.json              (Futu-style cache format)
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "cache" / "market_caps.json"
LB_PATH = PROJECT_ROOT / "data" / "market_caps.json"


def _load_cache_map() -> dict[str, float | None]:
    cache: dict[str, float | None] = {}
    if CACHE_PATH.exists():
        try:
            raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    code = str(item.get("stock_code", "")).zfill(5)
                    cache[code] = item.get("market_cap")
            elif isinstance(raw, dict):
                for k, v in raw.items():
                    cache[str(k).zfill(5)] = v
        except Exception:
            pass
    return cache


def _merge_longbridge(cache: dict[str, float | None]) -> int:
    if not LB_PATH.exists():
        return 0
    try:
        raw = json.loads(LB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0

    updated = 0
    if isinstance(raw, dict):
        for sym, info in raw.items():
            code = str(sym).replace(".HK", "").zfill(5)
            mc_hkd = info.get("market_cap_hkd") if isinstance(info, dict) else None
            mc = round(float(mc_hkd) / 1e8, 2) if mc_hkd else None
            if cache.get(code) != mc:
                cache[code] = mc
                updated += 1
    return updated


def main() -> int:
    cache = _load_cache_map()
    merged = _merge_longbridge(cache)

    rows = [{"stock_code": k, "market_cap": v} for k, v in sorted(cache.items())]
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    non_null = sum(1 for v in cache.values() if v is not None)
    print(f"Saved {len(rows)} cache rows to {CACHE_PATH}")
    print(f"Non-null market caps: {non_null}")
    print(f"Updated from Longbridge: {merged}")
    print("Note: daily runner uses cache-only market caps; refresh via Futu/Longbridge scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
