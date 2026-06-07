"""HKEX scraper backfill — in-process, fast, for remaining dates."""
import sys, os, time, sqlite3, logging
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ccass"))

from src.scraper import CCASSScraper, _compute_concentration_metrics

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ccass", "ccass.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger("hkex_backfill")

DATES = ["2026-06-05"]

def get_conn():
    return sqlite3.connect(DB_PATH)

def get_active_stocks():
    with get_conn() as conn:
        rows = conn.execute("SELECT stock_code FROM stock_universe WHERE is_active=1 ORDER BY stock_code").fetchall()
    return [r[0] for r in rows]

def save_snapshot(stock_code, trade_date, snap):
    now = datetime.utcnow().isoformat()
    holdings = snap.holdings
    sorted_shares = sorted([h["shares"] for h in holdings if h.get("shares")], reverse=True)
    top5 = sum(sorted_shares[:5])
    top10 = sum(sorted_shares[:10])
    top5_pct = round(top5 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    top10_pct = round(top10 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    cm = _compute_concentration_metrics(holdings)

    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""
                INSERT INTO ccass_daily
                (stock_code, trade_date, total_shares, total_pct, num_participants,
                 top5_pct, top10_pct, adj_hhi, broker_top5_pct, top_broker_id,
                 top_broker_name, top_broker_pct, futu_pct, a00005_pct,
                 adjusted_float, scraped_at, validation_failed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                 total_shares=excluded.total_shares, total_pct=excluded.total_pct,
                 num_participants=excluded.num_participants, top5_pct=excluded.top5_pct,
                 top10_pct=excluded.top10_pct, adj_hhi=excluded.adj_hhi,
                 broker_top5_pct=excluded.broker_top5_pct, top_broker_id=excluded.top_broker_id,
                 top_broker_name=excluded.top_broker_name, top_broker_pct=excluded.top_broker_pct,
                 futu_pct=excluded.futu_pct, a00005_pct=excluded.a00005_pct,
                 adjusted_float=excluded.adjusted_float, scraped_at=excluded.scraped_at,
                 validation_failed=0
            """, (
                stock_code, trade_date, snap.total_shares, snap.total_pct,
                snap.num_participants, top5_pct, top10_pct,
                cm.get("adj_hhi"), cm.get("broker_top5_pct"),
                cm.get("top_broker_id"), cm.get("top_broker_name"), cm.get("top_broker_pct"),
                cm.get("futu_pct"), cm.get("a00005_pct"), cm.get("adjusted_float"), now,
            ))
            # P3: Save holdings (participant breakdown) — was MISSING!
            conn.execute(
                "DELETE FROM ccass_holdings WHERE stock_code = ? AND trade_date = ?",
                (stock_code, trade_date),
            )
            conn.executemany(
                """INSERT INTO ccass_holdings
                     (stock_code, trade_date, participant_id, participant_name,
                      shares, pct_of_issued)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (stock_code, trade_date,
                     h["participant_id"], h["participant_name"],
                     h["shares"], h["pct_of_issued"])
                    for h in holdings
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def backfill_date(scraper, target_date: str):
    dt = date.fromisoformat(target_date)
    stocks = get_active_stocks()

    # Skip existing
    with get_conn() as conn:
        existing = set(r[0] for r in conn.execute(
            "SELECT stock_code FROM ccass_daily WHERE trade_date=?", (target_date,)
        ).fetchall())
    todo = [s for s in stocks if s not in existing]
    logger.info("=== HKEX BACKFILL %s: have=%d need=%d ===", target_date, len(existing), len(todo))

    if not todo:
        logger.info("SKIP: all done")
        return 0, 0

    ok = fail = 0
    t0 = time.time()

    for i, code in enumerate(todo, 1):
        try:
            snap = scraper.scrape_stock(code, dt)
            if snap and snap.holdings:
                save_snapshot(code, target_date, snap)
                ok += 1
            else:
                fail += 1
                if fail <= 5:
                    logger.warning("%s: no data", code)
        except Exception as e:
            fail += 1
            logger.warning("%s: %s", code, e)
            if "block" in str(e).lower() or "503" in str(e):
                logger.error("HKEX BLOCK DETECTED — stopping")
                break

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            logger.info("%d/%d ok=%d fail=%d %.1f/s ETA %.0fs",
                        i, len(todo), ok, fail, rate, eta)

    elapsed = time.time() - t0
    logger.info("DONE %s: ok=%d fail=%d %.0fs (%.1f/s)",
                target_date, ok, fail, elapsed, len(todo)/elapsed if elapsed > 0 else 0)
    return ok, fail


if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("HKEX LOCAL BACKFILL", flush=True)
    print(f"Targets: {DATES}", flush=True)
    print("=" * 60, flush=True)

    s = CCASSScraper("Mozilla/5.0", delay_min=1.5, delay_max=3.0, timeout=30, max_retries=2)
    total_ok = total_fail = 0
    t_start = time.time()

    for dt_str in DATES:
        ok, fail = backfill_date(s, dt_str)
        total_ok += ok
        total_fail += fail
        if fail > 0 and "BLOCK" in str(fail):
            break

    total_elapsed = time.time() - t_start
    print("=" * 60, flush=True)
    print(f"ALL DONE: ok={total_ok} fail={total_fail} {total_elapsed/60:.1f}min", flush=True)
    print("=" * 60, flush=True)
