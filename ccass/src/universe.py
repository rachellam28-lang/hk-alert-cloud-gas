"""Stock universe management.

CCASS 公開 stock list 喺 HKEX 網站。我哋每星期 refresh 一次。
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from src.db import get_conn
from src.logger import setup_logger

logger = setup_logger("universe")

# HKEX 有公開嘅 stock list CSV
HKEX_STOCK_LIST_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/"
    "ListOfSecurities.xlsx"
)


def fetch_all_hk_stocks_from_ccass() -> list[tuple[str, str]]:
    """
    Fallback: 從 CCASS query page 攞 dropdown stock list。
    回傳 [(stock_code_5digit, name), ...]
    
    我哋實際上唔需要逐隻 hardcode。每日 scrape 時，
    HKEX CCASS 系統會接受任何 5 位 stock code，invalid 嘅返回空。
    
    呢個 function 用 HKEX 嘅 stock list xlsx 作為 source of truth。
    """
    logger.info("Fetching HKEX stock list from %s", HKEX_STOCK_LIST_URL)
    try:
        resp = requests.get(HKEX_STOCK_LIST_URL, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to fetch HKEX stock list: %s", e)
        raise

    # Parse xlsx
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
    ws = wb.active

    stocks: list[tuple[str, str]] = []
    # HKEX 個 xlsx 有 header rows，stock code 喺第 1 col，name 第 2 col
    # 跳前 2-3 row header (HKEX 偶爾改 layout，所以用 heuristic)
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        first = str(row[0]).strip()
        # Stock code 係純數字，長度 1-5
        if first.isdigit() and 1 <= len(first) <= 5:
            code = first.zfill(5)
            name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            stocks.append((code, name))

    logger.info("Found %d stocks", len(stocks))
    return stocks


def refresh_universe() -> int:
    """Refresh stock_universe table. 回傳新增 stock 數量。"""
    stocks = fetch_all_hk_stocks_from_ccass()
    now_iso = datetime.utcnow().isoformat()
    added = 0

    with get_conn() as conn:
        for code, name in stocks:
            cur = conn.execute(
                "SELECT 1 FROM stock_universe WHERE stock_code = ?", (code,)
            )
            if cur.fetchone():
                conn.execute(
                    """UPDATE stock_universe
                       SET stock_name = ?, last_seen_at = ?, is_active = 1
                       WHERE stock_code = ?""",
                    (name, now_iso, code),
                )
            else:
                conn.execute(
                    """INSERT INTO stock_universe
                       (stock_code, stock_name, is_active, added_at, last_seen_at)
                       VALUES (?, ?, 1, ?, ?)""",
                    (code, name, now_iso, now_iso),
                )
                added += 1

    logger.info("Universe refreshed: %d added, %d total", added, len(stocks))
    return added


def get_active_stocks() -> list[str]:
    """攞所有 active stock codes。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT stock_code FROM stock_universe WHERE is_active = 1 ORDER BY stock_code"
        ).fetchall()
    return [r["stock_code"] for r in rows]


if __name__ == "__main__":
    refresh_universe()
