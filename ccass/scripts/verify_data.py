"""
HOLDINGS Data Accuracy Verification System
========================================
Runs after every backfill to verify data integrity.
Usage:
    python -m scripts.verify_data
    python -m scripts.verify_data --stock 00328   # single stock deep check
    python -m scripts.verify_data --date 2026-05-28  # single date check
    python -m scripts.verify_data --json          # machine-readable output
"""

from __future__ import annotations
import argparse
import json
import sys
import os
from datetime import date, timedelta
from collections import defaultdict
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.db import get_conn, DB_PATH
from src.logger import setup_logger
import sqlite3

logger = setup_logger("verify_data")

# ── Thresholds ──────────────────────────────────────────────────────────
MAX_PCT_DROP_DAY = 30.0       # Max % drop in total_pct day-over-day (alerts for corporate actions)
MAX_PCT_JUMP_DAY = 30.0       # Max % jump in total_pct day-over-day
MAX_PCT_VS_HOLDINGS_DIFF = 5.0  # Max diff between total_pct and SUM(pct_of_issued)
MAX_SHARES_VS_HOLDINGS_PCT = 2.0  # Max % diff between total_shares and SUM(holdings.shares)
MIN_PARTICIPANTS = 1          # Minimum expected participants for a stock with shares
MAX_TOTAL_PCT = 100.0
MIN_TOTAL_PCT = 0.0


class VerificationResult:
    """Collects all verification findings categorised by severity."""

    def __init__(self):
        self.errors: list[dict] = []      # Definitely wrong data
        self.warnings: list[dict] = []    # Suspicious but could be legitimate
        self.info: list[dict] = []        # Informational anomalies
        self.stats: dict[str, Any] = {}   # Aggregate statistics

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> dict:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "stats": self.stats,
        }


def run_all_checks(conn: sqlite3.Connection, result: VerificationResult,
                   filter_stock: str | None = None,
                   filter_date: str | None = None) -> None:
    """Run all verification checks in sequence."""

    # ── Check 1: Basic range validation ─────────────────────────────────
    _check_range_validation(conn, result, filter_stock, filter_date)

    # ── Check 2: Pct consistency — total_pct vs holdings SUM(pct_of_issued) ──
    _check_pct_consistency(conn, result, filter_stock, filter_date)

    # ── Check 3: Shares consistency — total_shares vs SUM(holdings.shares) ──
    _check_shares_consistency(conn, result, filter_stock, filter_date)

    # ── Check 4: Day-over-day anomaly detection ─────────────────────────
    _check_daily_jumps(conn, result, filter_stock, filter_date)

    # ── Check 5: Date coverage gaps ─────────────────────────────────────
    _check_coverage_gaps(conn, result, filter_stock, filter_date)

    # ── Check 6: Zero/missing participant counts ─────────────────────────
    _check_participant_counts(conn, result, filter_stock, filter_date)

    # ── Check 7: holdings per stock vs daily row existence ──────────────
    _check_orphan_rows(conn, result, filter_stock, filter_date)

    # ── Check 8: Concentration metrics sanity ───────────────────────────
    _check_concentration_metrics(conn, result, filter_stock, filter_date)


def _add_filter(stock: str | None, date_val: str | None) -> tuple[str, list]:
    """Build WHERE clause and params from optional filters.
    Returns (where_clause, params). When no filters, returns 'WHERE 1=1' so
    subsequent AND conditions work seamlessly."""
    clauses = []
    params = []
    if stock:
        clauses.append("d.stock_code = ?")
        params.append(stock)
    if date_val:
        clauses.append("d.trade_date = ?")
        params.append(date_val)
    if clauses:
        return "WHERE " + " AND ".join(clauses), params
    return "WHERE 1=1", params


# ── Check 1: Basic range validation ─────────────────────────────────────
def _check_range_validation(conn, result, stock, date_val):
    where, params = _add_filter(stock, date_val)

    # total_pct out of range
    rows = conn.execute(f"""
        SELECT stock_code, trade_date, total_pct, total_shares
        FROM holdings_daily d
        {where}
        AND (total_pct < {MIN_TOTAL_PCT} OR total_pct > {MAX_TOTAL_PCT})
        ORDER BY trade_date, stock_code
    """, params).fetchall()

    for r in rows:
        result.errors.append({
            "check": "range_validation",
            "severity": "error",
            "stock": r[0],
            "date": r[1],
            "detail": f"total_pct={r[2]} out of range [0, 100]",
        })

    # total_shares negative or zero for stocks that should have data
    rows = conn.execute(f"""
        SELECT stock_code, trade_date, total_shares
        FROM holdings_daily d
        {where}
        AND total_shares <= 0
        ORDER BY trade_date, stock_code
    """, params).fetchall()

    for r in rows:
        result.errors.append({
            "check": "range_validation",
            "severity": "error",
            "stock": r[0],
            "date": r[1],
            "detail": f"total_shares={r[2]} (expected >0)",
        })


# ── Check 2: Pct consistency ────────────────────────────────────────────
def _check_pct_consistency(conn, result, stock, date_val):
    where, params = _add_filter(stock, date_val)
    stock_where = "AND d.stock_code = ?" if stock else ""
    stock_params = [stock] if stock else []

    # Join daily with holdings sum
    query = f"""
        SELECT d.stock_code, d.trade_date,
               ROUND(d.total_pct, 2) as total_pct,
               ROUND(COALESCE(h.sum_pct, 0), 2) as holdings_sum_pct,
               ROUND(COALESCE(d.total_pct - h.sum_pct, 999), 2) as diff,
               d.total_shares
        FROM holdings_daily d
        LEFT JOIN (
            SELECT stock_code, trade_date, SUM(pct_of_issued) as sum_pct
            FROM holdings_holdings
            WHERE 1=1 {stock_where}
            GROUP BY stock_code, trade_date
        ) h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
        {where}
        ORDER BY ABS(COALESCE(d.total_pct - h.sum_pct, 999)) DESC
    """

    # Need to handle the double stock_code filter carefully
    if stock:
        rows = conn.execute(f"""
            SELECT d.stock_code, d.trade_date,
                   ROUND(d.total_pct, 2) as total_pct,
                   ROUND(COALESCE(h.sum_pct, 0), 2) as holdings_sum_pct,
                   ROUND(COALESCE(d.total_pct - h.sum_pct, 999), 2) as diff,
                   d.total_shares
            FROM holdings_daily d
            LEFT JOIN (
                SELECT stock_code, trade_date, SUM(pct_of_issued) as sum_pct
                FROM holdings_holdings
                WHERE stock_code = ?
                GROUP BY stock_code, trade_date
            ) h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
            WHERE d.stock_code = ?
            ORDER BY ABS(COALESCE(d.total_pct - h.sum_pct, 999)) DESC
        """, [stock, stock]).fetchall()
    elif date_val:
        rows = conn.execute(f"""
            SELECT d.stock_code, d.trade_date,
                   ROUND(d.total_pct, 2) as total_pct,
                   ROUND(COALESCE(h.sum_pct, 0), 2) as holdings_sum_pct,
                   ROUND(COALESCE(d.total_pct - h.sum_pct, 999), 2) as diff,
                   d.total_shares
            FROM holdings_daily d
            LEFT JOIN (
                SELECT stock_code, trade_date, SUM(pct_of_issued) as sum_pct
                FROM holdings_holdings
                WHERE trade_date = ?
                GROUP BY stock_code, trade_date
            ) h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
            WHERE d.trade_date = ?
            ORDER BY ABS(COALESCE(d.total_pct - h.sum_pct, 999)) DESC
        """, [date_val, date_val]).fetchall()
    else:
        rows = conn.execute("""
            SELECT d.stock_code, d.trade_date,
                   ROUND(d.total_pct, 2) as total_pct,
                   ROUND(COALESCE(h.sum_pct, 0), 2) as holdings_sum_pct,
                   ROUND(COALESCE(d.total_pct - h.sum_pct, 999), 2) as diff,
                   d.total_shares
            FROM holdings_daily d
            LEFT JOIN (
                SELECT stock_code, trade_date, SUM(pct_of_issued) as sum_pct
                FROM holdings_holdings
                GROUP BY stock_code, trade_date
            ) h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
            WHERE d.total_pct > 0 AND COALESCE(h.sum_pct, 0) > 0
              AND ABS(COALESCE(d.total_pct - h.sum_pct, 999)) > ?
            ORDER BY ABS(COALESCE(d.total_pct - h.sum_pct, 999)) DESC
            LIMIT 100
        """, [MAX_PCT_VS_HOLDINGS_DIFF]).fetchall()

    for r in rows:
        sc, td, tp, hs, diff, ts = r
        entry = {
            "check": "pct_consistency",
            "stock": sc,
            "date": td,
            "total_pct": tp,
            "holdings_sum_pct": hs,
            "diff": diff,
        }
        if diff is None or diff > 999:
            # No holdings data at all
            entry["severity"] = "warning"
            entry["detail"] = f"No holdings data exists for {sc} on {td}"
            result.warnings.append(entry)
        elif abs(diff) > 50:
            entry["severity"] = "error"
            entry["detail"] = f"Massive pct mismatch: daily={tp} vs holdings_sum={hs} (diff={diff})"
            result.errors.append(entry)
        elif abs(diff) > MAX_PCT_VS_HOLDINGS_DIFF:
            entry["severity"] = "warning"
            entry["detail"] = f"Pct mismatch: daily={tp} vs holdings_sum={hs} (diff={diff})"
            result.warnings.append(entry)


# ── Check 3: Shares consistency ─────────────────────────────────────────
def _check_shares_consistency(conn, result, stock, date_val):
    base_where = ""
    base_params = []
    if stock:
        base_where = "AND d.stock_code = ?"
        base_params = [stock]
    if date_val:
        base_where += " AND d.trade_date = ?"
        base_params.append(date_val)

    rows = conn.execute(f"""
        SELECT d.stock_code, d.trade_date, d.total_shares,
               COALESCE(h.sum_shares, 0) as holdings_sum,
               ROUND(ABS(d.total_shares - COALESCE(h.sum_shares, 0)) * 100.0 / d.total_shares, 2) as pct_diff
        FROM holdings_daily d
        LEFT JOIN (
            SELECT stock_code, trade_date, SUM(shares) as sum_shares
            FROM holdings_holdings
            GROUP BY stock_code, trade_date
        ) h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
        WHERE d.total_shares > 0 {base_where}
          AND ABS(d.total_shares - COALESCE(h.sum_shares, 0)) * 100.0 / d.total_shares > ?
        ORDER BY pct_diff DESC
        LIMIT 50
    """, base_params + [MAX_SHARES_VS_HOLDINGS_PCT]).fetchall()

    for r in rows:
        sc, td, ts, hs, pd = r
        entry = {
            "check": "shares_consistency",
            "stock": sc,
            "date": td,
            "daily_shares": ts,
            "holdings_sum": hs,
            "pct_diff": pd,
        }
        entry["severity"] = "warning"
        if hs == 0:
            entry["detail"] = f"No holdings shares for {sc} on {td} (holdings may not be scraped)"
        elif pd > 20:
            entry["detail"] = f"Large shares mismatch: daily={ts} vs holdings_sum={hs} ({pd}%)"
        else:
            entry["detail"] = f"Shares mismatch: daily={ts} vs holdings_sum={hs} ({pd}%)"
        result.warnings.append(entry)


# ── Check 4: Day-over-day anomaly detection ─────────────────────────────
def _check_daily_jumps(conn, result, stock, date_val):
    stock_where = "WHERE stock_code = ?" if stock else ""
    stock_params = [stock] if stock else []

    # Limit scope for full-scan performance
    limit_clause = "" if (stock or date_val) else "LIMIT 50"

    rows = conn.execute(f"""
        WITH changes AS (
            SELECT stock_code, trade_date, total_pct, total_shares,
                   LAG(total_pct) OVER w as prev_pct,
                   LAG(total_shares) OVER w as prev_shares,
                   LAG(trade_date) OVER w as prev_date
            FROM holdings_daily
            {stock_where}
            WINDOW w AS (PARTITION BY stock_code ORDER BY trade_date)
        )
        SELECT stock_code, prev_date, trade_date,
               ROUND(prev_pct, 2), ROUND(total_pct, 2),
               ROUND(total_pct - prev_pct, 2) as delta,
               prev_shares, total_shares
        FROM changes
        WHERE prev_pct IS NOT NULL
          AND total_pct > 0 AND prev_pct > 0
          AND ABS(total_pct - prev_pct) > ?
        ORDER BY ABS(total_pct - prev_pct) DESC
        {limit_clause}
    """, stock_params + [MAX_PCT_JUMP_DAY]).fetchall()

    for r in rows:
        sc, pd, td, pp, tp, delta, ps, ts = r
        # Check if shares also changed significantly (suggesting corp action)
        share_change = abs(ts - ps) / ps * 100 if ps and ps > 0 else 999

        entry = {
            "check": "daily_jump",
            "stock": sc,
            "prev_date": pd,
            "date": td,
            "prev_pct": pp,
            "curr_pct": tp,
            "delta_pct": delta,
            "share_change_pct": round(share_change, 2),
        }

        if share_change < 5 and abs(delta) > 50:
            # Large pct jump with nearly-unchanged shares = likely scraper bug
            entry["severity"] = "error"
            entry["detail"] = (
                f"Pct swung {delta:+.1f}% ({pp}→{tp}) but shares barely changed "
                f"({ps}→{ts}, {share_change:.2f}%). Likely SCRAPER BUG."
            )
            result.errors.append(entry)
        elif share_change > 20:
            entry["severity"] = "info"
            entry["detail"] = (
                f"Pct changed {delta:+.1f}% with significant share change "
                f"({share_change:.1f}%) — likely corporate action."
            )
            result.info.append(entry)
        else:
            entry["severity"] = "warning"
            entry["detail"] = (
                f"Pct changed {delta:+.1f}% ({pp}→{tp}), shares changed {share_change:.1f}%."
            )
            result.warnings.append(entry)


# ── Check 5: Date coverage gaps ─────────────────────────────────────────
def _check_coverage_gaps(conn, result, stock, date_val):
    """Check for trading days with unexpectedly low stock coverage."""
    if date_val:
        return  # Not meaningful for single-date check

    stock_where = "WHERE stock_code = ?" if stock else ""
    stock_params = [stock] if stock else []

    # Get stock count per date
    rows = conn.execute(f"""
        SELECT trade_date, COUNT(*) as n_stocks
        FROM holdings_daily
        {stock_where}
        GROUP BY trade_date
        ORDER BY trade_date
    """, stock_params).fetchall()

    if not rows:
        return

    counts = [r[1] for r in rows]
    median_count = sorted(counts)[len(counts) // 2] if counts else 0

    for r in rows:
        td, n = r
        if median_count > 0 and n < median_count * 0.5:
            result.warnings.append({
                "check": "coverage_gap",
                "severity": "warning",
                "stock": stock or "*",
                "date": td,
                "detail": f"Only {n} stocks on {td} (median={median_count}) — possible partial scrape",
            })

    result.stats["date_count"] = len(rows)
    result.stats["median_stocks_per_date"] = median_count
    result.stats["min_stocks_per_date"] = min(counts)
    result.stats["max_stocks_per_date"] = max(counts)


# ── Check 6: Zero participant counts ────────────────────────────────────
def _check_participant_counts(conn, result, stock, date_val):
    where, params = _add_filter(stock, date_val)

    rows = conn.execute(f"""
        SELECT stock_code, trade_date, total_shares, num_participants
        FROM holdings_daily d
        {where}
        AND total_shares > 0
        AND (num_participants IS NULL OR num_participants = 0)
        ORDER BY trade_date, stock_code
        LIMIT 50
    """, params).fetchall()

    for r in rows:
        result.warnings.append({
            "check": "zero_participants",
            "severity": "warning",
            "stock": r[0],
            "date": r[1],
            "detail": f"Has {r[2]:,} shares but num_participants={r[3]}",
        })

    # Count total
    count_row = conn.execute(f"""
        SELECT COUNT(*) FROM holdings_daily d
        {where}
        AND total_shares > 0
        AND (num_participants IS NULL OR num_participants = 0)
    """, params).fetchone()
    if count_row and count_row[0] > 0:
        result.stats["zero_participant_rows"] = count_row[0]


# ── Check 7: Orphan rows ────────────────────────────────────────────────
def _check_orphan_rows(conn, result, stock, date_val):
    """Find daily rows without corresponding holdings, and vice versa."""

    # Daily without holdings
    where_d = ""
    params_d = []
    if stock:
        where_d = "AND d.stock_code = ?"
        params_d = [stock]
    if date_val:
        where_d += " AND d.trade_date = ?"
        params_d.append(date_val)

    rows = conn.execute(f"""
        SELECT d.stock_code, d.trade_date, d.total_shares, d.total_pct
        FROM holdings_daily d
        LEFT JOIN holdings_holdings h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
        WHERE h.stock_code IS NULL {where_d}
        ORDER BY d.trade_date, d.stock_code
        LIMIT 50
    """, params_d).fetchall()

    for r in rows:
        result.warnings.append({
            "check": "orphan_daily",
            "severity": "warning",
            "stock": r[0],
            "date": r[1],
            "detail": f"Daily row exists ({r[2]:,} shares, {r[3]}%) but no holdings rows",
        })

    # Count
    count_row = conn.execute(f"""
        SELECT COUNT(*) FROM holdings_daily d
        LEFT JOIN holdings_holdings h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
        WHERE h.stock_code IS NULL {where_d}
    """, params_d).fetchone()
    if count_row and count_row[0] > 0:
        result.stats["orphan_daily_rows"] = count_row[0]


# ── Check 8: Concentration metrics sanity ───────────────────────────────
def _check_concentration_metrics(conn, result, stock, date_val):
    where, params = _add_filter(stock, date_val)

    # top5_pct > total_pct
    rows = conn.execute(f"""
        SELECT stock_code, trade_date, total_pct, top5_pct, top10_pct
        FROM holdings_daily d
        {where}
        AND top5_pct IS NOT NULL AND total_pct IS NOT NULL
        AND top5_pct > total_pct + 1
        ORDER BY top5_pct - total_pct DESC
        LIMIT 20
    """, params).fetchall()

    for r in rows:
        result.warnings.append({
            "check": "concentration_sanity",
            "severity": "warning",
            "stock": r[0],
            "date": r[1],
            "detail": f"top5_pct={r[3]} > total_pct={r[2]} (impossible unless computed against adjusted float)",
        })

    # top5_pct > top10_pct
    rows = conn.execute(f"""
        SELECT stock_code, trade_date, top5_pct, top10_pct
        FROM holdings_daily d
        {where}
        AND top5_pct IS NOT NULL AND top10_pct IS NOT NULL
        AND top5_pct > top10_pct + 1
        ORDER BY top5_pct - top10_pct DESC
        LIMIT 20
    """, params).fetchall()

    for r in rows:
        result.warnings.append({
            "check": "concentration_sanity",
            "severity": "warning",
            "stock": r[0],
            "date": r[1],
            "detail": f"top5_pct={r[2]} > top10_pct={r[3]} (top5 should be ≤ top10)",
        })


# ── Deep check for a specific stock ─────────────────────────────────────
def deep_check_stock(conn, stock_code: str) -> dict:
    """Detailed analysis of a single stock."""
    result = {
        "stock_code": stock_code,
        "dates_checked": 0,
        "pct_inconsistency_dates": [],
        "shares_inconsistency_dates": [],
        "jump_dates": [],
        "holdings_consistency": [],
    }

    # All daily rows
    rows = conn.execute("""
        SELECT trade_date, total_shares, total_pct, num_participants, top5_pct, top10_pct
        FROM holdings_daily WHERE stock_code = ?
        ORDER BY trade_date
    """, [stock_code]).fetchall()

    result["dates_checked"] = len(rows)

    # holdings sum per date
    holdings = conn.execute("""
        SELECT trade_date, SUM(shares) as sum_shares, SUM(pct_of_issued) as sum_pct,
               COUNT(*) as n_participants
        FROM holdings_holdings WHERE stock_code = ?
        GROUP BY trade_date ORDER BY trade_date
    """, [stock_code]).fetchall()
    holdings_map = {h[0]: h for h in holdings}

    for r in rows:
        td, ts, tp, np, t5, t10 = r
        h = holdings_map.get(td)

        implied_issued = int(ts / (tp / 100)) if tp and tp > 0 else None

        entry = {
            "date": td,
            "total_shares": ts,
            "total_pct": tp,
            "implied_issued_shares": implied_issued,
        }

        if h:
            _, hs, hp, hn = h
            entry["holdings_shares_sum"] = hs
            entry["holdings_pct_sum"] = round(hp, 2) if hp else None
            entry["holdings_participants"] = hn

            if tp and hp and abs(tp - hp) > 3:
                result["pct_inconsistency_dates"].append({
                    "date": td,
                    "daily_pct": tp,
                    "holdings_sum_pct": round(hp, 2),
                    "diff": round(tp - hp, 2),
                })

            if ts and hs and abs(ts - hs) > ts * 0.02:
                result["shares_inconsistency_dates"].append({
                    "date": td,
                    "daily_shares": ts,
                    "holdings_sum_shares": hs,
                    "diff": ts - hs,
                })

        result["holdings_consistency"].append(entry)

    # Day-over-day jumps
    prev = None
    for r in rows:
        td, ts, tp, np, t5, t10 = r
        if prev:
            pt, ps, pp = prev
            if tp and pp and abs(tp - pp) > 5:
                share_change = abs(ts - ps) / ps * 100 if ps > 0 else 999
                result["jump_dates"].append({
                    "from_date": pt,
                    "to_date": td,
                    "pct_delta": round(tp - pp, 2),
                    "shares_delta": ts - ps,
                    "share_change_pct": round(share_change, 2),
                    "likely_bug": share_change < 5 and abs(tp - pp) > 30,
                })
        prev = (td, ts, tp)

    return result


# ── Summary report ──────────────────────────────────────────────────────
def _compute_summary_stats(conn, result: VerificationResult, stock, date_val):
    """Compute aggregate statistics."""
    base_where = ""
    base_params = []
    if stock:
        base_where = "WHERE stock_code = ?"
        base_params = [stock]
    if date_val:
        prefix = "AND" if base_where else "WHERE"
        base_where += f" {prefix} trade_date = ?"
        base_params.append(date_val)

    def _and(cond):
        """Prefix with AND or WHERE depending on base_where."""
        prefix = "AND" if base_where else "WHERE"
        return f" {prefix} {cond}"

    # Total stocks and dates
    row = conn.execute(f"""
        SELECT COUNT(DISTINCT stock_code), COUNT(DISTINCT trade_date), COUNT(*)
        FROM holdings_daily
        {base_where}
    """, base_params).fetchone()
    result.stats["unique_stocks"] = row[0]
    result.stats["unique_dates"] = row[1]
    result.stats["total_rows"] = row[2]

    # NULL pct count
    row = conn.execute(f"""
        SELECT COUNT(*) FROM holdings_daily
        {base_where}{_and("total_pct IS NULL")}
    """, base_params).fetchone()
    result.stats["null_total_pct"] = row[0]

    # total_pct = 0 count
    row = conn.execute(f"""
        SELECT COUNT(*) FROM holdings_daily
        {base_where}{_and("total_pct = 0")}
    """, base_params).fetchone()
    result.stats["zero_total_pct"] = row[0]

    # total_pct = 0 by date (for full scan)
    if not date_val and not stock:
        rows = conn.execute("""
            SELECT trade_date, COUNT(*) FROM holdings_daily
            WHERE total_pct = 0
            GROUP BY trade_date ORDER BY COUNT(*) DESC
        """).fetchall()
        result.stats["zero_pct_by_date"] = [(r[0], r[1]) for r in rows[:10]]


# ── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="HOLDINGS Data Verification")
    parser.add_argument("--stock", help="Check a single stock (e.g. 00328)")
    parser.add_argument("--date", help="Check a single date (e.g. 2026-05-28)")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--deep", action="store_true", help="Deep-check a single stock (requires --stock)")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    stock_code = args.stock.zfill(5) if args.stock else None

    if args.deep and stock_code:
        # Deep single-stock analysis
        result = deep_check_stock(conn, stock_code)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_deep_report(stock_code, result)
        conn.close()
        return

    result = VerificationResult()

    # Compute summary
    _compute_summary_stats(conn, result, stock_code, args.date)

    # Run all checks
    run_all_checks(conn, result, stock_code, args.date)

    conn.close()

    if args.json:
        output = result.to_dict()
        print(json.dumps(output, indent=2, default=str))
    else:
        _print_report(result, stock_code, args.date)

    # Exit code
    sys.exit(1 if result.has_errors() else 0)


def _print_report(result: VerificationResult, stock: str | None, date_val: str | None):
    """Human-readable report."""
    scope = f"stock={stock}" if stock else (f"date={date_val}" if date_val else "ALL")
    print(f"{'='*70}")
    print(f"  HOLDINGS Data Verification Report — {scope}")
    print(f"{'='*70}")

    # Stats
    s = result.stats
    print(f"\n── Summary Statistics ──")
    print(f"  Unique stocks:  {s.get('unique_stocks', 'N/A'):>8}")
    print(f"  Unique dates:   {s.get('unique_dates', 'N/A'):>8}")
    print(f"  Total rows:     {s.get('total_rows', 'N/A'):>8}")
    print(f"  NULL total_pct: {s.get('null_total_pct', 'N/A'):>8}")
    print(f"  Zero total_pct: {s.get('zero_total_pct', 'N/A'):>8}")

    if 'median_stocks_per_date' in s:
        print(f"  Stocks/date:    median={s['median_stocks_per_date']}, "
              f"min={s['min_stocks_per_date']}, max={s['max_stocks_per_date']}")

    if 'zero_pct_by_date' in s:
        print(f"\n  Dates with most total_pct=0 rows:")
        for td, cnt in s['zero_pct_by_date']:
            print(f"    {td}: {cnt} stocks")

    # Errors
    print(f"\n── Errors ({len(result.errors)}) ──")
    if result.errors:
        for e in result.errors[:30]:
            print(f"  [{e['check']}] {e['stock']} {e['date']}: {e['detail']}")
        if len(result.errors) > 30:
            print(f"  ... and {len(result.errors) - 30} more")
    else:
        print("  ✓ No errors found")

    # Warnings
    print(f"\n── Warnings ({len(result.warnings)}) ──")
    if result.warnings:
        for w in result.warnings[:20]:
            print(f"  [{w['check']}] {w['stock']} {w['date']}: {w['detail']}")
        if len(result.warnings) > 20:
            print(f"  ... and {len(result.warnings) - 20} more")
    else:
        print("  ✓ No warnings")

    # Info
    print(f"\n── Info ({len(result.info)}) ──")
    if result.info:
        for i in result.info[:10]:
            print(f"  [{i['check']}] {i['stock']}: {i['detail']}")
    else:
        print("  ✓ No info items")

    print(f"\n{'='*70}")
    status = "❌ FAIL" if result.has_errors() else "✓ PASS"
    print(f"  Overall: {status}  ({len(result.errors)} errors, {len(result.warnings)} warnings)")
    print(f"{'='*70}")


def _print_deep_report(stock_code: str, result: dict):
    """Print detailed single-stock analysis."""
    print(f"{'='*70}")
    print(f"  Deep Check: {stock_code}")
    print(f"  Dates: {result['dates_checked']}")
    print(f"{'='*70}")

    print(f"\n── holdings Consistency ──")
    print(f"  {'Date':<12} {'Shares':>12} {'Pct%':>8} {'ImpliedIssued':>14} {'H-Shares':>12} {'H-Pct%':>8}")
    print(f"  {'-'*12} {'-'*12} {'-'*8} {'-'*14} {'-'*12} {'-'*8}")
    for entry in result["holdings_consistency"]:
        td = entry["date"]
        ts = f"{entry['total_shares']:,}" if entry["total_shares"] else "N/A"
        tp = f"{entry['total_pct']:.2f}" if entry["total_pct"] else "N/A"
        ii = f"{entry.get('implied_issued_shares', 'N/A'):,}" if entry.get('implied_issued_shares') else "N/A"
        hs = f"{entry.get('holdings_shares_sum', 'N/A'):,}" if entry.get('holdings_shares_sum') else "N/A"
        hp = f"{entry.get('holdings_pct_sum', 'N/A'):.2f}" if entry.get('holdings_pct_sum') else "N/A"
        flag = ""
        if entry.get("total_pct") and entry.get("holdings_pct_sum"):
            diff = abs(entry["total_pct"] - entry["holdings_pct_sum"])
            if diff > 50:
                flag = " ⚠️ BUG"
            elif diff > 5:
                flag = " ⚡"
        print(f"  {td:<12} {ts:>12} {tp:>8} {ii:>14} {hs:>12} {hp:>8}{flag}")

    if result["pct_inconsistency_dates"]:
        print(f"\n── PCT Inconsistencies ──")
        for p in result["pct_inconsistency_dates"]:
            print(f"  {p['date']}: daily={p['daily_pct']}% vs holdings_sum={p['holdings_sum_pct']}% (diff={p['diff']})")

    if result["jump_dates"]:
        print(f"\n── Day-over-Day Jumps ──")
        for j in result["jump_dates"]:
            bug_flag = " 🐛 LIKELY SCRAPER BUG" if j["likely_bug"] else ""
            print(f"  {j['from_date']} → {j['to_date']}: "
                  f"pct {j['pct_delta']:+.2f}%, "
                  f"shares {j['shares_delta']:+,} ({j['share_change_pct']:.2f}%){bug_flag}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
    # The CLI exits non-zero when JSON status is FAIL so shell pipelines can gate deploys.
