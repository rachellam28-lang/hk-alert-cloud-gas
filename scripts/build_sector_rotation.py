"""Build an observed HK sector rotation snapshot from real closing prices.

The output is an RRG-style proxy, not a vendor RRG clone.  Each sector is an
equal-weight basket of observed stocks and is compared with the equal-weight
market basket.  Missing prices are excluded and unavailable horizons stay
null.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
OUT = ROOT / "data" / "sector_rotation.json"
MIN_FRESH_ROWS = 500
TAIL_POINTS = 6

SECTOR_LABELS = {
    "tech": "科技／AI",
    "healthcare": "醫藥",
    "property": "地產／物管",
    "finance": "金融／券商",
    "energy": "能源／資源",
    "auto": "汽車／新能源",
    "consumer": "消費／餐飲",
    "infra": "電訊／基建",
    "shipping": "航運物流",
    "industrial": "工業／製造",
    "conglomerate": "綜合／控股",
    "other": "其他／未分類",
}

SECTOR_KEYWORDS = {
    "tech": ("科技", "軟件", "數據", "智能", "AI", "晶片", "芯片", "電子", "網絡", "互聯網"),
    "healthcare": ("醫藥", "醫療", "生物", "製藥", "健康", "醫院", "牙科"),
    "property": ("地產", "置業", "物業", "房託", "房地產", "REIT"),
    "finance": ("銀行", "金融", "保險", "證券", "資產管理", "信託", "基金", "期貨"),
    "energy": ("能源", "石油", "煤炭", "燃氣", "電力", "礦", "黃金", "資源", "光伏"),
    "auto": ("汽車", "新能源車", "電池", "車業"),
    "consumer": ("消費", "零售", "食品", "餐飲", "旅遊", "酒店", "服裝", "教育", "娛樂"),
    "infra": ("電訊", "通信", "移動", "基建", "公路", "水務", "環保", "公用"),
    "shipping": ("航運", "物流", "港口", "航空", "貨運", "海運"),
    "industrial": ("工業", "製造", "機械", "工程", "建材", "水泥", "化工", "材料"),
    "conglomerate": ("控股", "綜合企業"),
}

PROFILES = {
    "20": {"label": "20日", "short_days": 5, "long_days": 20},
    "60": {"label": "60日", "short_days": 20, "long_days": 60},
    "120": {"label": "120日", "short_days": 60, "long_days": 120},
}


def parse_main_page_code_map() -> dict[str, str]:
    """Reuse the dashboard's existing explicit classification overrides."""
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const\s+SECTOR_CODE_MAP\s*=\s*\{(.*?)\};", text, re.S)
    if not match:
        return {}
    return {
        code.zfill(5): sector
        for code, sector in re.findall(r"['\"](\d{5})['\"]\s*:\s*['\"]([a-z_]+)['\"]", match.group(1))
        if sector in SECTOR_LABELS
    }


def classify(code: str, name: str, code_map: dict[str, str]) -> str:
    if code in code_map:
        return code_map[code]
    folded = name.upper()
    for key, words in SECTOR_KEYWORDS.items():
        if any(word.upper() in folded for word in words):
            return key
    return "other"


def observed_close(value, snapshot_day: date) -> float | None:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if not isinstance(value, dict):
        return None
    source_date = str(value.get("source_date") or "")[:10]
    if value.get("stale") is True or (source_date and source_date != snapshot_day.isoformat()):
        return None
    price = value.get("close")
    return float(price) if isinstance(price, (int, float)) and price > 0 else None


def load_snapshots() -> dict[date, dict[str, float]]:
    snapshots: dict[date, dict[str, float]] = {}
    for path in sorted(RAW.glob("prices_*.json")):
        match = re.search(r"prices_(\d{8})\.json$", path.name)
        if not match:
            continue
        stamp = match.group(1)
        day = date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        cleaned = {
            str(code).zfill(5): price
            for code, value in raw.items()
            if (price := observed_close(value, day)) is not None
        }
        if len(cleaned) >= MIN_FRESH_ROWS:
            snapshots[day] = cleaned
    return snapshots


def nearest_reference(as_of: date, snapshots: dict[date, dict[str, float]], days: int) -> date | None:
    target = as_of - timedelta(days=days)
    candidates = [day for day in snapshots if day < as_of]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda day: abs((day - target).days))
    tolerance = 10 if days <= 20 else 16
    return chosen if abs((chosen - target).days) <= tolerance else None


def relative_pct(basket_pct: float | None, market_pct: float | None) -> float | None:
    if basket_pct is None or market_pct is None or market_pct <= -100:
        return None
    return ((1 + basket_pct / 100) / (1 + market_pct / 100) - 1) * 100


def rounded(value: float | None) -> float | None:
    return round(value, 3) if isinstance(value, (int, float)) else None


def point_for(
    as_of: date,
    snapshots: dict[date, dict[str, float]],
    names: dict[str, str],
    classifications: dict[str, str],
    short_days: int,
    long_days: int,
) -> dict | None:
    short_ref = nearest_reference(as_of, snapshots, short_days)
    long_ref = nearest_reference(as_of, snapshots, long_days)
    if short_ref is None or long_ref is None:
        return None

    current = snapshots[as_of]
    short_prices = snapshots[short_ref]
    long_prices = snapshots[long_ref]
    short_market: list[float] = []
    long_market: list[float] = []
    short_buckets = {key: [] for key in SECTOR_LABELS}
    long_buckets = {key: [] for key in SECTOR_LABELS}
    member_returns = {key: [] for key in SECTOR_LABELS}

    for code, price in current.items():
        if code not in names:
            continue
        sector = classifications.get(code, "other")
        old_short = short_prices.get(code)
        old_long = long_prices.get(code)
        if old_short and old_short > 0:
            value = (price / old_short - 1) * 100
            short_market.append(value)
            short_buckets[sector].append(value)
        if old_long and old_long > 0:
            value = (price / old_long - 1) * 100
            long_market.append(value)
            long_buckets[sector].append(value)
            member_returns[sector].append((value, code, names[code]))

    if not short_market or not long_market:
        return None
    market_short = statistics.median(short_market)
    market_long = statistics.median(long_market)
    sectors = {}
    for key in SECTOR_LABELS:
        short_values = short_buckets[key]
        long_values = long_buckets[key]
        sector_short = statistics.median(short_values) if short_values else None
        sector_long = statistics.median(long_values) if long_values else None
        rel_short = relative_pct(sector_short, market_short)
        rel_long = relative_pct(sector_long, market_long)
        ranked = sorted(member_returns[key], reverse=True)[:3]
        sectors[key] = {
            "rs_ratio": rounded(100 + rel_long) if rel_long is not None else None,
            "rs_momentum": rounded(100 + rel_short) if rel_short is not None else None,
            "relative_long_pct": rounded(rel_long),
            "relative_short_pct": rounded(rel_short),
            "sector_long_pct": rounded(sector_long),
            "sector_short_pct": rounded(sector_short),
            "market_long_pct": rounded(market_long),
            "market_short_pct": rounded(market_short),
            "stocks": min(len(short_values), len(long_values)),
            "leaders": [
                {"code": code, "name": name, "return_pct": rounded(value)}
                for value, code, name in ranked
            ],
        }
    return {
        "as_of": as_of.isoformat(),
        "short_reference_date": short_ref.isoformat(),
        "long_reference_date": long_ref.isoformat(),
        "market_stocks": min(len(short_market), len(long_market)),
        "sectors": sectors,
    }


def quadrant(rs_ratio: float | None, rs_momentum: float | None) -> str:
    if rs_ratio is None or rs_momentum is None:
        return "unavailable"
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "leading"
    if rs_ratio < 100 and rs_momentum < 100:
        return "lagging"
    return "improving" if rs_momentum >= 100 else "weakening"


def main() -> None:
    snapshots = load_snapshots()
    if not snapshots:
        raise SystemExit(f"No price snapshot has at least {MIN_FRESH_ROWS} same-date observed rows")
    latest = max(snapshots)
    holdings = json.loads((ROOT / "holdings.json").read_text(encoding="utf-8"))
    names = {
        str(row.get("c", "")).zfill(5): str(row.get("n", "")).strip()
        for row in holdings.get("stocks", [])
        if row.get("c") and row.get("n")
    }
    code_map = parse_main_page_code_map()
    classifications = {code: classify(code, name, code_map) for code, name in names.items()}
    current_codes = set(snapshots[latest]) & set(names)
    counts = {key: 0 for key in SECTOR_LABELS}
    for code in current_codes:
        counts[classifications.get(code, "other")] += 1

    profiles = {}
    days = sorted(snapshots)
    for key, config in PROFILES.items():
        available = []
        for as_of in reversed(days):
            point = point_for(
                as_of,
                snapshots,
                names,
                classifications,
                config["short_days"],
                config["long_days"],
            )
            if point:
                available.append(point)
            if len(available) >= TAIL_POINTS:
                break
        available.reverse()
        latest_point = available[-1] if available else None
        sectors = {}
        for sector_key, label in SECTOR_LABELS.items():
            item = dict((latest_point or {}).get("sectors", {}).get(sector_key, {}))
            item.update({
                "label": label,
                "count": counts[sector_key],
                "quadrant": quadrant(item.get("rs_ratio"), item.get("rs_momentum")),
                "tail": [
                    {
                        "as_of": point["as_of"],
                        "rs_ratio": point["sectors"][sector_key]["rs_ratio"],
                        "rs_momentum": point["sectors"][sector_key]["rs_momentum"],
                    }
                    for point in available
                    if point["sectors"][sector_key]["rs_ratio"] is not None
                    and point["sectors"][sector_key]["rs_momentum"] is not None
                ],
            })
            sectors[sector_key] = item
        profiles[key] = {
            **config,
            "available": latest_point is not None,
            "as_of": latest_point.get("as_of") if latest_point else latest.isoformat(),
            "short_reference_date": latest_point.get("short_reference_date") if latest_point else None,
            "long_reference_date": latest_point.get("long_reference_date") if latest_point else None,
            "market_stocks": latest_point.get("market_stocks") if latest_point else 0,
            "sectors": sectors,
        }

    classified = len(current_codes) - counts["other"]
    windows = {}
    profile_refs = {
        "5": profiles["20"].get("short_reference_date"),
        "20": profiles["20"].get("long_reference_date"),
        "60": profiles["60"].get("long_reference_date"),
        "120": profiles["120"].get("long_reference_date"),
    }
    for days, reference in profile_refs.items():
        reference_day = date.fromisoformat(reference) if reference else None
        windows[days] = {
            "latest_date": latest.isoformat(),
            "latest_rows": len(snapshots[latest]),
            "reference_date": reference,
            "reference_rows": len(snapshots[reference_day]) if reference_day else None,
        }
    out = {
        "schema_version": 2,
        "updated": latest.isoformat(),
        "source": "raw/prices_YYYYMMDD.json + holdings.json names + index.html classification overrides",
        "method": (
            "RRG-style proxy using same-date non-stale closes: sector equal-weight median return relative to the equal-weight market median; "
            "RS-Ratio=100+long relative return; RS-Momentum=100+short relative return"
        ),
        "is_vendor_rrg": False,
        "minimum_fresh_rows": MIN_FRESH_ROWS,
        "coverage": {
            "observed_named_stocks": len(current_codes),
            "classified_stocks": classified,
            "unclassified_stocks": counts["other"],
            "classified_pct": rounded(classified / len(current_codes) * 100) if current_codes else None,
        },
        "windows": windows,
        "profiles": profiles,
        "sectors": {
            key: {"name": label, "count": counts[key]}
            for key, label in SECTOR_LABELS.items()
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(SECTOR_LABELS)} sectors, latest={latest}, classified={classified}/{len(current_codes)})")


if __name__ == "__main__":
    main()
