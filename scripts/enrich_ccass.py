"""
enrich_ccass.py — API-only enrichment (NO scraping)
Reads CCASS from DB, enriches with Futu prices + FCF.
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
EXCLUDE_PATTERNS = ["029%", "04621", "8%"]


def atomic_write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_latest_trade_date(conn):
    """Return the newest trade date that has at least one valid row."""
    row = conn.execute(
        """
        SELECT trade_date
        FROM ccass_daily
        WHERE validation_failed = 0
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT 1
        """
    ).fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


def get_date_coverage(conn, trade_date):
    """Return row coverage for a given trade date."""
    exclude_clause = " AND ".join([f"stock_code NOT LIKE '{p}'" for p in EXCLUDE_PATTERNS])
    total = conn.execute(
        f"SELECT COUNT(*) FROM stock_universe WHERE is_active=1 AND {exclude_clause}"
    ).fetchone()[0] or 0
    have = conn.execute(
        """
        SELECT COUNT(*)
        FROM ccass_daily
        WHERE trade_date = ? AND validation_failed = 0
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04621'
          AND stock_code NOT LIKE '8%'
        """,
        (trade_date,),
    ).fetchone()[0] or 0
    return have, total, round((have / total) * 100, 1) if total else None


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
    """Load non-trend price metadata from westock cache."""
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

    # Support raw format: {code: {cfo, capex, fcf, unit, report}}
    normalized = {}
    for code, item in data.items():
        code = str(code).zfill(5)
        if isinstance(item, dict):
            latest = item.get("latest", item.get("fcf"))
            entry = dict(item)
            if latest is not None:
                entry["latest"] = latest
                entry["fcf"] = item.get("fcf", latest)
            normalized[code] = entry
        else:
            normalized[code] = item

    logger.info("Loaded %d FCF entries", len(normalized))
    return normalized


def load_fcf5y():
    """Load 5-year FCF bar data."""
    path = PROJ / "data" / "fcf5y.json"
    if not path.exists():
        logger.warning("No fcf5y.json found")
        return {}
    with open(path) as f:
        data = json.load(f)
    logger.info("Loaded %d FCF 5Y entries", len(data) if isinstance(data, dict) else 0)
    return data if isinstance(data, dict) else {}


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
        # Get latest trade date, even if it is still partially complete.
        latest_date = get_latest_trade_date(conn)
        if not latest_date:
            logger.error("No CCASS data in DB!")
            return None
        have, total, coverage_pct = get_date_coverage(conn, latest_date)
        logger.info("Latest CCASS date: %s (%d/%d rows, %.1f%%)", latest_date, have, total, coverage_pct or 0.0)
        
        # Get all stocks for latest date
        rows = conn.execute("""
            SELECT stock_code, total_pct, num_participants, top5_pct, top10_pct,
                   adj_hhi, broker_top5_pct, top_broker_id, top_broker_name, top_broker_pct
            FROM ccass_daily
            WHERE trade_date = ? AND validation_failed = 0
              AND stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04621'
              AND stock_code NOT LIKE '8%'
        """, (latest_date,)).fetchall()
        
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

    # 2. Enrich with Futu prices + non-trend price metadata
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
                    # FIX 2: Cap anomalous PE values (>500) at null to prevent sorting/filter pollution
                    if k == "pe" and fp[k] > 500:
                        continue
                    price_data[code][k] = fp[k]
    fcf_data = load_fcf()
    fcf5y_data = load_fcf5y()
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
                latest = fc.get("latest", fc.get("fcf"))
                if latest is not None and s.get("fcf") is None:
                    try:
                        latest_val = float(latest)
                        s["fcf"] = round(latest_val / 1e8, 1) if abs(latest_val) > 1e6 else round(latest_val, 1)
                    except Exception:
                        s["fcf"] = latest
            else:
                s["fcf"] = fc

        if code in fcf5y_data and s.get("fcf5y") is None:
            s["fcf5y"] = fcf5y_data[code]
        
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
    
    # FIX 3: Detect suspended/dead stocks — if hi52==lo52 AND vol==0, mark as suspended
    suspended_count = 0
    for code, s in stocks.items():
        if not s.get("suspended"):
            hi = s.get("hi52")
            lo = s.get("lo52")
            vol = s.get("vol")
            if (hi is not None and lo is not None and hi == lo) and (vol is not None and vol == 0):
                s["suspended"] = True
                suspended_count += 1
    if suspended_count:
        logger.info("Marked %d stocks as suspended (hi52==lo52, vol==0)", suspended_count)
    
    logger.info("Enriched: %d/%d stocks", enriched, len(stocks))
    
    # 3. Build final holdings.json
    result = {
        "updated": latest_date,
        "stock_count": len(stocks),
        "stocks": list(stocks.values()),
        "first_date": "2026-04-30",
        "coverage": have,
        "coverage_total": total,
        "coverage_pct": coverage_pct,
        "is_complete": bool(total and have >= total),
    }

    # Write
    out_path = PROJ / "holdings.json"
    atomic_write_json(out_path, result)
    
    logger.info("Written holdings.json: %d stocks, %d bytes", len(stocks), out_path.stat().st_size)
    
    # Also write to data/holdings.json for dashboard
    data_out = PROJ / "data" / "holdings.json"
    atomic_write_json(data_out, result)
    
    logger.info("Written data/holdings.json")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-only", action="store_true", help="Only generate holdings.json (skip DB load)")
    args = parser.parse_args()
    
    build_ccass_json()


if __name__ == "__main__":
    main()
