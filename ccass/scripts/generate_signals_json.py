"""
Generate data/signals.json from scanner data as GAS fallback.
Combines corp actions, FVG, breakthroughs into GAS-compatible format.

Output format matches GAS ?format=json response:
  {ok: true, groups: [{code, name, signals: [], corpTypes: {placement, rights, increase}, hkexLink, latestPrice}], recentCorps: []}

Data sources:
  - data/announcements.json → corpTypes (534 entries, 90-day window)
  - scanner/corp_scan_result.json → alerted/watched signals + recentCorps
  - fvg.json → FVG signals  
  - data/breakthroughs.json → breakout/ipo/POC signals
  - data/stock_prices.json → stock codes, names, latest prices (primary)
  - data/prices.json → fallback only

Usage:
  python scripts/generate_signals_json.py
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

PROJECT = Path(__file__).parent.parent  # ccass/
ROOT = PROJECT.parent                    # ccass-debug/
DATA = ROOT / "data"
SCANNER = ROOT / "scanner"
OUT = DATA / "signals.json"
STOCK_PRICES_JSON = DATA / "stock_prices.json"
PRICES_JSON = DATA / "prices.json"
CORP_SCAN = SCANNER / "corp_scan_result.json"
FVG_JSON = ROOT / "fvg.json"
BT_JSON = DATA / "breakthroughs.json"
ANNOUNCEMENTS_JSON = DATA / "announcements.json"

# How far back to consider corp actions "active" for corpTypes
CORP_WINDOW_DAYS = 90


def atomic_write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

TYPE_MAP = {
    'placement': 'placement', '配售': 'placement', 'placing': 'placement',
    'rights': 'rights', '供股': 'rights', 'rights issue': 'rights',
    'increase': 'increase', '增持': 'increase', '股東增持': 'increase',
}


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


def build_corp_types_from_announcements(window_days=CORP_WINDOW_DAYS):
    """Build corpTypes map from data/announcements.json (full history, not just alerts).
    
    Returns dict: code -> {placement: {date, link, count}|False, rights: ..., increase: ...}
    """
    data = load_json(ANNOUNCEMENTS_JSON)
    if isinstance(data, dict):
        anns = data.get('announcements') or data.get('items') or []
    else:
        anns = data if isinstance(data, list) else []

    if not anns:
        print("WARNING: announcements.json empty or missing — corpTypes will be sparse")
        return {}

    cutoff = datetime.now() - timedelta(days=window_days)
    corp_map = {}  # code -> {placement: {date, link, count}|False, ...}

    for a in anns:
        code = str(a.get('code', '')).zfill(5)
        if not code or len(code) > 6:
            continue

        # Handle multiple date formats
        raw_date = a.get('date') or a.get('release_time', '')[:10]
        dt = None
        for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(raw_date.strip()[:10], fmt)
                break
            except (ValueError, AttributeError):
                continue
        if not dt or dt < cutoff:
            continue

        # Match type from types list or title text
        types_list = a.get('types', [])
        if isinstance(types_list, str):
            types_list = [types_list]
        text = ' '.join(types_list).lower() + ' ' + (a.get('title', '') or '').lower()

        matched_types = set()
        for kw, ctype in TYPE_MAP.items():
            if kw in text:
                matched_types.add(ctype)

        if not matched_types:
            continue

        date_str = dt.strftime('%Y-%m-%d')
        if code not in corp_map:
            corp_map[code] = {}
        for ctype in matched_types:
            cur = corp_map[code].get(ctype)
            if not cur or date_str > cur['date']:
                corp_map[code][ctype] = {
                    'date': date_str,
                    'link': a.get('url', ''),
                    'count': 1,
                }
            else:
                cur['count'] += 1

    return corp_map


def load_stock_prices():
    """Prefer stock_prices.json (fresh Futu/Longbridge cache), fallback to prices.json."""
    for path in (STOCK_PRICES_JSON, PRICES_JSON):
        data = load_json(path)
        if not isinstance(data, dict) or not data:
            continue

        # stock_prices.json schema: {code: {lp, ...}}
        sample_key = next(iter(data), None)
        if sample_key and isinstance(data.get(sample_key), dict) and ("lp" in data[sample_key] or "latestPrice" in data[sample_key]):
            return path, data

        # prices.json schema: {ok, groups:[{code,name,latestPrice}]}
        groups = data.get("groups", [])
        if groups:
            stock_info = {}
            for g in groups:
                code = str(g.get("code", "")).strip()
                stock_info[code] = {
                    "name": g.get("name", ""),
                    "latestPrice": g.get("latestPrice"),
                }
            return path, stock_info

    return None, {}


def generate():
    # 1. Load base prices/names from stock_prices.json first
    source_path, raw_prices = load_stock_prices()
    if not raw_prices:
        print("ERROR: no usable price source found — cannot generate signals.json")
        return

    # Build lookup: code → {name, latestPrice}
    stock_info = {}
    if source_path == STOCK_PRICES_JSON:
        names = {}
        try:
            # If available, use prices.json names as a fallback naming map
            prices_data = load_json(PRICES_JSON)
            if isinstance(prices_data, dict):
                for g in prices_data.get("groups", []) or []:
                    code = str(g.get("code", "")).strip()
                    if code:
                        names[code] = g.get("name", "")
        except Exception:
            pass
        for code, entry in raw_prices.items():
            if not isinstance(entry, dict):
                continue
            lp = entry.get("lp", entry.get("latestPrice"))
            if lp is None:
                continue
            stock_info[str(code).strip()] = {
                "name": names.get(str(code).strip(), ""),
                "latestPrice": lp,
            }
    else:
        stock_info = raw_prices

    # === CORP TYPES: from announcements.json (full history, 90-day window) ===
    corp_map = build_corp_types_from_announcements()
    
    # Build simplified corpTypes for output (frontend expects booleans or objects)
    corp_types_map = {}  # code → {placement: bool|obj, rights: bool|obj, increase: bool|obj}
    hkex_link_map = {}   # code → hkexLink URL
    
    for code, ct in corp_map.items():
        entry = {}
        for k in ('placement', 'rights', 'increase'):
            val = ct.get(k, False)
            entry[k] = val if val else False
        corp_types_map[code] = entry
        # Set hkexLink from latest corp action
        best_date = ''
        for k in ('placement', 'rights', 'increase'):
            v = ct.get(k)
            if v and v.get('date', '') > best_date:
                best_date = v['date']
                hkex_link_map[code] = v.get('link', '')
    
    print(f"corpTypes from announcements.json: {len(corp_map)} stocks with active corp actions (90-day window)")

    # === SIGNALS: from corp_scan_result.json + FVG + breakthroughs ===
    signals_map = {}     # code → list of signal strings

    # 2a. Corp scan alerted signals
    corp_data = load_json(CORP_SCAN)
    alerted = corp_data.get("alerted", []) if isinstance(corp_data, dict) else []
    watchlisted = corp_data.get("watchlisted", []) if isinstance(corp_data, dict) else []
    all_corps = alerted + watchlisted

    for item in all_corps:
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        types_list = item.get("types_list", [])
        if not types_list and item.get("types"):
            types_list = [item["types"]]
        if code not in signals_map:
            signals_map[code] = []
        for sig in map_signals(types_list):
            if sig not in signals_map[code]:
                signals_map[code].append(sig)
        # Also set hkexLink from alert if not already set
        url = item.get("url", "")
        if url and code not in hkex_link_map:
            hkex_link_map[code] = url

    # 2b. FVG signals
    fvg_data = load_json(FVG_JSON)
    fvg_alerts = fvg_data.get("alerts", []) if isinstance(fvg_data, dict) else []

    for alert in fvg_alerts:
        ticker = alert.get("ticker", "")  # e.g. "0941.HK"
        if not ticker or ".HK" not in ticker.upper():
            continue
        raw_code = ticker.upper().replace(".HK", "")
        code = raw_code.zfill(5)
        if code not in signals_map:
            signals_map[code] = []
        if "FVG" not in signals_map[code]:
            signals_map[code].append("FVG")

    # 2c. Breakthrough signals
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

    # 3. Build output groups
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
        "source": f"scanner + fvg + breakthroughs + announcements.json (price base: {source_path.name if source_path else 'unknown'})",
        "totalStocks": len(groups),
        "totalWithSignals": sum(1 for g in groups if g["signals"]),
        "totalWithCorpTypes": sum(1 for g in groups if any(g["corpTypes"].values())),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT, output)

    print(f"Generated {OUT}")
    print(f"  {len(groups)} stocks total")
    print(f"  {output['totalWithSignals']} with signals")
    print(f"  {output['totalWithCorpTypes']} with corp action types")
    print(f"  {len(recent_corps)} recent corps")
    print(f"  File size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    generate()
