"""
Placement/Rights Price Breakthrough Detector.

從HKEX公告提取配股價/供股價 → 每日check現價是否突破 → feed dashboard signal.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

HKT_TZ = timezone(__import__("datetime").timedelta(hours=8))
DATA_DIR = Path(__file__).parent.parent / "data"
PRICE_CACHE = DATA_DIR / "breakthrough_prices.json"

# Regex patterns for extracting offer prices from HKEX announcement titles
PRICE_PATTERNS = [
    # "at HK$0.38 per share" / "at the price of HK$0.38"
    re.compile(r'(?:at\s+(?:the\s+)?(?:price|placing price|subscription price|offer price|issue price)\s+of\s+)?HK\$?\s*(\d+\.?\d*)', re.I),
    # "每股0.38港元" / "配售價每股0.38港元" / "供股價每股0.12港元" 
    re.compile(r'(?:配售價|供股價|發行價|認購價|每股)\s*(?:為|：|:)?\s*(?:HK\$?\s*)?(\d+\.?\d*)\s*(?:港元|元|港幣)?'),
    # "HK$0.38" bare price near "placing" or "subscription"
    re.compile(r'HK\$?\s*(\d+\.\d{2,})'),
    # "$0.38 per share" / "priced at $0.38"
    re.compile(r'\$\s*(\d+\.?\d*)\s*(?:per\s+share|each)', re.I),
]


def today_hkt() -> date:
    return datetime.now(HKT_TZ).date()


def extract_price_from_title(title: str) -> float | None:
    """Extract offer price from HKEX announcement title/headline.
    Returns the price as float, or None if not found.
    """
    if not title:
        return None
    for pat in PRICE_PATTERNS:
        m = pat.search(title)
        if m:
            try:
                price = float(m.group(1))
                if 0.001 < price < 10000:  # sanity check
                    return price
            except ValueError:
                continue
    return None


def load_price_cache() -> dict:
    """Load the price cache. Returns {code: [{type, price, date, title, link}]}."""
    if PRICE_CACHE.exists():
        try:
            return json.loads(PRICE_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_price_cache(cache: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRICE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def add_prices_from_announcements(announcements: list[dict]) -> int:
    """Scan HKEX announcements for placement/rights prices. Add to cache. Returns count added."""
    cache = load_price_cache()
    added = 0

    for ann in announcements:
        code = str(ann.get("code", "")).zfill(5)
        types = ann.get("types", [])
        title = ann.get("title", "") or ann.get("title_en", "")
        title_en = ann.get("title_en", "") or ann.get("title", "")
        link = ann.get("url", "")
        ann_date = ann.get("release_date", "")

        # Only process placement or rights issue announcements
        is_placement = "配股" in types
        is_rights = "供股" in types
        if not (is_placement or is_rights):
            continue

        price = extract_price_from_title(title) or extract_price_from_title(title_en)
        if price is None:
            continue

        event_type = "placement" if is_placement else "rights"

        if code not in cache:
            cache[code] = []

        # Check for duplicates
        existing = [e for e in cache[code]
                    if e["type"] == event_type and e["date"] == ann_date]
        if existing:
            continue

        cache[code].append({
            "type": event_type,
            "price": price,
            "date": ann_date,
            "title": title[:120],
            "link": link,
        })
        added += 1
        print(f"[breakthrough] + {code} {event_type} @{price} {ann_date}")

    if added:
        save_price_cache(cache)
    return added


def check_breakthrough(stock_code: str) -> dict[str, Any] | None:
    """Check if a stock just broke above its placement/rights price.
    Returns breakthrough signal dict or None.
    """
    cache = load_price_cache()
    if stock_code not in cache:
        return None

    entries = cache[stock_code]
    today = today_hkt()

    # Get current price from Yahoo Finance
    try:
        symbol = f"{stock_code[-4:]}.HK"
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist.empty:
            return None
        cur_price = float(hist.iloc[-1]["Close"])
        prev_price = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else cur_price
    except Exception:
        return None

    for entry in entries:
        offer_price = entry["price"]
        if cur_price <= 0 or offer_price <= 0:
            continue

        # "首日突破": today > offer AND yesterday <= offer
        if cur_price > offer_price and prev_price <= offer_price:
            pct_above = round((cur_price - offer_price) / offer_price * 100, 1)
            return {
                "type": entry["type"],
                "offer_price": offer_price,
                "current_price": round(cur_price, 3),
                "pct_above": pct_above,
                "date": entry["date"],
                "title": entry.get("title", ""),
                "breakthrough_date": today.isoformat(),
            }

    return None


def scan_all_breakthroughs() -> list[dict]:
    """Scan all stocks with cached prices for today's breakthroughs.
    Returns list of breakthrough signals.
    """
    cache = load_price_cache()
    results = []
    for code in cache:
        bt = check_breakthrough(code)
        if bt:
            bt["stock_code"] = code
            results.append(bt)
            print(f"[breakthrough] {code} {bt['type']} break @{bt['offer_price']} → {bt['current_price']} (+{bt['pct_above']}%)")
    return results


def export_breakthroughs_json(output_path: str | None = None) -> str:
    """Export breakthroughs to JSON file for dashboard consumption.
    Returns path to the output file.
    """
    breakthroughs = scan_all_breakthroughs()
    cache = load_price_cache()

    payload = {
        "updated": datetime.now(HKT_TZ).isoformat(),
        "breakthroughs": breakthroughs,
        "active_prices": {
            code: [
                {"type": e["type"], "price": e["price"], "date": e["date"]}
                for e in entries
            ]
            for code, entries in cache.items()
        },
    }

    out = Path(output_path) if output_path else DATA_DIR / "breakthroughs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[breakthrough] exported {len(breakthroughs)} signals to {out}")
    return str(out)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--scan", action="store_true", help="Scan for breakthroughs")
    p.add_argument("--export", type=str, help="Export path")
    p.add_argument("--add-price", nargs=4, metavar=("CODE", "TYPE", "PRICE", "DATE"),
                   help="Manually add a price: CODE placement|rights PRICE DATE")
    args = p.parse_args()

    if args.add_price:
        code, etype, price_str, date_str = args.add_price
        cache = load_price_cache()
        if code not in cache:
            cache[code] = []
        cache[code].append({
            "type": etype,
            "price": float(price_str),
            "date": date_str,
            "title": "(manual)",
            "link": "",
        })
        save_price_cache(cache)
        print(f"[breakthrough] added {code} {etype} @{price_str} {date_str}")

    if args.scan:
        scan_all_breakthroughs()

    if args.export:
        export_breakthroughs_json(args.export)
