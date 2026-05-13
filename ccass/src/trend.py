"""Trend calculation: 5日/20日 持倉變化 + 連續增減。

用 SQL window functions（截圖入面講過：方便日後加 60d column）。
"""
from __future__ import annotations

from datetime import datetime, date

from src.db import get_conn
from src.logger import setup_logger

logger = setup_logger("trend")


def compute_trends_for_date(target_date: date, windows: list[int] | None = None) -> int:
    """
    計指定日期所有股票嘅 trend metrics。
    回傳成功計嘅股票數。
    """
    if windows is None:
        windows = [5, 20]
    date_str = target_date.strftime("%Y-%m-%d")
    now_iso = datetime.utcnow().isoformat()

    # 用 window functions LAG，攞番 N 個 trading day 前嘅 total_pct
    # 注意：要 partition by stock_code，order by trade_date
    sql = """
    WITH ranked AS (
        SELECT
            stock_code,
            trade_date,
            total_pct,
            total_shares,
            LAG(total_pct, 5) OVER (PARTITION BY stock_code ORDER BY trade_date) AS pct_5d_ago,
            LAG(total_pct, 20) OVER (PARTITION BY stock_code ORDER BY trade_date) AS pct_20d_ago,
            LAG(total_shares, 5) OVER (PARTITION BY stock_code ORDER BY trade_date) AS sh_5d_ago,
            LAG(total_shares, 20) OVER (PARTITION BY stock_code ORDER BY trade_date) AS sh_20d_ago
        FROM ccass_daily
        WHERE validation_failed = 0
    )
    SELECT
        stock_code,
        trade_date,
        total_pct - COALESCE(pct_5d_ago, total_pct) AS delta_5d_pct,
        total_pct - COALESCE(pct_20d_ago, total_pct) AS delta_20d_pct,
        total_shares - COALESCE(sh_5d_ago, total_shares) AS delta_5d_shares,
        total_shares - COALESCE(sh_20d_ago, total_shares) AS delta_20d_shares
    FROM ranked
    WHERE trade_date = ?
    """

    consecutive_sql = """
    WITH prev AS (
        SELECT
            stock_code,
            trade_date,
            total_pct,
            LAG(total_pct, 1) OVER (PARTITION BY stock_code ORDER BY trade_date) AS prev_pct
        FROM ccass_daily
        WHERE validation_failed = 0
    ),
    direction AS (
        SELECT
            stock_code,
            trade_date,
            CASE
                WHEN prev_pct IS NULL THEN 0
                WHEN total_pct > prev_pct THEN 1
                WHEN total_pct < prev_pct THEN -1
                ELSE 0
            END AS dir
        FROM prev
    )
    SELECT
        stock_code,
        SUM(CASE WHEN dir = 1 THEN 1 ELSE 0 END) AS up_days,
        SUM(CASE WHEN dir = -1 THEN 1 ELSE 0 END) AS down_days
    FROM (
        SELECT * FROM direction
        WHERE trade_date <= ?
        ORDER BY stock_code, trade_date DESC
    )
    GROUP BY stock_code
    """
    # ↑ 上面個 consecutive 簡化版：實際要算「連續同方向」要遞迴 CTE。
    # 為咗效率，我哋用 Python 計（每隻股票拎最近 N 日 direction）。

    count = 0
    with get_conn() as conn:
        rows = conn.execute(sql, (date_str,)).fetchall()
        for r in rows:
            up, down = _consecutive_streak(conn, r["stock_code"], target_date)
            conn.execute(
                """INSERT INTO ccass_trends
                     (stock_code, trade_date, delta_5d_pct, delta_20d_pct,
                      delta_5d_shares, delta_20d_shares,
                      consecutive_increase_days, consecutive_decrease_days,
                      computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                     delta_5d_pct = excluded.delta_5d_pct,
                     delta_20d_pct = excluded.delta_20d_pct,
                     delta_5d_shares = excluded.delta_5d_shares,
                     delta_20d_shares = excluded.delta_20d_shares,
                     consecutive_increase_days = excluded.consecutive_increase_days,
                     consecutive_decrease_days = excluded.consecutive_decrease_days,
                     computed_at = excluded.computed_at""",
                (
                    r["stock_code"],
                    r["trade_date"],
                    r["delta_5d_pct"],
                    r["delta_20d_pct"],
                    r["delta_5d_shares"],
                    r["delta_20d_shares"],
                    up,
                    down,
                    now_iso,
                ),
            )
            count += 1

    logger.info("Computed trends for %d stocks on %s", count, date_str)
    return count


def _consecutive_streak(conn, stock_code: str, end_date: date) -> tuple[int, int]:
    """計到 end_date 為止嘅連續增持/減持日數。"""
    end_str = end_date.strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT trade_date, total_pct
           FROM ccass_daily
           WHERE stock_code = ? AND trade_date <= ? AND validation_failed = 0
           ORDER BY trade_date DESC
           LIMIT 30""",
        (stock_code, end_str),
    ).fetchall()

    if len(rows) < 2:
        return 0, 0

    up = down = 0
    streak_dir = 0  # 1 = up, -1 = down
    for i in range(len(rows) - 1):
        cur = rows[i]["total_pct"]
        prev = rows[i + 1]["total_pct"]
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
