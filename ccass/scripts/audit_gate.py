"""Unified publish gate for HOLDINGS outputs.

Runs data/dashboard verification and checks freshness against the DB. The gate
fails on current publish-data errors; historical gaps stay visible as backlog
warnings so stale old rows do not block today's page refresh.

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
from statistics import median

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

sys.path.insert(0, str((Path(__file__).resolve().parent.parent)))
from src.db import DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CCASS_DIR = PROJECT_ROOT / "ccass"
PYTHON = sys.executable
PUBLISH_SCOPE_PATTERNS = ("029%", "04%", "8%")


def _run_json_script(script: str, *args: str) -> tuple[dict, int, str, str]:
    cmd = [PYTHON, script, *args]
    proc = subprocess.run(
        cmd,
        cwd=CCASS_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
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


def _publish_scope_predicate(alias: str | None = None) -> str:
    col = f"{alias}.stock_code" if alias else "stock_code"
    return " AND ".join(f"{col} NOT LIKE '{pattern}'" for pattern in PUBLISH_SCOPE_PATTERNS)


def _latest_db_coverage(conn: sqlite3.Connection, trade_date: str) -> tuple[int, int, float | None]:
    count_row = conn.execute(
        """
        SELECT COUNT(DISTINCT stock_code)
        FROM ccass_daily
        WHERE trade_date = ? AND validation_failed = 0
          AND total_shares > 0
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
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
        SELECT trade_date,
               COUNT(DISTINCT CASE WHEN total_shares > 0 THEN stock_code END) AS stock_count
        FROM ccass_daily
        WHERE validation_failed = 0
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
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


def _local_expected_count(counts: list[int], index: int) -> float:
    """Median of the nearest complete dates, excluding obvious partial runs."""
    if not counts:
        return 0.0
    complete_floor = max(counts) * 0.8
    complete_indexes = [i for i, count in enumerate(counts) if count >= complete_floor]
    before = [i for i in complete_indexes if i <= index][-3:]
    after = [i for i in complete_indexes if i > index][:3]
    reference_counts = [counts[i] for i in before + after]
    return float(median(reference_counts)) if reference_counts else 0.0


def _date_coverages(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT trade_date,
               COUNT(DISTINCT CASE WHEN total_shares > 0 THEN stock_code END) AS stock_count
        FROM ccass_daily
        WHERE validation_failed = 0
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchall()
    out: dict[str, float] = {}
    counts = [int(row[1] or 0) for row in rows]
    for index, (trade_date, stock_count) in enumerate(rows):
        expected = _local_expected_count(counts, index)
        out[str(trade_date)] = min(float(stock_count) / expected, 1.0) if expected else 0.0
    return out


def _date_participant_coverages(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        """
        WITH aggregate_rows AS (
            SELECT trade_date, COUNT(DISTINCT stock_code) AS stock_count
            FROM ccass_daily
            WHERE validation_failed = 0
              AND total_shares > 0
              AND stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04%'
              AND stock_code NOT LIKE '8%'
            GROUP BY trade_date
        ), participant_rows AS (
            SELECT trade_date, COUNT(DISTINCT stock_code) AS stock_count
            FROM ccass_holdings
            WHERE stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04%'
              AND stock_code NOT LIKE '8%'
            GROUP BY trade_date
        )
        SELECT a.trade_date, a.stock_count, COALESCE(p.stock_count, 0)
        FROM aggregate_rows a
        LEFT JOIN participant_rows p ON p.trade_date = a.trade_date
        ORDER BY a.trade_date
        """
    ).fetchall()
    return {
        str(trade_date): min(float(participant_count) / float(aggregate_count), 1.0)
        if aggregate_count else 0.0
        for trade_date, aggregate_count, participant_count in rows
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


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


def _load_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing file: {path.relative_to(PROJECT_ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON: {path.relative_to(PROJECT_ROOT)}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"expected object JSON: {path.relative_to(PROJECT_ROOT)}")
    return data


def _alias_meta(data: dict, fields: tuple[str, ...]) -> dict:
    out = {field: data.get(field) for field in fields}
    stocks = data.get("stocks")
    if isinstance(stocks, list):
        out["stocks_len"] = len(stocks)
    return out


def _check_publish_aliases(errors: list[str]) -> None:
    pairs = [
        ("holdings.json", "data/holdings.json", ("updated", "stock_count", "coverage_pct")),
        ("ccass.json", "data/ccass.json", ("updated", "stock_count", "coverage_pct")),
        ("market.json", "data/market.json", ("updated_at",)),
    ]
    for src_rel, dst_rel, fields in pairs:
        try:
            src = _load_json_file(PROJECT_ROOT / src_rel)
            dst = _load_json_file(PROJECT_ROOT / dst_rel)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        src_meta = _alias_meta(src, fields)
        dst_meta = _alias_meta(dst, fields)
        if src_meta != dst_meta:
            errors.append(f"{dst_rel} metadata mismatch {dst_meta} != {src_rel} {src_meta}")


def _transfer_snapshot_date(data: dict) -> str | None:
    date_value = data.get("date")
    if date_value:
        return str(date_value)[:10]
    updated = data.get("updated")
    if isinstance(updated, str) and " vs " in updated:
        return updated.split(" vs ", 1)[0][:10]
    if isinstance(updated, str) and len(updated) >= 10:
        return updated[:10]
    return None


def _check_transfer_freshness(holdings_updated: str | None, errors: list[str]) -> None:
    try:
        root = _load_json_file(PROJECT_ROOT / "data" / "transfers.json")
        ccass = _load_json_file(PROJECT_ROOT / "ccass" / "data" / "transfers.json")
    except RuntimeError as exc:
        errors.append(str(exc))
        return

    root_meta = {
        "updated": root.get("updated"),
        "date": _transfer_snapshot_date(root),
        "count": root.get("count"),
    }
    ccass_meta = {
        "updated": ccass.get("updated"),
        "date": _transfer_snapshot_date(ccass),
        "count": ccass.get("count"),
    }
    if root_meta != ccass_meta:
        errors.append(f"ccass/data/transfers.json metadata mismatch {ccass_meta} != data/transfers.json {root_meta}")

    transfer_date = root_meta["date"]
    if holdings_updated and transfer_date != str(holdings_updated)[:10]:
        errors.append(f"data/transfers.json date={transfer_date} != holdings.json.updated={holdings_updated}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified audit gate for publish/deploy")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    parser.add_argument("--min-coverage", type=float, default=98.0, help="Minimum trusted Market%% coverage required for publish")
    args = parser.parse_args()

    holdings_path = PROJECT_ROOT / "holdings.json"
    ccass_path = PROJECT_ROOT / "ccass.json"
    errors: list[str] = []
    warnings: list[str] = []
    maintenance_warnings: list[str] = []

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

    latest_db = None
    latest_db_stock_count = None
    latest_db_coverage_pct = None
    publishable_db = None
    publishable_count = None
    publishable_coverage_pct = None
    present_dates: set[str] = set()
    date_coverages: dict[str, float] = {}
    participant_coverages: dict[str, float] = {}
    conn = sqlite3.connect(str(DB_PATH))
    try:
        if not _table_exists(conn, "ccass_daily") or not _table_exists(conn, "stock_universe"):
            errors.append(f"Database schema missing at {DB_PATH}")
        else:
            latest_db = _latest_db_date(conn)
            if latest_db:
                latest_db_stock_count, _, latest_db_coverage_pct = _latest_db_coverage(conn, latest_db)
            publishable_db, publishable_count, publishable_coverage_pct = _latest_publishable_db_date(conn, args.min_coverage)
            present_dates = _date_set(conn)
            date_coverages = _date_coverages(conn)
            participant_coverages = _date_participant_coverages(conn)
    except sqlite3.Error as exc:
        errors.append(f"Database audit failed: {exc}")
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
    _check_publish_aliases(errors)
    _check_transfer_freshness(holdings_updated, errors)

    if coverage_pct is None:
        errors.append("holdings.json missing coverage_pct")
    elif float(coverage_pct) < args.min_coverage:
        errors.append(f"coverage_pct={coverage_pct} below threshold {args.min_coverage}")
    elif not isinstance(is_complete, bool):
        warnings.append("holdings.json.is_complete is missing or non-bool")

    # Timeline continuity check across the current DB range. Historical gaps are
    # backlog warnings; the current publish date/coverage checks above decide
    # whether today's output is deployable.
    if present_dates:
        start_db = min(present_dates)
        end_db = publishable_db or max(present_dates)
        missing_days = _missing_trading_days(start_db, end_db, present_dates)
        if missing_days:
            maintenance_warnings.append(
                f"Historical DB gaps in range {start_db}..{end_db}: "
                + ", ".join(missing_days[:12])
                + (" ..." if len(missing_days) > 12 else "")
            )
        incomplete_days = [
            trade_date
            for trade_date, cov in sorted(date_coverages.items(), reverse=True)
            if start_db <= trade_date <= end_db and cov * 100 < args.min_coverage
        ]
        if incomplete_days:
            maintenance_warnings.append(
                f"Historical low-coverage DB dates below {args.min_coverage}%: "
                + ", ".join(incomplete_days[:12])
                + (" ..." if len(incomplete_days) > 12 else "")
            )
        incomplete_participant_days = [
            trade_date
            for trade_date, cov in sorted(participant_coverages.items(), reverse=True)
            if start_db <= trade_date <= end_db and cov * 100 < args.min_coverage
        ]
        if incomplete_participant_days:
            maintenance_warnings.append(
                f"Historical low participant-detail coverage below {args.min_coverage}%: "
                + ", ".join(incomplete_participant_days[:12])
                + (" ..." if len(incomplete_participant_days) > 12 else "")
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
            tail_incomplete = [
                trade_date
                for trade_date, cov in sorted(date_coverages.items(), reverse=True)
                if publishable_db < trade_date <= latest_db and cov * 100 < args.min_coverage
            ]
            if tail_incomplete:
                warnings.append(
                    f"Low-coverage tail after publishable date {publishable_db}: "
                    + ", ".join(tail_incomplete[:12])
                    + (" ..." if len(tail_incomplete) > 12 else "")
                )

    # Run verifiers. Date-scoped data verification gates the current publish;
    # full-history verification is reported as backlog only.
    verify_date = str(holdings_updated or publishable_db or "")
    try:
        if not verify_date:
            raise RuntimeError("No holdings/publishable date available for verify_data")
        data_report, data_rc, _, _ = _run_json_script("scripts/verify_data.py", "--date", verify_date, "--json", "--publish-scope")
    except Exception as exc:
        data_report, data_rc = {"status": "FAIL", "errors": [str(exc)], "warnings": []}, 1
        errors.append(f"verify_data failed to run: {exc}")
    try:
        history_report, history_rc, _, _ = _run_json_script("scripts/verify_data.py", "--json", "--publish-scope")
    except Exception as exc:
        history_report, history_rc = {"status": "FAIL", "errors": [str(exc)], "warnings": []}, 1
        maintenance_warnings.append(f"historical verify_data failed to run: {exc}")
    try:
        dash_report, dash_rc, _, _ = _run_json_script("scripts/verify_dashboard.py")
    except Exception as exc:
        dash_report, dash_rc = {"status": "FAIL", "errors": [str(exc)], "warnings": []}, 1
        errors.append(f"verify_dashboard failed to run: {exc}")

    if data_report.get("errors"):
        errors.append(f"verify_data {verify_date} errors={len(data_report['errors'])}")
    if dash_report.get("status") == "FAIL" or dash_rc != 0:
        errors.append("verify_dashboard failed")

    if data_report.get("warnings"):
        warnings.append(f"verify_data {verify_date} warnings={len(data_report['warnings'])}")
    if history_report.get("errors"):
        maintenance_warnings.append(
            "historical verify_data backlog "
            f"errors={len(history_report.get('errors', []))} "
            f"warnings={len(history_report.get('warnings', []))}"
        )
    history_warning_counts: dict[str, int] = {}
    for item in history_report.get("warnings", []):
        check = str(item.get("check") or "unknown")
        history_warning_counts[check] = history_warning_counts.get(check, 0) + 1
    if dash_report.get("status") == "WARN":
        warnings.append("verify_dashboard WARN")

    publish_status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    maintenance_status = "WARN" if maintenance_warnings else "PASS"
    report = {
        # status remains the full audit result for backwards compatibility.
        # publish_status is the current operational gate used by the dashboard.
        "status": "FAIL" if errors else ("WARN" if warnings or maintenance_warnings else "PASS"),
        "publish_status": publish_status,
        "maintenance_status": maintenance_status,
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
        "warnings": warnings + maintenance_warnings,
        "current_warnings": warnings,
        "maintenance_warnings": maintenance_warnings,
        "verify_data": {
            "date": verify_date or None,
            "status": "FAIL" if data_report.get("errors") else ("WARN" if data_report.get("warnings") else "PASS"),
            "errors": len(data_report.get("errors", [])),
            "warnings": len(data_report.get("warnings", [])),
        },
        "historical_verify_data": {
            "status": "FAIL" if history_report.get("errors") else ("WARN" if history_report.get("warnings") else "PASS"),
            "errors": len(history_report.get("errors", [])),
            "warnings": len(history_report.get("warnings", [])),
            "warning_counts": history_warning_counts,
            "classification": "observations; coverage and participant gaps are gated separately",
        },
        "verify_dashboard": {
            "status": dash_report.get("status"),
            "errors": len(dash_report.get("errors", [])),
            "warnings": len(dash_report.get("warnings", [])),
        },
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors or (args.strict and (warnings or maintenance_warnings)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
