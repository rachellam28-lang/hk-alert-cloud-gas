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

SHARD_TOTAL = 6
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
    
    # Get stock names
    names = {}
    for row in db.execute("SELECT stock_code, stock_name FROM stock_universe"):
        names[row[0]] = row[1] or row[0]
    
    # Get latest data for target_date
    rows = db.execute("""
        SELECT cd.stock_code, cd.total_pct, cd.num_participants,
               cd.top5_pct, cd.top10_pct
        FROM ccass_daily cd
        WHERE cd.trade_date = ?
    """, (target_date.strftime("%Y-%m-%d"),)).fetchall()
    
    # Get trends for this date
    trends = {}
    for row in db.execute("""
        SELECT stock_code, delta_5d_pct, delta_20d_pct, delta_60d_pct, delta_120d_pct
        FROM ccass_trends
        WHERE trade_date = ?
    """, (target_date.strftime("%Y-%m-%d"),)).fetchall():
        trends[row[0]] = {
            'd5': row[1], 'd20': row[2], 'd60': row[3], 'd120': row[4]
        }
    
    # Market cap
    mc_map = {}
    try:
        import json as _json
        mc_path = PROJECT_ROOT / "cache" / "market_caps.json"
        if mc_path.exists():
            mc_data = _json.loads(mc_path.read_text(encoding='utf-8'))
            for item in mc_data:
                mc_map[item.get('stock_code', '')] = item.get('market_cap')
    except Exception:
        pass
    
    stocks = []
    for row in rows:
        sc = row[0]
        tp = row[1] or 0
        np_val = row[2] or 0
        t5 = row[3] or 0
        t10 = row[4] or 0
        
        tr = trends.get(sc, {})
        mc = mc_map.get(sc)
        
        stocks.append({
            'c': sc,
            'n': names.get(sc, sc),
            'tp': tp,
            't5': t5,
            't10': t10,
            'd5': tr.get('d5'),
            'd20': tr.get('d20'),
            'd60': tr.get('d60'),
            'd120': tr.get('d120'),
            'su': 0,
            'sd': 0,
            'np': np_val,
            'mc': mc,
        })
    
    out = {
        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "stock_count": len(stocks),
        "stocks": stocks,
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
