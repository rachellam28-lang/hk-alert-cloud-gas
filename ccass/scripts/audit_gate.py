"""
Unified audit gate for CCASS/HOLDINGS data pipeline.
All publish/deploy paths MUST pass through this gate.

Usage:
    python scripts/audit_gate.py                    # Full audit, exit 0/1/2
    python scripts/audit_gate.py --json             # Machine-readable output
    python scripts/audit_gate.py --date 2026-06-18  # Single date check
    python scripts/audit_gate.py --warn-only        # Warnings → exit 0 (for backfill)

Exit codes:
    0 = PASS (all green, safe to publish)
    1 = FAIL (errors found, BLOCK publish)
    2 = WARN (warnings only, caution)
"""

import sys, json, os, subprocess
from pathlib import Path
from datetime import date, datetime, timedelta
from collections import defaultdict

CCASS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CCASS_DIR.parent
sys.path.insert(0, str(CCASS_DIR))

from src.db import get_conn, DB_PATH

# ── Thresholds ──────────────────────────────────────────────────────────
MIN_STOCK_COUNT = 2000            # Minimum stocks expected per date
MAX_ORPHAN_DAYS = 2               # Max consecutive dates without holdings detail
MAX_ORPHAN_PCT = 5.0              # Max % of stocks with orphan rows on any date
STALE_DAYS_MAX = 3                # Max days since last DB update before warning

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Unified CCASS audit gate")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--date", help="Check a single date only")
    parser.add_argument("--warn-only", action="store_true",
                        help="Treat warnings as non-fatal (exit 0 even on WARN)")
    args = parser.parse_args()

    conn_ctx = get_conn()
    conn = conn_ctx.__enter__()

    result = {
        "status": "PASS",
        "timestamp": datetime.now().isoformat(),
        "db_path": str(DB_PATH),
        "checks": {},
    }

    # ── Check 1: DB freshness ──────────────────────────────────────────
    freshness = _check_freshness(conn)
    result["checks"]["freshness"] = freshness

    # ── Check 2: Holdings completeness — daily rows vs holdings rows ────
    completeness = _check_holdings_completeness(conn, args.date)
    result["checks"]["holdings_completeness"] = completeness

    # ── Check 3: Date coverage ──────────────────────────────────────────
    coverage = _check_date_coverage(conn)
    result["checks"]["date_coverage"] = coverage

    # ── Check 4: Run verify_data.py (subprocess) ────────────────────────
    verify_data = _run_verify_data(args.date)
    result["checks"]["verify_data"] = verify_data

    # ── Check 5: Run verify_dashboard.py (subprocess) ───────────────────
    verify_dash = _run_verify_dashboard()
    result["checks"]["verify_dashboard"] = verify_dash

    conn_ctx.__exit__(None, None, None)

    # ── Aggregate status ────────────────────────────────────────────────
    errors = []
    warnings = []

    for check_name, check in result["checks"].items():
        if check.get("status") == "FAIL":
            errors.extend(check.get("errors", []))
        elif check.get("status") == "WARN":
            warnings.extend(check.get("warnings", []))

    if errors:
        result["status"] = "FAIL"
    elif warnings:
        result["status"] = "WARN"
    else:
        result["status"] = "PASS"

    result["error_count"] = len(errors)
    result["warning_count"] = len(warnings)

    # ── Output ──────────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_summary(result)

    # ── Exit code ───────────────────────────────────────────────────────
    if result["status"] == "FAIL":
        sys.exit(1)
    elif result["status"] == "WARN":
        sys.exit(0 if args.warn_only else 2)
    sys.exit(0)


# ── Check 1: DB freshness ──────────────────────────────────────────────
def _check_freshness(conn):
    """Check that the DB has recent data."""
    result = {"status": "PASS", "errors": [], "warnings": []}

    row = conn.execute("SELECT MAX(trade_date) FROM ccass_daily").fetchone()
    latest_date = row[0] if row else None

    if not latest_date:
        result["status"] = "FAIL"
        result["errors"].append("DB has no data (ccass_daily is empty)")
        return result

    result["latest_date"] = latest_date

    # Check staleness
    try:
        latest = datetime.strptime(latest_date, "%Y-%m-%d").date()
        today = datetime.now(HKT).date()
        days_behind = (today - latest).days
        result["days_behind"] = days_behind

        if days_behind > STALE_DAYS_MAX + 2:  # Allow weekends
            result["status"] = "FAIL"
            result["errors"].append(
                f"DB is {days_behind} days stale (latest={latest_date}, today={today})"
            )
        elif days_behind > STALE_DAYS_MAX:
            result["status"] = "WARN"
            result["warnings"].append(
                f"DB is {days_behind} days behind (latest={latest_date})"
            )
    except ValueError:
        result["warnings"].append(f"Cannot parse date: {latest_date}")

    # Check stock count on latest date
    row = conn.execute(
        "SELECT COUNT(*) FROM ccass_daily WHERE trade_date = ?", [latest_date]
    ).fetchone()
    latest_count = row[0] if row else 0
    result["latest_stock_count"] = latest_count

    if latest_count < MIN_STOCK_COUNT:
        result["status"] = "FAIL"
        result["errors"].append(
            f"Only {latest_count} stocks on latest date {latest_date} (min={MIN_STOCK_COUNT})"
        )

    return result


# ── Check 2: Holdings completeness ─────────────────────────────────────
def _check_holdings_completeness(conn, filter_date=None):
    """Check that every daily row has corresponding holdings detail rows."""
    result = {"status": "PASS", "errors": [], "warnings": [], "orphan_dates": []}

    where = ""
    params = []
    if filter_date:
        where = "WHERE d.trade_date = ?"
        params = [filter_date]

    # Find dates where daily exists but no holdings
    rows = conn.execute(f"""
        SELECT d.trade_date, COUNT(DISTINCT d.stock_code) as daily_count,
               COUNT(DISTINCT h.stock_code) as holdings_count
        FROM ccass_daily d
        LEFT JOIN ccass_holdings h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
        {where}
        GROUP BY d.trade_date
        HAVING daily_count > holdings_count
        ORDER BY d.trade_date DESC
    """, params).fetchall()

    for trade_date, daily_cnt, holdings_cnt in rows:
        missing = daily_cnt - holdings_cnt
        pct = (missing / daily_cnt * 100) if daily_cnt > 0 else 0

        entry = {
            "date": trade_date,
            "daily_stocks": daily_cnt,
            "with_holdings": holdings_cnt,
            "missing": missing,
            "missing_pct": round(pct, 1),
        }

        if pct > MAX_ORPHAN_PCT:
            result["status"] = "FAIL"
            result["errors"].append(
                f"{trade_date}: {missing}/{daily_cnt} stocks ({pct:.1f}%) missing holdings detail"
            )
            entry["severity"] = "error"
        elif missing > 0:
            result["status"] = "WARN"
            result["warnings"].append(
                f"{trade_date}: {missing}/{daily_cnt} stocks missing holdings detail"
            )
            entry["severity"] = "warning"

        result["orphan_dates"].append(entry)

    if not rows:
        result["status"] = "PASS"

    return result


# ── Check 3: Date coverage ─────────────────────────────────────────────
def _check_date_coverage(conn):
    """Check for suspicious gaps in trade dates."""
    result = {"status": "PASS", "errors": [], "warnings": []}

    rows = conn.execute("""
        SELECT trade_date, COUNT(DISTINCT stock_code) as n
        FROM ccass_daily
        GROUP BY trade_date
        ORDER BY trade_date
    """).fetchall()

    if not rows:
        return result

    dates = [(r[0], r[1]) for r in rows]
    counts = [c for _, c in dates]

    if counts:
        median_count = sorted(counts)[len(counts) // 2]
        result["median_stocks_per_date"] = median_count
        result["total_dates"] = len(dates)

        for td, n in dates:
            if median_count > 0 and n < median_count * 0.5:
                result["warnings"].append(
                    f"{td}: only {n} stocks (median={median_count})"
                )
                if result["status"] == "PASS":
                    result["status"] = "WARN"

    return result


# ── Check 4: Run verify_data.py ────────────────────────────────────────
def _run_verify_data(filter_date=None):
    """Run verify_data.py as subprocess and parse output."""
    result = {"status": "PASS", "errors": [], "warnings": []}

    cmd = [sys.executable, str(CCASS_DIR / "scripts" / "verify_data.py"), "--json"]
    if filter_date:
        cmd.extend(["--date", filter_date])

    try:
        r = subprocess.run(cmd, cwd=str(CCASS_DIR), capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            result["status"] = "PASS"
        elif r.returncode == 1:
            result["status"] = "FAIL"
        elif r.returncode == 2:
            result["status"] = "WARN"
        else:
            result["status"] = "FAIL"
            result["errors"].append(f"verify_data.py crashed (rc={r.returncode}): {r.stderr[-300:]}")

        if r.stdout.strip():
            try:
                data = json.loads(r.stdout)
                result["verify_data_output"] = data
                for e in data.get("errors", []):
                    result["errors"].append(f"[verify_data] {e.get('stock','?')} {e.get('date','?')}: {e.get('detail','')}")
                for w in data.get("warnings", [])[:10]:  # cap warnings from this sub-check
                    result["warnings"].append(f"[verify_data] {w.get('stock','?')} {w.get('date','?')}: {w.get('detail','')}")
            except json.JSONDecodeError:
                result["errors"].append(f"verify_data.py returned non-JSON: {r.stdout[:200]}")
    except subprocess.TimeoutExpired:
        result["status"] = "FAIL"
        result["errors"].append("verify_data.py timed out (120s)")
    except Exception as e:
        result["status"] = "FAIL"
        result["errors"].append(f"verify_data.py failed to run: {e}")

    return result


# ── Check 5: Run verify_dashboard.py ───────────────────────────────────
def _run_verify_dashboard():
    """Run verify_dashboard.py as subprocess and parse output."""
    result = {"status": "PASS", "errors": [], "warnings": []}

    cmd = [sys.executable, str(CCASS_DIR / "scripts" / "verify_dashboard.py")]

    try:
        r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            result["status"] = "PASS"
        elif r.returncode == 1:
            result["status"] = "FAIL"
        elif r.returncode == 2:
            result["status"] = "WARN"
        else:
            result["status"] = "FAIL"
            result["errors"].append(f"verify_dashboard.py crashed (rc={r.returncode})")

        if r.stdout.strip():
            try:
                data = json.loads(r.stdout)
                result["verify_dashboard_output"] = data
                for e in data.get("errors", []):
                    result["errors"].append(f"[dashboard] {e}")
                wc = len(data.get("warnings", []))
                if wc > 0:
                    result["warnings"].append(f"[dashboard] {wc} py_pct mismatch warnings (see full verify_dashboard.py output)")
                    result["summary"] = data.get("summary", {})
            except json.JSONDecodeError:
                result["errors"].append(f"verify_dashboard.py returned non-JSON")
    except subprocess.TimeoutExpired:
        result["status"] = "FAIL"
        result["errors"].append("verify_dashboard.py timed out (60s)")
    except Exception as e:
        result["status"] = "FAIL"
        result["errors"].append(f"verify_dashboard.py failed to run: {e}")

    return result


# ── Human-readable summary ─────────────────────────────────────────────
def _print_summary(result):
    """Print a clean one-line summary + details."""
    status = result["status"]
    icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}.get(status, "?")
    errors = result.get("error_count", 0)
    warnings = result.get("warning_count", 0)

    print(f"\n{'='*60}")
    print(f"  AUDIT GATE — {icon} {status}  ({errors} errors, {warnings} warnings)")
    print(f"{'='*60}")

    # Freshness
    f = result["checks"].get("freshness", {})
    print(f"\n  DB Freshness:  latest={f.get('latest_date','?')}, "
          f"stocks={f.get('latest_stock_count','?')}, "
          f"behind={f.get('days_behind','?')}d")

    # Holdings completeness
    hc = result["checks"].get("holdings_completeness", {})
    orphan_dates = hc.get("orphan_dates", [])
    if orphan_dates:
        print(f"\n  Holdings Gaps ({len(orphan_dates)} dates with missing detail):")
        for od in orphan_dates[:10]:
            print(f"    {od['date']}: {od['missing']}/{od['daily_stocks']} stocks "
                  f"({od['missing_pct']:.1f}%) missing holdings — {od.get('severity','?')}")

    # Coverage
    dc = result["checks"].get("date_coverage", {})
    print(f"\n  Date Coverage: {dc.get('total_dates','?')} dates, "
          f"median={dc.get('median_stocks_per_date','?')} stocks/date")

    # Verify data
    vd = result["checks"].get("verify_data", {})
    print(f"  verify_data.py: {vd.get('status','?')}")

    # Verify dashboard
    vdb = result["checks"].get("verify_dashboard", {})
    dash_summary = vdb.get("summary", {})
    if dash_summary:
        print(f"  verify_dashboard.py: {vdb.get('status','?')} — "
              f"{dash_summary.get('total_stocks','?')} stocks, "
              f"lp={dash_summary.get('with_lp','?')}, "
              f"py={dash_summary.get('with_py','?')}")

    # Errors
    if result["status"] in ("FAIL",):
        print(f"\n  ── ERRORS (BLOCKING) ──")
        for check_name, check in result["checks"].items():
            for e in check.get("errors", []):
                print(f"  [{check_name}] {e}")

    print(f"\n{'='*60}")
    print(f"  GATE RESULT: {status} → {'PUBLISH OK' if status == 'PASS' else 'PUBLISH BLOCKED' if status == 'FAIL' else 'PUBLISH WITH CAUTION'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
