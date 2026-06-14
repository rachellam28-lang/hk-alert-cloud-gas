"""
Compute BOTH concentration metrics + trend deltas for dates with missing data.
Uses holdings_holdings raw data — NO re-scraping needed.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import date
from src.db import get_conn, init_db, DB_PATH
from src.trend import compute_trends_for_date
from src.logger import setup_logger
import sqlite3

logger = setup_logger("compute_metrics")

def compute_concentration_for_date(trade_date: str) -> int:
    """Recompute concentration metrics from holdings_holdings for given date."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    updated = 0
    
    # Get stocks that have holdings but missing metrics
    stocks = conn.execute("""
        SELECT DISTINCT h.stock_code
        FROM holdings_holdings h
        LEFT JOIN ccass_daily d ON h.stock_code = d.stock_code AND h.trade_date = d.trade_date
        WHERE h.trade_date = ?
          AND (d.adj_hhi IS NULL OR d.stock_code IS NULL)
    """, (trade_date,)).fetchall()
    
    if not stocks:
        conn.close()
        return 0
    
    for (stock_code,) in stocks:
        holdings = conn.execute("""
            SELECT participant_id, participant_name, shares, pct_of_issued
            FROM ccass_holdings
            WHERE trade_date = ? AND stock_code = ?
        """, (trade_date, stock_code)).fetchall()
        
        if not holdings:
            continue
        
        # Convert to list of dicts for computation
        holdings_list = [dict(h) for h in holdings]
        clean = [h for h in holdings_list if h.get("shares")]
        total = sum(h["shares"] for h in clean)
        if total <= 0:
            continue
        
        a5_shares = sum(h["shares"] for h in clean if h.get("participant_id") == "A00005")
        adjusted_float = total - a5_shares
        
        adjusted = sorted(
            [h for h in clean if h.get("participant_id") != "A00005"],
            key=lambda h: h["shares"], reverse=True,
        )
        brokers = [h for h in adjusted if str(h.get("participant_id", "")).startswith("B")]
        top_broker = brokers[0] if brokers else None
        futu_shares = sum(h["shares"] for h in adjusted if h.get("participant_id") == "B01955")
        
        if adjusted_float > 0:
            adj_hhi = sum((h["shares"] / adjusted_float * 100) ** 2 for h in adjusted)
            btop5 = sum(h["shares"] for h in brokers[:5]) / adjusted_float * 100
            tbp = top_broker["shares"] / adjusted_float * 100 if top_broker else 0.0
            fp = futu_shares / adjusted_float * 100
        else:
            adj_hhi = btop5 = tbp = fp = 0.0
        
        a5_pct = round(a5_shares / total * 100, 2)
        
        # Update or insert
        existing = conn.execute(
            "SELECT stock_code FROM ccass_daily WHERE trade_date = ? AND stock_code = ?",
            (trade_date, stock_code)
        ).fetchone()
        
        if existing:
            conn.execute("""
                UPDATE ccass_daily
                SET adj_hhi = ?, broker_top5_pct = ?, top_broker_id = ?,
                    top_broker_name = ?, top_broker_pct = ?,
                    futu_pct = ?, a00005_pct = ?, adjusted_float = ?
                WHERE trade_date = ? AND stock_code = ?
            """, (
                round(adj_hhi, 1), round(btop5, 2),
                top_broker["participant_id"] if top_broker else "",
                (top_broker.get("participant_name") or "")[:40] if top_broker else "",
                round(tbp, 2), round(fp, 2), a5_pct, adjusted_float,
                trade_date, stock_code
            ))
        else:
            conn.execute("""
                INSERT INTO ccass_daily (stock_code, trade_date, adj_hhi, broker_top5_pct,
                    top_broker_id, top_broker_name, top_broker_pct,
                    futu_pct, a00005_pct, adjusted_float, validation_failed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                stock_code, trade_date, round(adj_hhi, 1), round(btop5, 2),
                top_broker["participant_id"] if top_broker else "",
                (top_broker.get("participant_name") or "")[:40] if top_broker else "",
                round(tbp, 2), round(fp, 2), a5_pct, adjusted_float,
            ))
        
        updated += 1
    
    conn.commit()
    conn.close()
    return updated


def main():
    init_db()
    
    conn = sqlite3.connect(str(DB_PATH))
    
    # Dates needing concentration metrics
    dates = conn.execute("""
        SELECT trade_date, COUNT(*) as total,
               SUM(CASE WHEN adj_hhi IS NOT NULL THEN 1 ELSE 0 END) as with_metrics
        FROM ccass_daily
        GROUP BY trade_date
        HAVING total > 100 AND with_metrics < total * 0.99
        ORDER BY trade_date
    """).fetchall()
    conn.close()
    
    logger.info("=" * 60)
    logger.info("CONCENTRATION METRICS COMPUTATION (from holdings)")
    logger.info("=" * 60)
    
    for trade_date, total, have in dates:
        need = total - have
        pct = have * 100.0 / total if total else 0
        logger.info(f"  {trade_date}: {have}/{total} ({pct:.0f}%) — need ~{need}")
    
    print()
    
    for trade_date, total, have in dates:
        logger.info(f"Computing concentration for {trade_date}...")
        try:
            updated = compute_concentration_for_date(trade_date)
            logger.info(f"  {trade_date}: updated {updated} stocks")
        except Exception as e:
            logger.exception(f"  {trade_date} FAILED: {e}")
    
    # Final state
    logger.info("=" * 60)
    logger.info("FINAL STATE:")
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT trade_date, COUNT(*) as total,
               SUM(CASE WHEN adj_hhi IS NOT NULL THEN 1 ELSE 0 END) as with_metrics
        FROM ccass_daily
        GROUP BY trade_date
        HAVING total > 100
        ORDER BY trade_date DESC LIMIT 15
    """).fetchall()
    conn.close()
    
    for trade_date, total, have in rows:
        pct = have * 100.0 / total if total else 0
        status = "✅" if pct >= 99 else "⚠️" if pct >= 50 else "🔴"
        logger.info(f"  {trade_date}: {have}/{total} ({pct:.0f}%) {status}")

if __name__ == "__main__":
    main()
