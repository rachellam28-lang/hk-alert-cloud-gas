"""Fast Longbridge backfill – self-contained, no runner.py imports.

KEY FEATURES:
- In-process singleton MCP client (not subprocess per stock)
- Skip-if-exists: only scrapes stocks not already in DB for each date
- 0.8s throttle between calls — safe rate verified 2026-06-09
- UPSERT via ON CONFLICT — safe to re-run on partially filled dates
- Logs progress every 200 stocks with ETA
- Survives quota exhaustion gracefully: partial progress preserved for next run

Usage:
    cd C:/Users/Administrator/Desktop/automatic/ccass-debug
    # Edit DATES in script or override at bottom
    python direct_backfill.py
    python direct_backfill.py --dates 2026-07-02,2026-06-30

Env:
    LONGBRIDGE_ACCESS_TOKEN must be in .env
    CCASS_PROVIDER=longbridge (set by script)
"""
import argparse
import sys, os, json, time, logging
import tempfile
from datetime import date, datetime, timezone

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ccass"))
os.environ["CCASS_PROVIDER"] = "longbridge"
# Historical backfill needs requested-date fidelity; the Longbridge CLI path
# only returns latest broker holdings and cannot serve prior dates.
os.environ["LONGBRIDGE_USE_CLI"] = "0"

from src.longbridge_provider import scrape_stock
from src.db import DB_PATH as PRIMARY_DB_PATH, get_conn
from src.scraper import _compute_concentration_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("direct_backfill")
logger.info("Using primary DB: %s", PRIMARY_DB_PATH)

# Edit this list to target specific dates
# When adding new dates, put newest first
DATES = ["2026-07-07", "2026-07-06", "2026-07-03", "2026-07-02", "2026-06-30", "2026-06-27", "2026-06-26", "2026-06-25", "2026-06-24", "2026-06-23", "2026-06-20", "2026-06-19"]


def _acquire_lock() -> bool:
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        logger.info("Lock acquired (PID %d)", os.getpid())
        return True
    except FileExistsError:
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            logger.error(
                "FATAL-003: Another backfill is already running (PID %d). Lock file: %s",
                old_pid,
                LOCK_FILE,
            )
            return False
        except (OSError, ValueError):
            logger.warning("Stale lock from dead/corrupt PID, removing.")
            os.remove(LOCK_FILE)
            return _acquire_lock()


def _release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock released")
    except OSError:
        pass


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dates",
        help="Comma-separated ISO dates newest-first. Default: built-in backlog queue.",
    )
    return parser.parse_args()
def get_active_stocks():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT stock_code FROM stock_universe WHERE is_active=1 ORDER BY stock_code"
        ).fetchall()
    return [r[0] for r in rows]


def _auth_probe(target_date: str) -> bool:
    """Distinguish a real global auth failure from a one-off stock failure."""
    try:
        snap = scrape_stock("00001", date.fromisoformat(target_date))
        return bool(snap and snap.holdings)
    except Exception:
        return False


def save_snapshot(stock_code, trade_date, snap):
    now = datetime.now(timezone.utc).isoformat()
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
            conn.execute(
                """
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
            """,
                (
                    stock_code, trade_date, snap.total_shares, snap.total_pct,
                    snap.num_participants, top5_pct, top10_pct,
                    cm.get("adj_hhi"), cm.get("broker_top5_pct"),
                    cm.get("top_broker_id"), cm.get("top_broker_name"), cm.get("top_broker_pct"),
                    cm.get("futu_pct"), cm.get("a00005_pct"), cm.get("adjusted_float"), now,
                ),
            )
            conn.execute("COMMIT")
            # Write participant-level holdings for dashboard detail
            conn.execute(
                "DELETE FROM ccass_holdings WHERE stock_code=? AND trade_date=?",
                (stock_code, trade_date),
            )
            for h in holdings:
                conn.execute(
                    """INSERT INTO ccass_holdings
                    (stock_code, trade_date, participant_id, participant_name, shares, pct_of_issued)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stock_code, trade_date, participant_id) DO UPDATE SET
                    participant_name=excluded.participant_name,
                    shares=excluded.shares,
                    pct_of_issued=excluded.pct_of_issued""",
                    (
                        stock_code, trade_date,
                        h.get("participant_id"),
                        h.get("participant_name"),
                        h.get("shares"),
                        h.get("pct_of_issued"),
                    ),
                )
        except Exception:
            conn.execute("ROLLBACK")
            raise


def backfill_date(target_date: str):
    dt = date.fromisoformat(target_date)
    stocks = get_active_stocks()
    logger.info("=== BACKFILL %s: %d stocks ===", target_date, len(stocks))

    # Skip stocks already in DB for this date
    with get_conn() as conn:
        existing = set(
            r[0]
            for r in conn.execute(
                "SELECT stock_code FROM ccass_daily WHERE trade_date=?", (target_date,)
            ).fetchall()
        )
    stocks = [s for s in stocks if s not in existing]
    logger.info("Already have %d stocks, scraping %d remaining", len(existing), len(stocks))

    if not stocks:
        logger.info("SKIP %s: all stocks already in DB", target_date)
        return 0, 0, False, len(existing)

    ok = fail = 0
    quota_exhausted = False
    auth_failed = False
    t0 = time.time()

    for i, code in enumerate(stocks, 1):
        if quota_exhausted:
            logger.warning("QUOTA EXHAUSTED at %d/%d — stopping. %d ok, %d fail. Resume tomorrow.",
                          i-1, len(stocks), ok, fail)
            fail += len(stocks) - i + 1
            break

        try:
            snap = scrape_stock(code, dt)
            if snap and snap.holdings:
                save_snapshot(code, target_date, snap)
                ok += 1
            else:
                fail += 1
        except RuntimeError as e:
            err = str(e).lower()
            if any(marker in err for marker in AUTH_FAIL_MARKERS):
                if _auth_probe(target_date):
                    logger.warning("AUTH-LIKE failure only for %s on %s, skipping: %s", code, target_date, e)
                    fail += 1
                    continue
                logger.error("AUTH FAILURE at %s for %s: %s", target_date, code, e)
                auth_failed = True
                fail += len(stocks) - i + 1
                break
            if "rate" in err or "quota" in err:
                logger.warning("RATE LIMIT at %d/%d — quota exhausted", i, len(stocks))
                quota_exhausted = True
                fail += len(stocks) - i + 1
                break
            fail += 1
            if fail <= 3:
                logger.warning("%s: %s", code, e)
        except Exception as e:
            fail += 1
            if fail <= 3:
                logger.warning("%s: %s", code, e)

        # Throttle: 0.8s/call — proven safe
        time.sleep(0.8)

        if i % 200 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(stocks) - i) / rate if rate > 0 else 0
            logger.info(
                "%d/%d (%.1f%%) ok=%d fail=%d %.1f/s ETA %.0fs",
                i, len(stocks), 100 * i / len(stocks), ok, fail, rate, eta,
            )

    elapsed = time.time() - t0
    logger.info("DONE %s: ok=%d fail=%d %.0fs", target_date, ok, fail, elapsed)
    return ok, fail, auth_failed, len(existing)


if __name__ == "__main__":
    args = parse_args()
    targets = [d.strip() for d in (args.dates or "").split(",") if d.strip()] or list(DATES)
    for dt_str in targets:
        date.fromisoformat(dt_str)

    if not _acquire_lock():
        raise SystemExit(1)

    try:
        print("=" * 60, flush=True)
        print("DIRECT LONGBRIDGE BACKFILL", flush=True)
        print(f"Targets: {targets}", flush=True)
        print("=" * 60, flush=True)

        total_ok = total_fail = 0
        t_start = time.time()
        hard_fail_dates = []
        partial_dates = []

        for dt_str in targets:
            ok, fail, auth_failed, existing = backfill_date(dt_str)
            total_ok += ok
            total_fail += fail
            if auth_failed or (existing == 0 and ok == 0 and fail > 0):
                hard_fail_dates.append(dt_str)
                break
            if fail > 0:
                partial_dates.append(dt_str)

        total_elapsed = time.time() - t_start
        print("=" * 60, flush=True)
        print("ALL DONE: ok=%d fail=%d %.1fmin" % (total_ok, total_fail, total_elapsed / 60), flush=True)
        if hard_fail_dates:
            print(f"HARD FAIL DATES: {hard_fail_dates}", flush=True)
        elif partial_dates:
            print(f"PARTIAL DATES: {partial_dates}", flush=True)
        print("=" * 60, flush=True)

        if hard_fail_dates:
            raise SystemExit(2)
        if partial_dates:
            raise SystemExit(3)
        raise SystemExit(0)
    finally:
        _release_lock()
