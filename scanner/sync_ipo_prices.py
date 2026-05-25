"""
Sync IPO listing prices from Yahoo Finance to breakthrough price cache.

Fetches yf.Ticker(symbol).info['ipo_price'] for all active HK stocks,
then stores them in data/breakthrough_prices.json with type="ipo".
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yfinance as yf

# Add project root to path so we can import from scanner/
sys.path.insert(0, str(Path(__file__).parent.parent))
from scanner.breakthrough_detector import (
    load_price_cache,
    save_price_cache,
    export_breakthroughs_json,
)

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "ccass" / "ccass.db"

# How many stocks to process per batch before a longer pause
BATCH_SIZE = 20
BATCH_SLEEP = 2.0  # seconds between batches
CALL_SLEEP = 0.3   # seconds between individual calls


def get_hk_symbol(code: str) -> str:
    """Convert 5-digit HK stock code to Yahoo Finance symbol."""
    n = int(code)
    if n < 10000:
        return f"{n:04d}.HK"
    return f"{code}.HK"


def get_active_stock_codes() -> list[str]:
    """Get all active HK stock codes from the DB or fallback to ccass.json."""
    import sqlite3

    if DB_PATH.exists():
        db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT stock_code FROM stock_universe WHERE is_active = 1 ORDER BY stock_code"
        ).fetchall()
        db.close()
        if rows:
            codes = [r["stock_code"] for r in rows]
            print(f"Loaded {len(codes)} active stocks from DB")
            return codes

    # Fallback: read ccass.json
    ccass_path = PROJECT_ROOT / "ccass.json"
    if ccass_path.exists():
        data = json.loads(ccass_path.read_text(encoding="utf-8"))
        codes = [s["c"] for s in data.get("stocks", [])]
        print(f"Loaded {len(codes)} stocks from ccass.json (fallback)")
        return codes

    print("ERROR: No stock universe found (no DB, no ccass.json)")
    return []


def fetch_ipo_price(code: str) -> dict | None:
    """Fetch IPO listing price for a single HK stock from Yahoo Finance.
    Returns {type, price, date, title, link} dict or None.
    """
    symbol = get_hk_symbol(code)
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
    except Exception as e:
        print(f"  {code} ({symbol}): yfinance error: {e}")
        return None

    ipo_price = info.get("ipo_price") or info.get("regularMarketPreviousClose")
    # Sanity checks
    if ipo_price is None:
        return None
    try:
        ipo_price = float(ipo_price)
    except (ValueError, TypeError):
        return None
    if ipo_price <= 0 or ipo_price > 50000:
        return None

    # Get long name for title
    name = info.get("longName") or info.get("shortName") or ""
    # Try to get IPO date — yfinance rarely has this, but try
    ipo_date = info.get("ipo_date") or ""
    # Normalize date
    if isinstance(ipo_date, int):
        from datetime import datetime, timezone
        ipo_date = datetime.fromtimestamp(ipo_date, tz=timezone.utc).strftime("%Y-%m-%d")

    return {
        "type": "ipo",
        "price": round(ipo_price, 3),
        "date": str(ipo_date) if ipo_date else "",
        "title": name[:120],
        "link": f"https://finance.yahoo.com/quote/{symbol}",
    }


def main():
    codes = get_active_stock_codes()
    if not codes:
        print("No stock codes found. Aborting.")
        return

    cache = load_price_cache()
    added = 0
    skipped_existing = 0
    skipped_no_price = 0
    errors = 0
    total = len(codes)

    print(f"\nFetching IPO prices for {total} stocks...")
    print(f"Existing cache has {len(cache)} stocks with prices\n")

    for i, code in enumerate(codes):
        # Skip if already has type=ipo in cache
        if code in cache:
            has_ipo = any(e.get("type") == "ipo" for e in cache[code])
            if has_ipo:
                skipped_existing += 1
                if (i + 1) % 100 == 0:
                    print(f"  ... {i+1}/{total} (skipped {skipped_existing} existing, added {added})")
                continue

        result = fetch_ipo_price(code)

        if result is None:
            skipped_no_price += 1
        else:
            if code not in cache:
                cache[code] = []
            cache[code].append(result)
            added += 1
            print(f"  [{i+1}/{total}] {code} ({result['title'][:30]}) ipo @{result['price']}")

            # Save periodically (every 50 additions)
            if added % 50 == 0:
                save_price_cache(cache)
                print(f"  → saved {added} IPO prices so far")

            # Re-export breakthroughs.json periodically
            if added % 100 == 0:
                export_breakthroughs_json()

        # Rate limiting
        time.sleep(CALL_SLEEP)
        if (i + 1) % BATCH_SIZE == 0:
            time.sleep(BATCH_SLEEP)

        if errors > 50:
            print(f"Too many errors ({errors}), aborting.")
            break

    # Final save
    if added > 0:
        save_price_cache(cache)

    print(f"\n{'='*50}")
    print(f"IPO price sync complete:")
    print(f"  Total stocks checked: {total}")
    print(f"  IPO prices added:     {added}")
    print(f"  Already cached:       {skipped_existing}")
    print(f"  No IPO price found:   {skipped_no_price}")
    print(f"  Errors:               {errors}")
    print(f"  Cache now has:        {len(cache)} stocks")
    print(f"{'='*50}")

    # Export breakthroughs.json
    print("\nExporting breakthroughs.json...")
    export_breakthroughs_json()
    print("Done!")


if __name__ == "__main__":
    main()
