"""Trend calculation: 5日/20日 持倉變化 + 連續增減。

用 trading-day-based lookback（不是 row-based LAG），支持 data gaps。
"""
from __future__ import annotations

from datetime import datetime, date, timedelta

from src.db import get_conn
from src.logger import setup_logger
from src.trading_calendar import last_n_trading_days

logger = setup_logger("trend")


def reference_dates_for_windows(
    target_date: date,
    windows: list[int] | None = None,
    max_calendar_gap: int = 4,
) -> dict[int, date | None]:
    """Pick a nearby high-coverage trusted reference date for each window."""
    if windows is None:
        windows = [5, 20, 60, 120]
    if not windows:
        return {}
    all_tdays = last_n_trading_days(target_date, max(windows) + 1)
    expected = {
        w: all_tdays[-(w + 1)] if len(all_tdays) > w else None
        for w in windows
    }
    refs: dict[int, date | None] = {}
    with get_conn() as conn:
        active_row = conn.execute(
            "SELECT COUNT(*) FROM stock_universe WHERE is_active = 1"
        ).fetchone()
        active_total = int(active_row[0] or 0) if active_row else 0
        minimum_trusted = max(1, int(active_total * 0.90))
        for window, expected_date in expected.items():
            if expected_date is None:
                refs[window] = None
                continue
            lower = (expected_date - timedelta(days=max_calendar_gap)).isoformat()
            upper = min(target_date, expected_date + timedelta(days=max_calendar_gap)).isoformat()
            row = conn.execute(
                """
                SELECT trade_date,
                       SUM(CASE WHEN total_pct IS NOT NULL THEN 1 ELSE 0 END) AS trusted_count
                FROM holdings_daily
                WHERE trade_date BETWEEN ? AND ?
                  AND validation_failed = 0
                GROUP BY trade_date
                HAVING trusted_count >= ?
                ORDER BY ABS(julianday(trade_date) - julianday(?)) ASC,
                         trusted_count DESC,
                         trade_date DESC
                LIMIT 1
                """,
                (lower, upper, minimum_trusted, expected_date.isoformat()),
            ).fetchone()
            refs[window] = date.fromisoformat(row[0]) if row else None
    return refs


def compute_trends_for_date(target_date: date, windows: list[int] | None = None) -> int:
    """
    計指定日期所有股票嘅 trend metrics。
    用真實交易日曆做 lookback（唔係 row offset LAG），gap-friendly。
    回傳成功計嘅股票數。
    """
    if windows is None:
        windows = [5, 20, 60, 120]
    date_str = target_date.strftime("%Y-%m-%d")
    now_iso = datetime.utcnow().isoformat()

    # Use the nearest trusted high-coverage snapshot around each exact trading-day target.
    # This tolerates one missing scrape without comparing incompatible fallback sources.
    ref_dates = reference_dates_for_windows(target_date, windows)

    # Build SQL with date-based LEFT JOINs
    ref_joins = []
    ref_selects = []
    ref_params = []
    for w in windows:
        if ref_dates[w] is not None:
            rd = ref_dates[w].strftime("%Y-%m-%d")
            ref_joins.append(
                "LEFT JOIN holdings_daily AS ref{w} "
                "ON cur.stock_code = ref{w}.stock_code "
                "AND ref{w}.trade_date = ? "
                "AND ref{w}.validation_failed = 0".format(w=w)
            )
            ref_selects.append(
                "CASE "
                "WHEN cur.total_pct IS NOT NULL AND ref{w}.total_pct IS NOT NULL "
                "AND cur.total_shares IS NOT NULL AND ref{w}.total_shares IS NOT NULL "
                "AND ref{w}.total_shares != 0 "
                "THEN (cur.total_shares - ref{w}.total_shares) * 100.0 / ref{w}.total_shares "
                "ELSE NULL END AS delta_{w}d_pct, "
                "CASE WHEN cur.total_pct IS NOT NULL AND ref{w}.total_pct IS NOT NULL "
                "THEN cur.total_shares - ref{w}.total_shares ELSE NULL END AS delta_{w}d_shares".format(w=w)
            )
            ref_params.append(rd)
        else:
            ref_selects.append(
                "NULL AS delta_{w}d_pct, NULL AS delta_{w}d_shares".format(w=w)
            )

    ref_join_block = "\n".join(ref_joins)
    ref_select_block = ",\n        ".join(ref_selects)

    sql = (
        "SELECT\n"
        "    cur.stock_code,\n"
        "    cur.trade_date,\n"
        "    {ref_select_block}\n"
        "FROM holdings_daily AS cur\n"
        "{ref_join_block}\n"
        "WHERE cur.trade_date = ?\n"
        "  AND cur.validation_failed = 0"
    ).format(
        ref_select_block=ref_select_block,
        ref_join_block=ref_join_block,
    )
    ref_params.append(date_str)

    # Build INSERT dynamically
    delta_cols = []
    for w in windows:
        delta_cols.append("delta_{w}d_pct".format(w=w))
        delta_cols.append("delta_{w}d_shares".format(w=w))

    # Null out unsupported/unreliable windows so stale values from an older run
    # cannot survive when only a subset of windows is recomputed.
    supported_windows = (5, 20, 60, 120)
    missing_delta_cols = []
    for w in supported_windows:
        if w not in windows:
            missing_delta_cols.append("delta_{w}d_pct".format(w=w))
            missing_delta_cols.append("delta_{w}d_shares".format(w=w))
    extra_null_cols = ", " + ", ".join(missing_delta_cols) if missing_delta_cols else ""
    extra_null_vals = ", " + ", ".join(["NULL" for _ in missing_delta_cols]) if missing_delta_cols else ""
    extra_update_nulls = ""
    if missing_delta_cols:
        extra_update_nulls = ",\n        " + ",\n        ".join(
            "{c} = NULL".format(c=c) for c in missing_delta_cols
        )

    update_set = ",\n        ".join(
        "{c} = excluded.{c}".format(c=c) for c in delta_cols
    )

    insert_sql = (
        "INSERT INTO ccass_trends\n"
        "    (stock_code, trade_date, {delta_cols}{extra_null_cols},\n"
        "     consecutive_increase_days, consecutive_decrease_days, computed_at)\n"
        "VALUES (?, ?, {placeholders}{extra_null_vals}, ?, ?, ?)\n"
        "ON CONFLICT(stock_code, trade_date) DO UPDATE SET\n"
        "    {update_set}{extra_update_nulls},\n"
        "    consecutive_increase_days = excluded.consecutive_increase_days,\n"
        "    consecutive_decrease_days = excluded.consecutive_decrease_days,\n"
        "    computed_at = excluded.computed_at"
    ).format(
        delta_cols=", ".join(delta_cols),
        extra_null_cols=extra_null_cols,
        placeholders=", ".join(["?" for _ in delta_cols]),
        extra_null_vals=extra_null_vals,
        update_set=update_set,
        extra_update_nulls=extra_update_nulls,
    )

    count = 0
    with get_conn() as conn:
        rows = conn.execute(sql, ref_params).fetchall()
        for r in rows:
            up, down = _consecutive_streak(conn, r["stock_code"], target_date)

            params = [r["stock_code"], r["trade_date"]]
            for w in windows:
                key_pct = "delta_{w}d_pct".format(w=w)
                key_sh = "delta_{w}d_shares".format(w=w)
                params.append(r[key_pct])
                params.append(r[key_sh])
            params.extend([up, down, now_iso])

            conn.execute(insert_sql, params)
            count += 1

    logger.info("Computed trends for %d stocks on %s (refs: %s)", count, date_str,
                {w: str(d) for w, d in ref_dates.items() if d})
    return count


def _consecutive_streak(conn, stock_code: str, end_date: date) -> tuple[int, int]:
    """計到 end_date 為止嘅連續增持/減持日數。"""
    end_str = end_date.strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT trade_date, total_pct, total_shares
           FROM holdings_daily
           WHERE stock_code = ? AND trade_date <= ? AND validation_failed = 0
             AND total_pct IS NOT NULL
           ORDER BY trade_date DESC
           LIMIT 30""",
        (stock_code, end_str),
    ).fetchall()

    if len(rows) < 2:
        return 0, 0

    up = down = 0
    streak_dir = 0
    for i in range(len(rows) - 1):
        # P1-1: use total_shares (absolute) not total_pct (affected by corp actions)
        cur = rows[i]["total_shares"]
        prev = rows[i + 1]["total_shares"]
        if cur is None or prev is None:
            break
        if cur > prev:
            if streak_dir in (0, 1):
                up += 1
                streak_dir = 1
            else:
                break
        elif cur < prev:
            if streak_dir in (0, -1):
                down += 1
                streak_dir = -1
            else:
                break
        # else: cur == prev → neutral day, skip without breaking streak

    return up, down
