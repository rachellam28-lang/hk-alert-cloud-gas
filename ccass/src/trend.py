"""Trend calculation: 5日/20日 持倉變化 + 連續增減。

用 trading-day-based lookback（不是 row-based LAG），支持 data gaps。
"""
from __future__ import annotations

from datetime import datetime, date

from src.db import get_conn
from src.logger import setup_logger
from src.trading_calendar import last_n_trading_days

logger = setup_logger("trend")


def compute_trends_for_date(target_date: date, windows: list[int] | None = None) -> int:
    """
    計指定日期所有股票嘅 trend metrics。
    用真實交易日曆做 lookback（唔係 row offset LAG），gap-friendly。
    回傳成功計嘅股票數。
    """
    if windows is None:
        windows = [5, 20]
    date_str = target_date.strftime("%Y-%m-%d")
    now_iso = datetime.utcnow().isoformat()

    # Pre-compute reference dates: for each window, find the trading day N days back
    ref_dates = {}
    max_window = max(windows)
    all_tdays = last_n_trading_days(target_date, max_window + 1)
    for w in windows:
        if len(all_tdays) > w:
            ref_dates[w] = all_tdays[-(w + 1)]
        else:
            ref_dates[w] = None

    # Build SQL with date-based LEFT JOINs
    ref_joins = []
    ref_selects = []
    ref_params = []
    for w in windows:
        if ref_dates[w] is not None:
            rd = ref_dates[w].strftime("%Y-%m-%d")
            ref_joins.append(
                "LEFT JOIN ccass_daily AS ref{w} "
                "ON cur.stock_code = ref{w}.stock_code "
                "AND ref{w}.trade_date = ? "
                "AND ref{w}.validation_failed = 0".format(w=w)
            )
            ref_selects.append(
                "cur.total_pct - ref{w}.total_pct AS delta_{w}d_pct, "
                "cur.total_shares - ref{w}.total_shares AS delta_{w}d_shares".format(w=w)
            )
            ref_params.append(rd)
        else:
            ref_selects.append(
                "0.0 AS delta_{w}d_pct, 0 AS delta_{w}d_shares".format(w=w)
            )

    ref_join_block = "\n".join(ref_joins)
    ref_select_block = ",\n        ".join(ref_selects)

    sql = (
        "SELECT\n"
        "    cur.stock_code,\n"
        "    cur.trade_date,\n"
        "    {ref_select_block}\n"
        "FROM ccass_daily AS cur\n"
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

    # Fill remaining columns (60d, 120d) with NULL
    extra_null_cols = ""
    extra_null_vals = ""
    if 60 not in windows:
        extra_null_cols = ", delta_60d_pct, delta_120d_pct, delta_60d_shares, delta_120d_shares"
        extra_null_vals = ", NULL, NULL, NULL, NULL"

    update_set = ",\n        ".join(
        "{c} = excluded.{c}".format(c=c) for c in delta_cols
    )

    insert_sql = (
        "INSERT INTO ccass_trends\n"
        "    (stock_code, trade_date, {delta_cols}{extra_null_cols},\n"
        "     consecutive_increase_days, consecutive_decrease_days, computed_at)\n"
        "VALUES (?, ?, {placeholders}{extra_null_vals}, ?, ?, ?)\n"
        "ON CONFLICT(stock_code, trade_date) DO UPDATE SET\n"
        "    {update_set},\n"
        "    consecutive_increase_days = excluded.consecutive_increase_days,\n"
        "    consecutive_decrease_days = excluded.consecutive_decrease_days,\n"
        "    computed_at = excluded.computed_at"
    ).format(
        delta_cols=", ".join(delta_cols),
        extra_null_cols=extra_null_cols,
        placeholders=", ".join(["?" for _ in delta_cols]),
        extra_null_vals=extra_null_vals,
        update_set=update_set,
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
           FROM ccass_daily
           WHERE stock_code = ? AND trade_date <= ? AND validation_failed = 0
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
        else:
            break

    return up, down
