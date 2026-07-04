"""Merge shard JSON files into SQLite DB — CI merge phase.

用法:
    python -m scripts.merge_shards --date 2026-05-23

Expects holdings-shard-0.json through holdings-shard-{SHARD_TOTAL-1}.json in repo root.
Validates all shards, merges into DB, sends alerts,
and updates holdings.json for the dashboard.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

SHARD_TOTAL = int(os.environ.get("SHARD_TOTAL", "1"))
SHARD_PREFIX = "holdings-shard"
PROJECT_ROOT = Path(__file__).parent.parent


def _shard_path(idx: int) -> Path:
    """Shard files always at repo root (PROJECT_ROOT.parent).
    Deterministic — no CWD dependency."""
    return PROJECT_ROOT.parent / f"{SHARD_PREFIX}-{idx}.json"


def _safe_atomic_write(path: Path, payload: dict) -> None:
    """Atomic JSON write with best-effort parent creation.

    Some runtime environments raise ENOSYS on mkdir/stat against mounted
    paths even when the directory already exists. If that happens, fall
    back to writing directly.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if getattr(e, "errno", None) not in (38,):
            raise
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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
    from src.scraper import save_snapshot, HOLDINGSSnapshot

    init_db()

    written = 0
    for p in all_payloads:
        for snap_dict in p["snapshots"]:
            snap = HOLDINGSSnapshot(
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


def update_holdings_json(target_date: date) -> None:
    """Update holdings.json with frontend-compatible fields from DB."""
    import sqlite3
    from src.db import DB_PATH
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    
    # Get stock names (exclude non-equity: temp codes, prefs, warrants)
    EXCLUDE_PATTERNS = [
        "029%",        # temp consolidation/split codes
        "04%",         # non-core 04xxx counters (e.g. 04337)
        "8%",          # RMB counters (人仔櫃台)
    ]
    EXCLUDE_NAME_KEYWORDS = ["PREF", "優先", "股權", "二千五", "二千", "一萬"]
    
    names = {}
    exclude_clauses = " OR ".join([f"stock_code LIKE '{p}'" for p in EXCLUDE_PATTERNS])
    exclude_clauses += " OR " + " OR ".join([f"stock_name LIKE '%{k}%'" for k in EXCLUDE_NAME_KEYWORDS])
    for row in db.execute(f"SELECT stock_code, stock_name FROM stock_universe WHERE NOT ({exclude_clauses})"):
        names[row[0]] = row[1] or row[0]
    
    # Get latest data for target_date (filter non-equity)
    exclude_params = tuple(EXCLUDE_PATTERNS)
    exclude_where = " AND ".join([f"cd.stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])
    rows = db.execute(f"""
        SELECT cd.stock_code, cd.total_pct, cd.num_participants,
               cd.top5_pct, cd.top10_pct,
               cd.adj_hhi, cd.broker_top5_pct, cd.top_broker_id,
               cd.top_broker_name, cd.top_broker_pct, cd.futu_pct,
               cd.a00005_pct
        FROM holdings_daily cd
        WHERE cd.trade_date = ? AND {exclude_where}
    """, (target_date.strftime("%Y-%m-%d"), *exclude_params)).fetchall()
    
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
            # Support both list-of-dicts AND dict format (runner.py uses dict)
            if isinstance(mc_data, list):
                for item in mc_data:
                    mc_map[item.get('stock_code', '')] = item.get('market_cap')
            elif isinstance(mc_data, dict):
                mc_map = mc_data
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

    # FCF enrichment is maintained by a separate pipeline. Preserve it across
    # CCASS rewrites so regenerate_json does not wipe the 5Y bar-chart data.
    fcf_map = {}
    try:
        fcf5y_path = PROJECT_ROOT.parent / "data" / "fcf5y.json"
        fcf_path = PROJECT_ROOT.parent / "data" / "fcf.json"
        fcf5y_data = _json.loads(fcf5y_path.read_text(encoding="utf-8")) if fcf5y_path.exists() else {}
        fcf_data = _json.loads(fcf_path.read_text(encoding="utf-8")) if fcf_path.exists() else {}
        if isinstance(fcf5y_data, dict):
            for code, val in fcf5y_data.items():
                code5 = str(code).strip().zfill(5)
                if isinstance(val, list) and val:
                    fcf_map.setdefault(code5, {})["fcf5y"] = val
                    last = val[-1]
                    if isinstance(last, dict) and last.get("fcf") is not None:
                        fcf_map.setdefault(code5, {})["fcf"] = last.get("fcf")
                        first = next((x for x in val if isinstance(x, dict) and x.get("fcf") is not None), None)
                        if first and first.get("fcf") is not None and last.get("fcf") is not None:
                            fcf_map.setdefault(code5, {})["fcf_trend"] = 1 if last.get("fcf") >= first.get("fcf") else -1
        if isinstance(fcf_data, dict):
            for code, val in fcf_data.items():
                code5 = str(code).strip().zfill(5)
                if isinstance(val, dict):
                    fcf_map.setdefault(code5, {}).update({k: v for k, v in val.items() if k in ("fcf", "fcf5y", "fcf_trend")})
                elif isinstance(val, (int, float)):
                    fcf_map.setdefault(code5, {})["fcf"] = val
    except Exception:
        pass

    stocks = []
    for row in rows:
        sc = row[0]
        tp = round(row[1], 2) if row[1] is not None else None
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

        mc = mc_map.get(sc)
        pr = price_map.get(sc, {})
        fcf = fcf_map.get(sc, {})

        stock = {
            'c': sc,
            'n': names.get(sc, sc),
            'tp': tp,
            't5': t5,
            't10': t10,
            'np': np_val,
            'mc': mc,
            # Year-open + latest price
            'yo': pr.get('yo'),
            'lp': pr.get('lp'),
            'py': pr.get('apy', pr.get('py')),
            'py_pct': pr.get('apy_pct', pr.get('py_pct')),
            # Cached live quote fields (compact keys)
            'chg': pr.get('chg'),            # 今日變幅%
            'vol': pr.get('vol'),            # 成交額
            'hi52': pr.get('hi52'),          # 52週高
            'lo52': pr.get('lo52'),          # 52週低
            'p52': pr.get('p52'),            # 52週位置%
            'pe': pr.get('pe'),              # PE ratio
            'beta': pr.get('beta'),          # Beta
            'avg_vol': pr.get('avg_vol'),    # 平均成交量
            'vr': (pr.get('vol') or 0) / (pr.get('avg_vol') or 1) if pr.get('avg_vol') else None,  # 量比
            # Sentinel Option A (compact keys)
            'ah': ah,
            'bt5': bt5,
            'tb': tb,
            'tbn': tbn,
            'tbp': tbp,
            'fp': fp,
            'a5': a5,
        }
        for key in ("fcf", "fcf5y", "fcf_trend"):
            if fcf.get(key) is not None:
                stock[key] = fcf[key]
        stocks.append(stock)

    total_participants = sum(s['np'] for s in stocks)

    # Trend pipeline disabled: do not publish derived movers.
    top_increase: list[dict] = []
    top_decrease: list[dict] = []

    # First date in DB
    first_row = db.execute("SELECT MIN(trade_date) FROM holdings_daily").fetchone()
    first_date = first_row[0] if first_row and first_row[0] else target_date.strftime("%Y-%m-%d")

    active_row = db.execute(
        """
        SELECT COUNT(*)
        FROM stock_universe
        WHERE is_active=1
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """
    ).fetchone()
    active_total = active_row[0] if active_row else 0
    date_row = db.execute(
        """
        SELECT COUNT(*)
        FROM holdings_daily
        WHERE trade_date = ? AND validation_failed = 0
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """,
        (target_date.strftime("%Y-%m-%d"),),
    ).fetchone()
    date_count = date_row[0] if date_row else 0
    coverage_pct = round((date_count / active_total) * 100, 1) if active_total else None

    # Load suspended stocks
    suspended_map = {}
    try:
        suspended_path = PROJECT_ROOT / "data" / "suspended_stocks.json"
        if suspended_path.exists():
            suspended_map = json.loads(suspended_path.read_text(encoding='utf-8'))
    except Exception:
        pass

    # Add suspended flag
    for s in stocks:
        s['suspended'] = s['c'] in suspended_map

    # Sanitize NaN → null (invalid JSON) before serializing
    import math as _math
    def _sanitize(obj):
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        if isinstance(obj, float) and (_math.isnan(obj) or _math.isinf(obj)):
            return None
        return obj
    stocks = _sanitize(stocks)

    out = {
        "updated": target_date.strftime("%Y-%m-%d"),
        "stock_count": len(stocks),
        "stocks": stocks,
        "top_increase": top_increase,
        "top_decrease": top_decrease,
        "first_date": first_date,
        "total_participants": total_participants,
        "coverage": date_count,
        "coverage_total": active_total,
        "coverage_pct": coverage_pct,
        "is_complete": bool(active_total and date_count >= active_total),
    }
    legacy_out = dict(out)
    legacy_out["alerts_today"] = 0

    holdings_path = PROJECT_ROOT.parent / "holdings.json"
    ccass_path = PROJECT_ROOT.parent / "ccass.json"
    _safe_atomic_write(holdings_path, out)
    _safe_atomic_write(ccass_path, legacy_out)

    verified = json.loads(holdings_path.read_text(encoding="utf-8"))
    if verified.get("updated") != target_date.strftime("%Y-%m-%d"):
        raise RuntimeError(f"holdings.json stale date: {verified.get('updated')} != {target_date}")
    if verified.get("stock_count") != len(stocks):
        raise RuntimeError(f"holdings.json stock_count mismatch: {verified.get('stock_count')} != {len(stocks)}")
    ccass_verified = json.loads(ccass_path.read_text(encoding="utf-8"))
    if ccass_verified.get("updated") != target_date.strftime("%Y-%m-%d"):
        raise RuntimeError(f"ccass.json stale date: {ccass_verified.get('updated')} != {target_date}")
    if ccass_verified.get("stock_count") != len(stocks):
        raise RuntimeError(f"ccass.json stock_count mismatch: {ccass_verified.get('stock_count')} != {len(stocks)}")
    print(f"  holdings.json + ccass.json updated: {len(stocks)} stocks")
    db.close()


def main():
    global SHARD_TOTAL
    parser = argparse.ArgumentParser(description="Merge 6 shard JSONs into DB")
    parser.add_argument("--date", required=True, help="Query date YYYY-MM-DD")
    parser.add_argument(
        "--shard-total",
        type=int,
        default=SHARD_TOTAL,
        help="Total number of shard JSON files expected (default: env SHARD_TOTAL or 1)",
    )
    args = parser.parse_args()

    SHARD_TOTAL = args.shard_total

    date_str = args.date
    print(f"Merge: query_date={date_str}")

    # Restore DB from ccass.db.gz if missing (fresh GHA checkout)
    db_path = PROJECT_ROOT / "ccass.db"
    db_gz_path = PROJECT_ROOT / "ccass.db.gz"
    if not db_path.exists() or db_path.stat().st_size == 0:
        if db_gz_path.exists():
            import gzip, shutil
            print(f"Restoring holdings.db from holdings.db.gz ({db_gz_path.stat().st_size} bytes)...")
            tmp_path = db_path.with_suffix(".db.tmp")
            with gzip.open(db_gz_path, "rb") as f_in:
                with open(tmp_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            tmp_path.replace(db_path)
            print(f"Restored holdings.db: {db_path.stat().st_size} bytes")
        else:
            print("WARNING: holdings.db.gz not found — export will continue without legacy DB restore")

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

    # Trend pipeline disabled.
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Update holdings.json
    print("Updating holdings.json...")
    update_holdings_json(target_date)

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
