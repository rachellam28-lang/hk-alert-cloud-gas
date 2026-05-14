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

    # Parse xlsx — scan all sheets, pick the one with most stock codes
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(resp.content), data_only=True)  # read_only skips rows past dimension tag
    logger.info("Sheets in xlsx: %s", wb.sheetnames)

    best_stocks: list[tuple[str, str]] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        stocks: list[tuple[str, str]] = []
        row_count = 0
        for row in ws.iter_rows(values_only=True):
            row_count += 1
            # Log first 5 rows so we can see actual xlsx structure
            if row_count <= 5:
                logger.info("xlsx row %d: %s", row_count, [repr(c) for c in (row[:5] if row else [])])
            if not row or row[0] is None:
                continue
            raw = row[0]
            # Handle float (e.g. 1.0), int (1), or string ('00001')
            if isinstance(raw, float):
                if raw != int(raw):
                    continue
                raw = int(raw)
            if isinstance(raw, int):
                if raw <= 0 or raw > 99999:
                    continue
                first = str(raw)
            else:
                first = str(raw).strip().lstrip("'")  # xlsx stores as "'00001'" with apostrophe
                if first.endswith('.0'):
                    first = first[:-2]
            # Skip header rows (e.g. "Stock Code", "List of Securities")
            if not first or not first[0].isdigit():
                continue
            # Stock code: pure digits, length 1-5
            if not (first.isdigit() and 1 <= len(first) <= 5):
                continue
            # Filter: Equity + REITs only (skip warrants DW CBBCs debt)
            category = str(row[2]).strip() if len(row) > 2 and row[2] else ""
            if category not in ("Equity", "Real Estate Investment Trusts", ""):
                continue
            code = first.zfill(5)
            name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            stocks.append((code, name))
        logger.info("Sheet '%s': %d rows total, %d stocks found", sheet_name, row_count, len(stocks))
        if len(stocks) > len(best_stocks):
            best_stocks = stocks

    logger.info("Found %d stocks total (best sheet)", len(best_stocks))
    return best_stocks


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
