"""Build a compact HK sector rotation snapshot from real daily price files."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
OUT = ROOT / "data" / "sector_rotation.json"

SECTORS = {
    "tech": ["科技", "軟件", "芯", "智能", "AI", "電子", "電訊"],
    "finance": ["銀行", "金融", "保險", "證券", "資產管理", "信託"],
    "property": ["地產", "物業", "建設"],
    "energy": ["能源", "石油", "煤炭", "燃氣", "電力", "資源"],
    "consumer": ["消費", "零售", "食品", "餐飲", "汽車", "服裝", "旅遊", "酒店", "教育", "醫藥", "生物"],
    "industrial": ["工業", "製造", "機械", "材料", "物流", "航空", "航運"],
    "utilities": ["公用", "基建", "環保", "水務"],
}


def sector(name: str) -> str:
    for key, words in SECTORS.items():
        if any(word in name for word in words):
            return key
    return "other"


def close(value):
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, dict):
        value = value.get("close")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def load_snapshots():
    snapshots = {}
    for path in sorted(RAW.glob("prices_*.json")):
        match = re.search(r"prices_(\d{8})\.json$", path.name)
        if not match:
            continue
        day = date.fromisoformat(match.group(1)[:4] + "-" + match.group(1)[4:6] + "-" + match.group(1)[6:])
        raw = json.loads(path.read_text(encoding="utf-8"))
        snapshots[day] = {str(code).zfill(5): close(value) for code, value in raw.items()}
    return snapshots


def nearest_reference(latest: date, snapshots: dict[date, dict], days: int):
    target = latest - timedelta(days=days)
    candidates = [d for d in snapshots if d < latest]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda d: abs((d - target).days))
    return chosen if abs((chosen - target).days) <= (10 if days <= 20 else 14) else None


def main():
    snapshots = load_snapshots()
    latest = max(snapshots)
    holdings = json.loads((ROOT / "holdings.json").read_text(encoding="utf-8"))
    names = {str(row.get("c", "")).zfill(5): str(row.get("n", "")) for row in holdings.get("stocks", [])}
    windows = {}
    for days in (5, 20, 60, 120):
        ref = nearest_reference(latest, snapshots, days)
        windows[str(days)] = {"latest_date": latest.isoformat(), "reference_date": ref.isoformat() if ref else None}

    sectors = {key: {"name": key, "count": 0, "windows": {}} for key in [*SECTORS, "other"]}
    for key, item in sectors.items():
        item["name"] = {**{k: k for k in SECTORS}, "other": "other"}[key]

    for days, meta in windows.items():
        ref_date = date.fromisoformat(meta["reference_date"]) if meta["reference_date"] else None
        if not ref_date:
            continue
        current = snapshots[latest]
        baseline = snapshots[ref_date]
        buckets = {key: [] for key in sectors}
        for code, price in current.items():
            old = baseline.get(code)
            name = names.get(code, "")
            if price is None or old is None or old <= 0 or not name:
                continue
            buckets[sector(name)].append((price / old - 1.0) * 100.0)
        for key, values in buckets.items():
            sectors[key]["windows"][days] = {
                "pct": round(sum(values) / len(values), 2) if values else None,
                "stocks": len(values),
                "reference_date": meta["reference_date"],
                "latest_date": meta["latest_date"],
            }

    out = {
        "updated": latest.isoformat(),
        "source": "raw/prices_YYYYMMDD.json + holdings.json names",
        "method": "equal-weight mean price return; missing prices excluded",
        "windows": windows,
        "sectors": sectors,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(sectors)} sectors, latest={latest})")


if __name__ == "__main__":
    main()
