"""
enrich_ccass.py — API-only enrichment (NO scraping)
Reads CCASS from DB, enriches with Futu prices + westock deltas + FCF.
Generates holdings.json for the dashboard.
"""
import json, sys, os, argparse
from datetime import datetime, date
from pathlib import Path

PROJ = Path(__file__).parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "ccass"))

from src.db import get_conn, init_db
from src.logger import setup_logger

logger = setup_logger("enrich_ccass")


def load_futu_prices():
    """Load latest prices from Futu cache."""
    # Try local price cache first
    cache_path = PROJ / "data" / "stock_prices.json"
    if cache_path.exists():
        with open(cache_path) as f:
            data = json.load(f)
        logger.info("Loaded %d prices from cache", len(data))
        return data
    
    # Try ccass cache
    cache2 = PROJ / "ccass" / "cache" / "enrich_futu.json"
    if cache2.exists():
        with open(cache2) as f:
            data = json.load(f)
        logger.info("Loaded %d prices from Futu enrich cache", len(data))
        return data
    
    logger.warning("No price cache found")
    return {}


def load_westock_deltas():
    """Load delta data from westock cache."""
    prices_path = PROJ / "data" / "prices.json"
    if not prices_path.exists():
        logger.warning("No prices.json found")
        return {}
    
    with open(prices_path) as f:
        data = json.load(f)
    
    if data.get("ok") and "groups" in data:
        stocks = {}
        for g in data["groups"]:
            code = g.get("code", "").zfill(5)
            stocks[code] = {
                "d5": g.get("d5"),
                "d20": g.get("d20"),
                "d60": g.get("d60"),
                "d120": g.get("d120"),
                "lp": g.get("latestPrice"),
                "mc": g.get("marketCap"),
                "chg": g.get("changePercent"),
                "yo": g.get("yearOpen"),
                "py": g.get("prevYearOpen"),
                "pypct": g.get("prevYearChangePercent"),
                "yo_pct": g.get("yearChangePercent"),
                "vr": g.get("volumeRatio"),
            }
        logger.info("Loaded %d stocks from prices.json", len(stocks))
        return stocks
    
    logger.warning("prices.json has unexpected format")
    return {}


def load_fcf():
    """Load FCF data."""
    fcf_path = PROJ / "data" / "fcf.json"
    if not fcf_path.exists():
        logger.warning("No fcf.json found")
        return {}
    with open(fcf_path) as f:
        data = json.load(f)
    # fcf.json is {code: {latest, trend_5y, ...}}
    logger.info("Loaded %d FCF entries", len(data))
    return data


def load_signals():
    """Load signal data."""
    sig_path = PROJ / "data" / "signals.json"
    alerts_path = PROJ / "data" / "alerts.json"
    signals = {}
    
    for path in [sig_path, alerts_path]:
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        code = str(item.get("code", "")).zfill(5)
                        if code not in signals:
                            signals[code] = []
                        signals[code].append(item.get("type") or item.get("signal"))
                elif isinstance(data, dict):
                    for code, info in data.items():
                        signals[str(code).zfill(5)] = info if isinstance(info, list) else [info]
            except: pass
    
    logger.info("Loaded signals for %d stocks", len(signals))
    return signals


def load_breakthroughs():
    """Load breakthrough prices."""
    bt_path = PROJ / "data" / "breakthrough_prices.json"
    if bt_path.exists():
        with open(bt_path) as f:
            data = json.load(f)
        logger.info("Loaded %d breakthrough prices", len(data))
        return data
    return {}


def build_ccass_json():
    """Build complete holdings.json from DB + APIs."""
    init_db()
    
    # 1. Load latest CCASS from DB
    with get_conn() as conn:
        # Get latest trade date
        row = conn.execute(
            "SELECT trade_date FROM ccass_daily ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if not row:
            logger.error("No CCASS data in DB!")
            return None
        latest_date = row["trade_date"]
        logger.info("Latest CCASS date: %s", latest_date)
        
        # Get all stocks for latest date
        rows = conn.execute("""
            SELECT stock_code, total_pct, num_participants, top5_pct, top10_pct,
                   adj_hhi, broker_top5_pct, top_broker_id, top_broker_name, top_broker_pct
            FROM ccass_daily
            WHERE trade_date = ?
        """, (latest_date,)).fetchall()
        
        # Get trends (5d delta from previous dates)
        stocks = {}
        for r in rows:
            code = r["stock_code"]
            stocks[code] = {
                "c": code,
                "tp": r["total_pct"],
                "np": r["num_participants"],
                "t5": r["top5_pct"],
                "t10": r["top10_pct"],
                "hhi": r["adj_hhi"],
            }
        
        logger.info("DB stocks: %d", len(stocks))
        
        # Trend: compare with previous trading day
        prev_date = conn.execute(
            "SELECT trade_date FROM ccass_daily WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1",
            (latest_date,)
        ).fetchone()
        
        if prev_date:
            prev = prev_date["trade_date"]
            prev_rows = conn.execute(
                "SELECT stock_code, top5_pct FROM ccass_daily WHERE trade_date = ?",
                (prev,)
            ).fetchall()
            prev_map = {r["stock_code"]: r["top5_pct"] for r in prev_rows}
            
            for code in stocks:
                if code in prev_map and prev_map[code] and stocks[code]["t5"]:
                    stocks[code]["su"] = round(stocks[code]["t5"] - prev_map[code], 2)
            
            logger.info("Trend computed against %s", prev)
    
    # 2. Enrich with Futu prices + westock deltas
    price_data = load_westock_deltas()
    # Also load Futu prices (stock_prices.json) — primary source for lp,chg,mc,yo,py
    futu_prices = load_futu_prices()
    if futu_prices:
        # Merge futu prices into price_data (futu takes priority for overlapping keys)
        for code, fp in futu_prices.items():
            if code not in price_data:
                price_data[code] = {}
            for k in ["lp", "mc", "chg", "yo", "py", "py_pct", "yo_pct", "vr", "vol", "hi52", "lo52", "p52", "avg_vol", "beta", "pe"]:
                if k in fp and fp[k] is not None:
                    price_data[code][k] = fp[k]
    fcf_data = load_fcf()
    signals = load_signals()
    
    enriched = 0
    for code, s in stocks.items():
        # Price & delta data
        if code in price_data:
            pd = price_data[code]
            for key in list(pd.keys()):
                if key not in ['code', 'name'] and pd.get(key) is not None:
                    s[key] = pd[key]
        
        # FCF data
        if code in fcf_data:
            fc = fcf_data[code]
            if isinstance(fc, dict):
                s["fcf"] = fc.get("latest")
                s["fcfy"] = fc.get("trend_5y") or fc.get("trend")
            else:
                s["fcf"] = fc
        
        # Signals
        if code in signals:
            s["sd"] = len(signals[code]) if isinstance(signals[code], list) else 1
        
        # Name lookup
        if "n" not in s:
            # Try from DB
            try:
                with get_conn() as conn:
                    nr = conn.execute(
                        "SELECT stock_name FROM stock_universe WHERE stock_code=? AND is_active=1",
                        (code,)
                    ).fetchone()
                    if nr:
                        s["n"] = nr["stock_name"]
            except: pass
        
        enriched += 1
    
    logger.info("Enriched: %d/%d stocks", enriched, len(stocks))
    
    # 3. Build final holdings.json
    result = {
        "updated": latest_date,
        "stock_count": len(stocks),
        "stocks": list(stocks.values()),
        "first_date": "2026-04-30",
    }
    
    # Write
    out_path = PROJ / "holdings.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    
    logger.info("Written holdings.json: %d stocks, %d bytes", len(stocks), out_path.stat().st_size)
    
    # Also write to data/holdings.json for dashboard
    data_out = PROJ / "data" / "holdings.json"
    with open(data_out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    
    logger.info("Written data/holdings.json")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-only", action="store_true", help="Only generate holdings.json (skip DB load)")
    args = parser.parse_args()
    
    build_ccass_json()


if __name__ == "__main__":
    main()
