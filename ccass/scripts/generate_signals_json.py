"""
Generate data/signals.json from scanner data as GAS fallback.
Combines corp actions, FVG, breakthroughs into GAS-compatible format.

Output format matches GAS ?format=json response:
  {ok: true, groups: [{code, name, signals: [], corpTypes: {placement, rights, increase}, hkexLink, latestPrice}], recentCorps: []}

Data sources:
  - scanner/corp_scan_result.json → corpTypes (placement/rights/increase)
  - fvg.json → FVG signals  
  - data/breakthroughs.json → breakout/ipo/POC signals
  - data/prices.json → stock codes, names, latest prices

Usage:
  python scripts/generate_signals_json.py
"""
import json
from pathlib import Path
from datetime import datetime

PROJECT = Path(__file__).parent.parent  # holdings/
ROOT = PROJECT.parent                    # holdings-debug/
DATA = ROOT / "data"
SCANNER = ROOT / "scanner"
OUT = DATA / "signals.json"
PRICES_JSON = DATA / "prices.json"
CORP_SCAN = SCANNER / "corp_scan_result.json"
FVG_JSON = ROOT / "fvg.json"
BT_JSON = DATA / "breakthroughs.json"


def load_json(path):
    """Load a JSON file, return {} or [] on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if path.suffix == ".json" else []


def map_corp_types(types_list):
    """Map Chinese corp action types to GAS corpTypes booleans."""
    ct = {"placement": False, "rights": False, "increase": False}
    for t in types_list:
        t = t.strip()
        if t == "配股":
            ct["placement"] = True
        elif t == "供股":
            ct["rights"] = True
        elif t == "股東增持":
            ct["increase"] = True
    return ct


def map_signals(types_list):
    """Map corp action types to signal tags (POC-like labels)."""
    signals = []
    type_map = {
        "配股": "placement",
        "供股": "rights",
        "股東增持": "increase",
        "大手轉倉": "block_trade",
    }
    for t in types_list:
        tag = type_map.get(t.strip())
        if tag and tag not in signals:
            signals.append(tag)
    return signals


def generate():
    # 1. Load base prices/names from prices.json (always available)
    prices_data = load_json(PRICES_JSON)
    price_groups = prices_data.get("groups", []) if isinstance(prices_data, dict) else []

    if not price_groups:
        print("ERROR: prices.json not found or empty — cannot generate signals.json")
        return

    # Build lookup: code → {name, latestPrice}
    stock_info = {}
    for g in price_groups:
        code = str(g.get("code", "")).strip()
        stock_info[code] = {
            "name": g.get("name", ""),
            "latestPrice": g.get("latestPrice"),
        }

    # 2. Load corp scan results → corpTypes + signals
    corp_data = load_json(CORP_SCAN)
    alerted = corp_data.get("alerted", []) if isinstance(corp_data, dict) else []
    watchlisted = corp_data.get("watchlisted", []) if isinstance(corp_data, dict) else []
    all_corps = alerted + watchlisted

    # Build corpTypes and signals per code from scanner data
    corp_types_map = {}  # code → corpTypes dict
    signals_map = {}     # code → list of signal strings
    hkex_link_map = {}   # code → hkexLink URL

    for item in all_corps:
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        types_list = item.get("types_list", [])
        if not types_list and item.get("types"):
            types_list = [item["types"]]

        # Merge corpTypes (OR logic: once True, stays True)
        if code not in corp_types_map:
            corp_types_map[code] = {"placement": False, "rights": False, "increase": False}
        item_ct = map_corp_types(types_list)
        for k in ("placement", "rights", "increase"):
            if item_ct[k]:
                corp_types_map[code][k] = True

        # Merge signals (deduplicated)
        if code not in signals_map:
            signals_map[code] = []
        for sig in map_signals(types_list):
            if sig not in signals_map[code]:
                signals_map[code].append(sig)

        # hkexLink: prefer the announcement URL
        url = item.get("url", "")
        if url and code not in hkex_link_map:
            hkex_link_map[code] = url

    # 3. Load FVG signals
    fvg_data = load_json(FVG_JSON)
    fvg_alerts = fvg_data.get("alerts", []) if isinstance(fvg_data, dict) else []

    for alert in fvg_alerts:
        ticker = alert.get("ticker", "")  # e.g. "0941.HK"
        if not ticker or ".HK" not in ticker.upper():
            continue
        # Extract code: "0941.HK" → "00941"
        raw_code = ticker.upper().replace(".HK", "")
        code = raw_code.zfill(5)
        if code not in signals_map:
            signals_map[code] = []
        if "FVG" not in signals_map[code]:
            signals_map[code].append("FVG")

    # 4. Load breakthrough signals
    bt_data = load_json(BT_JSON)
    breakthroughs = bt_data.get("breakthroughs", []) if isinstance(bt_data, dict) else []

    for bt in breakthroughs:
        code = str(bt.get("stock_code", bt.get("code", ""))).strip()
        if not code:
            continue
        bt_type = bt.get("type", "").lower()
        tag = None
        if bt_type == "ipo":
            tag = "ipo"
        elif bt_type in ("poc", "breakout"):
            tag = "breakout"
        if tag:
            if code not in signals_map:
                signals_map[code] = []
            if tag not in signals_map[code]:
                signals_map[code].append(tag)

    # 5. Build output groups
    groups = []
    for code, info in stock_info.items():
        ct = corp_types_map.get(code, {"placement": False, "rights": False, "increase": False})
        sigs = signals_map.get(code, [])
        hk_link = hkex_link_map.get(code, "")

        groups.append({
            "code": code,
            "name": info.get("name", ""),
            "latestPrice": info.get("latestPrice"),
            "signals": sigs,
            "corpTypes": ct,
            "hkexLink": hk_link,
        })

    # Build recentCorps from alerted items
    recent_corps = []
    for item in alerted:
        recent_corps.append({
            "code": str(item.get("code", "")).strip(),
            "name": item.get("name", ""),
            "types": item.get("types", ""),
            "url": item.get("url", ""),
            "release_time": item.get("release_time", ""),
        })

    output = {
        "ok": True,
        "groups": groups,
        "recentCorps": recent_corps,
        "updatedAt": datetime.now().isoformat(),
        "source": "scanner + fvg + breakthroughs (GAS fallback)",
        "totalStocks": len(groups),
        "totalWithSignals": sum(1 for g in groups if g["signals"]),
        "totalWithCorpTypes": sum(1 for g in groups if any(g["corpTypes"].values())),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")

    print(f"Generated {OUT}")
    print(f"  {len(groups)} stocks total")
    print(f"  {output['totalWithSignals']} with signals")
    print(f"  {output['totalWithCorpTypes']} with corp action types")
    print(f"  {len(recent_corps)} recent corps")
    print(f"  File size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    generate()
