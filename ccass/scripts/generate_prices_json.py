"""
Generate data/prices.json from holdings/data/stock_prices.json + stock_universe names.
Output format matches GAS ?format=json response so dashboard can consume it directly.

The stock_prices.json is maintained daily by refresh_prices_and_suspended.py
(the daily pipeline cron c1a18c6a5786). Fallback to stock_prices DB table if JSON missing.

Fields per group:
  code, name, latestPrice, signals=[], corpTypes={}, hkexLink=''

Usage:
  python scripts/generate_prices_json.py
"""
import json, sqlite3
from pathlib import Path
from datetime import datetime

PROJECT = Path(__file__).parent.parent
DB = PROJECT / "holdings.db"
PRICES_JSON = PROJECT / "data" / "stock_prices.json"
OUT = PROJECT.parent / "data" / "prices.json"


def get_names():
    """Get stock names from stock_universe table."""
    try:
        db = sqlite3.connect(str(DB))
        rows = db.execute("SELECT stock_code, stock_name FROM stock_universe").fetchall()
        db.close()
        return {r[0]: r[1] or "" for r in rows}
    except Exception:
        return {}


def generate():
    names = get_names()

    # Try stock_prices.json first (maintained daily by refresh_prices_and_suspended.py)
    prices = {}
    if PRICES_JSON.exists():
        try:
            prices = json.loads(PRICES_JSON.read_text(encoding="utf-8"))
        except Exception:
            prices = {}

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

    # Build GAS-compatible groups
    groups = []
    for code in sorted(prices.keys()):
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
        "updatedAt": datetime.now().isoformat(),
        "source": "yfinance (static, via stock_prices.json)",
        "totalStocks": len(groups),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")

    print(f"Generated {OUT}")
    print(f"  {len(groups)} stocks with prices")
    print(f"  File size: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    generate()
