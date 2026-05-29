"""Merge 6 shard JSON files into SQLite DB — CI merge phase.

用法:
    python -m scripts.merge_shards --date 2026-05-23

Expects ccass-shard-0.json through ccass-shard-5.json in cwd.
Validates all 6, merges into DB, computes trends, sends alerts,
and updates ccass.json for the dashboard.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, date
from pathlib import Path

SHARD_TOTAL = 1  # P0-3: match parallel_backfill.py single-shard mode
SHARD_PREFIX = "ccass-shard"
PROJECT_ROOT = Path(__file__).parent.parent


def _shard_path(idx: int) -> Path:
    """Shard files always at repo root (PROJECT_ROOT.parent).
    Deterministic — no CWD dependency."""
    return PROJECT_ROOT.parent / f"{SHARD_PREFIX}-{idx}.json"


def _validate_shard(fpath: Path, expected_date: str, expected_shard: int) -> dict | None:
    """Validate a single shard JSON file. Returns parsed payload or None."""
    if not fpath.exists():
        print(f"  [X] shard {expected_shard}: file not found: {fpath}")
        return None
    try:
        payload = json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [X] shard {expected_shard}: JSON parse error: {e}")
        return None

    for k in ("shard", "shard_total", "query_date", "snapshots", "succeeded",
              "failed", "failed_stocks", "stocks_total", "stocks_in_shard"):
        if k not in payload:
            print(f"  [X] shard {expected_shard}: missing key '{k}'")
            return None

    if payload["shard"] != expected_shard:
        print(f"  [X] shard {expected_shard}: shard id mismatch ({payload['shard']})")
        return None
    if payload["shard_total"] != SHARD_TOTAL:
        print(f"  [X] shard {expected_shard}: shard_total mismatch ({payload['shard_total']})")
        return None
    if payload["query_date"] != expected_date:
        print(f"  [X] shard {expected_shard}: date mismatch ({payload['query_date']} != {expected_date})")
        return None
    if len(payload["snapshots"]) != payload["succeeded"]:
        print(f"  [X] shard {expected_shard}: len(snapshots)={len(payload['snapshots'])} != succeeded={payload['succeeded']}")
        return None

    return payload


def validate_all(date_str: str) -> tuple[list[dict], int, bool]:
    """Validate all 6 shards. Returns (all_payloads, total_failed, ok)."""
    all_payloads = []
    total_failed = 0
    all_ok = True

    for i in range(SHARD_TOTAL):
        fpath = _shard_path(i)
        p = _validate_shard(fpath, date_str, i)
        if p is None:
            all_ok = False
            continue
        all_payloads.append(p)
        total_failed += p["failed"]
        print(f"  OK shard {i}: {p['succeeded']}/{p['stocks_in_shard']} succeeded, {p['failed']} failed")

    if len(all_payloads) != SHARD_TOTAL:
        print(f"  [X] Only {len(all_payloads)}/{SHARD_TOTAL} valid shard files")
        return [], 0, False

    # Duplicate check
    seen = set()
    for p in all_payloads:
        for snap in p["snapshots"]:
            key = (snap["stock_code"], snap["trade_date"])
            if key in seen:
                print(f"  [X] Duplicate stock across shards: {key}")
                all_ok = False
            seen.add(key)

    # Failure rate check
    total_attempted = sum(p["stocks_in_shard"] for p in all_payloads)
    if total_attempted > 0:
        fail_rate = total_failed / total_attempted
        if fail_rate > 0.10:
            print(f"  [X] Aggregate failure rate {fail_rate:.1%} > 10%, aborting")
            all_ok = False

    return all_payloads, total_failed, all_ok


def merge_into_db(all_payloads: list[dict]) -> int:
    """Merge validated shard payloads into SQLite. Returns count written."""
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_ROOT))
    from src.db import DB_PATH, init_db
    from src.scraper import save_snapshot, CCASSSnapshot

    init_db()

    written = 0
    for p in all_payloads:
        for snap_dict in p["snapshots"]:
            snap = CCASSSnapshot(
                stock_code=snap_dict["stock_code"],
                trade_date=snap_dict["trade_date"],
                total_shares=snap_dict["total_shares"],
                total_pct=snap_dict["total_pct"],
                num_participants=snap_dict.get("num_participants", 0),
                holdings=snap_dict.get("holdings", []),
            )
            try:
                save_snapshot(snap)
                written += 1
            except Exception as e:
                print(f"  WARN save_snapshot failed for {snap_dict.get('stock_code', '??')}: {e}")

    return written


def update_ccass_json(target_date: date) -> None:
    """Update ccass.json with frontend-compatible fields from DB."""
    import sqlite3
    from src.db import DB_PATH
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    
    # Get stock names (exclude non-equity: temp codes, prefs, warrants)
    EXCLUDE_PATTERNS = [
        "029%",        # temp consolidation/split codes
        "04621",       # preference share
        "8%",          # RMB counters (人仔櫃台)
    ]
    EXCLUDE_NAME_KEYWORDS = ["PREF", "優先", "股權", "二千五", "二千", "一萬"]
    
    names = {}
    exclude_clauses = " OR ".join([f"stock_code LIKE '{p}'" for p in EXCLUDE_PATTERNS])
    exclude_clauses += " OR " + " OR ".join([f"stock_name LIKE '%{k}%'" for k in EXCLUDE_NAME_KEYWORDS])
    for row in db.execute(f"SELECT stock_code, stock_name FROM stock_universe WHERE NOT ({exclude_clauses})"):
        names[row[0]] = row[1] or row[0]
    
    # Get latest data for target_date (filter non-equity)
    exclude_where = " AND ".join([f"cd.stock_code NOT LIKE '{p}'" for p in EXCLUDE_PATTERNS])
    rows = db.execute(f"""
        SELECT cd.stock_code, cd.total_pct, cd.num_participants,
               cd.top5_pct, cd.top10_pct,
               cd.adj_hhi, cd.broker_top5_pct, cd.top_broker_id,
               cd.top_broker_name, cd.top_broker_pct, cd.futu_pct,
               cd.a00005_pct
        FROM ccass_daily cd
        WHERE cd.trade_date = ? AND {exclude_where}
    """, (target_date.strftime("%Y-%m-%d"),)).fetchall()
    
    # Get trends for this date (with streak)
    trends = {}
    for row in db.execute("""
        SELECT stock_code, delta_5d_pct, delta_20d_pct, delta_60d_pct, delta_120d_pct,
               consecutive_increase_days, consecutive_decrease_days
        FROM ccass_trends
        WHERE trade_date = ?
    """, (target_date.strftime("%Y-%m-%d"),)).fetchall():
        trends[row[0]] = {
            'd5': row[1], 'd20': row[2], 'd60': row[3], 'd120': row[4],
            'su': row[5] or 0, 'sd': row[6] or 0
        }
    
    # Market cap — try dated first, fallback to legacy
    mc_map = {}
    try:
        import json as _json
        # Try dated cache: market_caps_YYYY-MM-DD.json
        dated_path = PROJECT_ROOT / "cache" / f"market_caps_{target_date.strftime('%Y-%m-%d')}.json"
        legacy_path = PROJECT_ROOT / "cache" / "market_caps.json"
        
        mc_path = dated_path if dated_path.exists() else (legacy_path if legacy_path.exists() else None)
        if mc_path and mc_path.exists():
            mc_data = _json.loads(mc_path.read_text(encoding='utf-8'))
            for item in mc_data:
                mc_map[item.get('stock_code', '')] = item.get('market_cap')
    except Exception:
        pass

    # Stock prices (year-open + latest) from fetch_stock_prices.py
    price_map = {}
    try:
        price_path = PROJECT_ROOT / "data" / "stock_prices.json"
        if price_path.exists():
            price_data = _json.loads(price_path.read_text(encoding='utf-8'))
            price_map = price_data
    except Exception:
        pass

    stocks = []
    for row in rows:
        sc = row[0]
        tp = round(row[1] or 0, 2)
        np_val = row[2] or 0
        t5 = round(row[3] or 0, 2)
        t10 = round(row[4] or 0, 2)
        # Sentinel Option A fields (compact keys)
        ah = round(row[5], 1) if row[5] is not None else None       # adj_hhi
        bt5 = round(row[6], 2) if row[6] is not None else None      # broker_top5_pct
        tb = row[7] or ""                                             # top_broker_id
        tbn = row[8] or ""                                            # top_broker_name
        tbp = round(row[9], 2) if row[9] is not None else None       # top_broker_pct
        fp = round(row[10], 2) if row[10] is not None else None      # futu_pct
        a5 = round(row[11], 2) if row[11] is not None else None      # a00005_pct

        tr = trends.get(sc, {})
        mc = mc_map.get(sc)
        pr = price_map.get(sc, {})

        stocks.append({
            'c': sc,
            'n': names.get(sc, sc),
            'tp': tp,
            't5': t5,
            't10': t10,
            'd5': round(tr.get('d5'), 2) if tr.get('d5') is not None else None,
            'd20': round(tr.get('d20'), 2) if tr.get('d20') is not None else None,
            'd60': round(tr.get('d60'), 2) if tr.get('d60') is not None else None,
            'd120': round(tr.get('d120'), 2) if tr.get('d120') is not None else None,
            'su': tr.get('su', 0),
            'sd': tr.get('sd', 0),
            'np': np_val,
            'mc': mc,
            # Year-open + latest price
            'yo': pr.get('yo'),
            'lp': pr.get('lp'),
            'py': pr.get('apy', pr.get('py')),
            'py_pct': pr.get('apy_pct', pr.get('py_pct')),
            # Sentinel Option A (compact keys)
            'ah': ah,
            'bt5': bt5,
            'tb': tb,
            'tbn': tbn,
            'tbp': tbp,
            'fp': fp,
            'a5': a5,
        })

    total_participants = sum(s['np'] for s in stocks)

    # Top increase / decrease (by 5-day delta)
    sorted_up = sorted([s for s in stocks if s['d5'] is not None and s['d5'] > 0],
                       key=lambda s: -s['d5'])[:5]
    sorted_dn = sorted([s for s in stocks if s['d5'] is not None and s['d5'] < 0],
                       key=lambda s: s['d5'])[:5]
    top_increase = [{'c': s['c'], 'n': s['n'], 'd5': s['d5']} for s in sorted_up]
    top_decrease = [{'c': s['c'], 'n': s['n'], 'd5': s['d5']} for s in sorted_dn]

    # First date in DB
    first_row = db.execute("SELECT MIN(trade_date) FROM ccass_daily").fetchone()
    first_date = first_row[0] if first_row and first_row[0] else target_date.strftime("%Y-%m-%d")

    # Sanitize NaN → null (invalid JSON) before serializing
    import math as _math
    def _sanitize(obj):
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        if isinstance(obj, float) and _math.isnan(obj):
            return None
        return obj
    stocks = _sanitize(stocks)

    out = {
        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "stock_count": len(stocks),
        "stocks": stocks,
        "top_increase": top_increase,
        "top_decrease": top_decrease,
        "first_date": first_date,
        "total_participants": total_participants,
    }
    path = PROJECT_ROOT.parent / "ccass.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ccass.json updated: {len(stocks)} stocks")
    db.close()


def main():
    parser = argparse.ArgumentParser(description="Merge 6 shard JSONs into DB")
    parser.add_argument("--date", required=True, help="Query date YYYY-MM-DD")
    args = parser.parse_args()

    date_str = args.date
    print(f"Merge: query_date={date_str}")

    # Validate
    print("Validating shards...")
    all_payloads, total_failed, valid = validate_all(date_str)

    if not valid:
        print("FAIL: validation failed")
        sys.exit(1)

    # Merge
    print("Merging into DB...")
    written = merge_into_db(all_payloads)
    print(f"Merged: {written} snapshots ({total_failed} failures)")

    # Compute trends
    print("Computing trends...")
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.trend import compute_trends_for_date
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        n_trends = compute_trends_for_date(target_date)
        print(f"Trends computed: {n_trends} stocks")
    except Exception as e:
        print(f"WARN Trends failed: {e}")

    # Update ccass.json (after trends so deltas are included)
    print("Updating ccass.json...")
    update_ccass_json(target_date)

    # Run alerts
    print("Running alerts...")
    try:
        from src.alerts import scan_alerts_for_date
        n_alerts = scan_alerts_for_date(target_date)
        print(f"Alerts sent: {n_alerts}")
    except Exception as e:
        print(f"WARN Alerts failed: {e}")

    # Clean up shard JSONs
    for i in range(SHARD_TOTAL):
        fpath = _shard_path(i)
        if fpath.exists():
            fpath.unlink()

    print(f"Done: {date_str} merged successfully")


if __name__ == "__main__":
    main()
