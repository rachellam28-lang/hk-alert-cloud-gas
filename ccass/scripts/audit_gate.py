"""Unified publish gate for HOLDINGS outputs.

Runs data/dashboard verification, checks freshness against the DB, and fails
fast if the latest publish is stale or the trading-day timeline has gaps.

Usage:
    python scripts/audit_gate.py
    python scripts/audit_gate.py --strict
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str((Path(__file__).resolve().parent.parent)))
from src.db import DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CCASS_DIR = PROJECT_ROOT / "ccass"
PYTHON = sys.executable


def _run_json_script(script: str, *args: str) -> tuple[dict, int, str, str]:
    cmd = [PYTHON, script, *args]
    proc = subprocess.run(cmd, cwd=CCASS_DIR, capture_output=True, text=True)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        raise RuntimeError(f"{script} produced no stdout")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{script} did not return JSON: {exc}\nSTDOUT:\n{stdout[-1000:]}\nSTDERR:\n{stderr[-1000:]}") from exc
    return payload, proc.returncode, stdout, stderr


def _latest_db_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(trade_date)
        FROM ccass_daily
        WHERE validation_failed = 0
        """
    ).fetchone()
    return row[0] if row and row[0] else None


def _latest_db_coverage(conn: sqlite3.Connection, trade_date: str) -> tuple[int, int, float | None]:
    count_row = conn.execute(
        """
        SELECT COUNT(DISTINCT stock_code)
        FROM ccass_daily
        WHERE trade_date = ? AND validation_failed = 0
        """,
        (trade_date,),
    ).fetchone()
    total_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM stock_universe
        WHERE is_active=1
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """
    ).fetchone()
    count = int(count_row[0] or 0)
    total = int(total_row[0] or 0)
    pct = round((count / total) * 100, 1) if total else None
    return count, total, pct


def _latest_publishable_db_date(conn: sqlite3.Connection, min_coverage: float) -> tuple[str | None, int | None, float | None]:
    rows = conn.execute(
        """
        SELECT trade_date, COUNT(DISTINCT stock_code) AS stock_count
        FROM ccass_daily
        WHERE validation_failed = 0
        GROUP BY trade_date
        ORDER BY trade_date DESC
        """
    ).fetchall()
    for trade_date, _ in rows:
        count, _, pct = _latest_db_coverage(conn, trade_date)
        if pct is not None and pct >= min_coverage:
            return trade_date, count, pct
    return None, None, None


def _date_set(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT trade_date
        FROM ccass_daily
        WHERE validation_failed = 0
        ORDER BY trade_date
        """
    ).fetchall()
    return {r[0] for r in rows if r and r[0]}


def _missing_trading_days(start_iso: str, end_iso: str, present: set[str]) -> list[str]:
    from src.trading_calendar import is_trading_day

    missing: list[str] = []
    cur = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    while cur <= end:
        if is_trading_day(cur) and cur.isoformat() not in present:
            missing.append(cur.isoformat())
        cur += timedelta(days=1)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified audit gate for publish/deploy")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    parser.add_argument("--min-coverage", type=float, default=99.0, help="Minimum coverage_pct required for publish")
    args = parser.parse_args()

    holdings_path = PROJECT_ROOT / "holdings.json"
    ccass_path = PROJECT_ROOT / "ccass.json"
    errors: list[str] = []
    warnings: list[str] = []

    if not holdings_path.exists():
        errors.append(f"Missing file: {holdings_path}")
        holdings = {}
    else:
        try:
            holdings = json.loads(holdings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Failed to parse holdings.json: {exc}")
            holdings = {}

    if not ccass_path.exists():
        errors.append(f"Missing file: {ccass_path}")
        ccass = {}
    else:
        try:
            ccass = json.loads(ccass_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Failed to parse ccass.json: {exc}")
            ccass = {}

    conn = sqlite3.connect(str(DB_PATH))
    try:
        latest_db = _latest_db_date(conn)
        latest_db_stock_count = None
        latest_db_coverage_pct = None
        if latest_db:
            latest_db_stock_count, _, latest_db_coverage_pct = _latest_db_coverage(conn, latest_db)
        publishable_db, publishable_count, publishable_coverage_pct = _latest_publishable_db_date(conn, args.min_coverage)
        present_dates = _date_set(conn)
    finally:
        conn.close()

    holdings_updated = holdings.get("updated")
    coverage_pct = holdings.get("coverage_pct")
    is_complete = holdings.get("is_complete")
    stock_count = holdings.get("stock_count")

    # Freshness checks
    if not latest_db:
        errors.append("Database has no validated trading dates")
    if not publishable_db:
        errors.append(f"No DB date reaches publish coverage threshold {args.min_coverage}")
    if holdings_updated and publishable_db and holdings_updated != publishable_db:
        errors.append(f"holdings.json.updated={holdings_updated} != latest publishable DB date {publishable_db}")
    if latest_db and publishable_db and latest_db != publishable_db:
        warnings.append(
            f"latest DB date {latest_db} is partial ({latest_db_coverage_pct}%), "
            f"publishing latest complete date {publishable_db}"
        )
    if ccass.get("updated") and holdings_updated and ccass["updated"] != holdings_updated:
        errors.append(f"ccass.json.updated={ccass['updated']} != holdings.json.updated={holdings_updated}")
    if ccass.get("stock_count") is not None and stock_count is not None and ccass["stock_count"] != stock_count:
        errors.append(f"ccass.json.stock_count={ccass['stock_count']} != holdings.json.stock_count={stock_count}")

    if coverage_pct is None:
        errors.append("holdings.json missing coverage_pct")
    elif float(coverage_pct) < args.min_coverage:
        errors.append(f"coverage_pct={coverage_pct} below threshold {args.min_coverage}")
    elif not isinstance(is_complete, bool):
        warnings.append("holdings.json.is_complete is missing or non-bool")

    # Timeline continuity check across the current DB range.
    if present_dates:
        start_db = min(present_dates)
        end_db = publishable_db or max(present_dates)
        missing_days = _missing_trading_days(start_db, end_db, present_dates)
        if missing_days:
            errors.append(
                f"Missing trading days in DB range {start_db}..{end_db}: "
                + ", ".join(missing_days[:12])
                + (" ..." if len(missing_days) > 12 else "")
            )
        if publishable_db and latest_db and publishable_db != latest_db:
            tail_missing = _missing_trading_days(publishable_db, latest_db, present_dates)
            tail_missing = [d for d in tail_missing if d != publishable_db]
            if tail_missing:
                warnings.append(
                    f"Incomplete tail after publishable date {publishable_db}: "
                    + ", ".join(tail_missing[:12])
                    + (" ..." if len(tail_missing) > 12 else "")
                )

    # Run the existing verifiers.
    data_report, data_rc, _, _ = _run_json_script("scripts/verify_data.py", "--json")
    dash_report, dash_rc, _, _ = _run_json_script("scripts/verify_dashboard.py")

    if data_report.get("errors"):
        errors.append(f"verify_data errors={len(data_report['errors'])}")
    if dash_report.get("status") == "FAIL" or dash_rc != 0:
        errors.append("verify_dashboard failed")

    if data_report.get("warnings"):
        warnings.append(f"verify_data warnings={len(data_report['warnings'])}")
    if dash_report.get("status") == "WARN":
        warnings.append("verify_dashboard WARN")

    report = {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "latest_db_date": latest_db,
        "latest_db_stock_count": latest_db_stock_count,
        "latest_db_coverage_pct": latest_db_coverage_pct,
        "latest_publishable_date": publishable_db,
        "latest_publishable_stock_count": publishable_count,
        "latest_publishable_coverage_pct": publishable_coverage_pct,
        "holdings_updated": holdings_updated,
        "coverage_pct": coverage_pct,
        "stock_count": stock_count,
        "errors": errors,
        "warnings": warnings,
        "verify_data": {
            "status": data_report.get("status"),
            "errors": len(data_report.get("errors", [])),
            "warnings": len(data_report.get("warnings", [])),
        },
        "verify_dashboard": {
            "status": dash_report.get("status"),
            "errors": len(dash_report.get("errors", [])),
            "warnings": len(dash_report.get("warnings", [])),
        },
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
