"""
Generate data/prices.json from holdings/data/stock_prices.json + stock_universe names.
Output format matches GAS ?format=json response so dashboard can consume it directly.

The stock_prices.json is maintained daily by the Futu-based refresh script
(the daily pipeline cron c1a18c6a5786). Fallback to stock_prices DB table if JSON missing.

Fields per group:
  code, name, latestPrice, signals=[], corpTypes={}, hkexLink=''

Usage:
  python scripts/generate_prices_json.py
"""
import json, sqlite3
from pathlib import Path

PROJECT = Path(__file__).parent.parent
ROOT = PROJECT.parent
DB = PROJECT / "holdings.db"
PRICES_JSON = ROOT / "data" / "stock_prices.json"
LEGACY_PRICES_JSON = PROJECT / "data" / "stock_prices.json"
HOLDINGS_JSON = ROOT / "holdings.json"
OUT = ROOT / "data" / "prices.json"


def atomic_write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def get_names():
    """Get stock names, preferring publish JSON to avoid DB encoding drift."""
    names = {}
    try:
        holdings = json.loads(HOLDINGS_JSON.read_text(encoding="utf-8"))
        for stock in holdings.get("stocks", []):
            code = str(stock.get("c", "")).zfill(5)
            name = stock.get("n") or ""
            if code and name:
                names[code] = name
    except Exception:
        pass

    try:
        db = sqlite3.connect(str(DB))
        rows = db.execute("SELECT stock_code, stock_name FROM stock_universe").fetchall()
        db.close()
        for code, name in rows:
            names.setdefault(str(code).zfill(5), name or "")
    except Exception:
        pass
    return names


def generate():
    names = get_names()

    # Try stock_prices.json first (maintained daily by refresh_prices_and_suspended.py)
    prices = {}
    for candidate in (PRICES_JSON, LEGACY_PRICES_JSON):
        if not candidate.exists():
            continue
        try:
            prices = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            prices = {}
        if prices:
            break

    # Fallback: read from stock_prices DB table (latest close per stock)
    if not prices:
        db = sqlite3.connect(str(DB))
        rows = db.execute("""
            SELECT sp.stock_code, sp.close AS lp
            FROM stock_prices sp
            WHERE sp.price_date = (
                SELECT MAX(price_date) FROM stock_prices sp2
                WHERE sp2.stock_code = sp.stock_code
            )
            AND sp.close IS NOT NULL AND sp.close > 0
            ORDER BY sp.stock_code
        """).fetchall()
        db.close()
        for code, lp in rows:
            prices[code] = {"lp": round(float(lp), 3)}
        print(f"  (read {len(prices)} prices from DB fallback)")

    meta = prices.get("_meta") if isinstance(prices, dict) else {}
    updated_at = (meta or {}).get("updated_at")
    provider = (meta or {}).get("source")

    # Build GAS-compatible groups
    groups = []
    for code in sorted(k for k in prices.keys() if str(k).isdigit() and len(str(k)) == 5):
        entry = prices[code]
        lp = entry.get("lp")
        if lp is None or lp <= 0:
            continue
        groups.append({
            "code": code,
            "name": names.get(code, ""),
            "latestPrice": round(float(lp), 3),
            "signals": [],
            "corpTypes": {},
            "hkexLink": "",
        })

    output = {
        "ok": True,
        "groups": groups,
        "recentCorps": [],
        "updatedAt": updated_at,
        "source": "Futu/Longbridge cache (via stock_prices.json)",
        "provider": provider,
        "totalStocks": len(groups),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT, output)

    print(f"Generated {OUT}")
    print(f"  {len(groups)} stocks with prices")
    print(f"  File size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    generate()
