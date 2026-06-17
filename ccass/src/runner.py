"""Main daily runner.

Workflow:
1. Check 今日係咪 trading day。如果唔係，exit。
2. 攞 universe (refresh weekly)
3. Scrape 全部股票
4. Compute trends
5. Detect alerts → Telegram
6. Detect HOLDINGS events (deposit/transfer) → Telegram
7. Log run metadata
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from datetime import datetime, date, timedelta
from pathlib import Path

import yaml

try:
    from zoneinfo import ZoneInfo
    HK_TZ = ZoneInfo("Asia/Hong_Kong")
except Exception:  # pragma: no cover - fallback for older runtimes
    import pytz
    HK_TZ = pytz.timezone("Asia/Hong_Kong")

from src.db import init_db, get_conn
from src.logger import setup_logger
from src.trading_calendar import today_hk, is_trading_day, previous_trading_day, last_n_trading_days
from src.universe import refresh_universe, get_active_stocks
from src.scraper import HOLDINGSScraper, save_snapshot, HKEXBlockedError
from src.trend import compute_trends_for_date
from src.alerts import detect_alerts, send_alerts, send_admin_alert, send_event_alerts

# scanner/events_detector.py lives at project root (not inside holdings/),
# so add project root to path for the import
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scanner.events_detector import detect_events  # type: ignore[import-unused]

logger = setup_logger("runner")
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
STATE_DIR = Path(__file__).parent.parent / "state"
COOLDOWN_PATH = STATE_DIR / "hkex_cooldown.json"
COOLDOWN_HOURS = 12
MIN_SUCCESS_COVERAGE = 0.95


def _date_coverage(date_str: str) -> tuple[int, int, float]:
    """Return valid dashboard-equity coverage for a trade date."""
    with get_conn() as conn:
        active_row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM stock_universe
            WHERE is_active=1
              AND stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04621'
              AND stock_code NOT LIKE '8%'
            """
        ).fetchone()
        active_total = active_row["n"] if active_row else 0
        date_row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM holdings_daily
            WHERE trade_date = ? AND validation_failed = 0
              AND stock_code NOT LIKE '029%'
              AND stock_code NOT LIKE '04621'
              AND stock_code NOT LIKE '8%'
            """,
            (date_str,),
        ).fetchone()
        date_count = date_row["n"] if date_row else 0
    coverage = date_count / active_total if active_total else 0.0
    return date_count, active_total, coverage


def _reliable_trend_windows(target_date: date, windows: list[int]) -> list[int]:
    """Only compute trend windows whose reference date has complete data."""
    if not windows:
        return []
    max_window = max(windows)
    all_tdays = last_n_trading_days(target_date, max_window + 1)
    reliable: list[int] = []
    for w in windows:
        if len(all_tdays) <= w:
            continue
        ref_date = all_tdays[-(w + 1)].strftime("%Y-%m-%d")
        ref_count, ref_total, ref_cov = _date_coverage(ref_date)
        if ref_total and ref_cov >= MIN_SUCCESS_COVERAGE:
            reliable.append(w)
        else:
            logger.warning(
                "Trend %sd skipped for %s: ref %s coverage %.1f%% (%d/%d)",
                w, target_date, ref_date, ref_cov * 100, ref_count, ref_total,
            )
    return reliable


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _apply_runtime_tuning(config: dict) -> dict:
    """Apply env-driven runtime tuning without mutating the base config file."""
    sc_cfg = config.setdefault("scraping", {})
    fast = os.environ.get("HOLDINGS_FAST", "0") == "1"
    ultra_fast = os.environ.get("HOLDINGS_ULTRA_FAST", "0") == "1"
    backfill_fast = os.environ.get("HOLDINGS_BACKFILL_FAST", "0") == "1"
    skip_mc = os.environ.get("HOLDINGS_SKIP_MARKET_CAP_FETCH", "0") == "1"

    if fast:
        sc_cfg["delay_min_seconds"] = min(float(sc_cfg.get("delay_min_seconds", 4.0)), 1.0)
        sc_cfg["delay_max_seconds"] = min(float(sc_cfg.get("delay_max_seconds", 10.0)), 2.0)
        sc_cfg["parallel_workers"] = max(int(sc_cfg.get("parallel_workers", 1)), 8)
        sc_cfg["timeout_seconds"] = min(int(sc_cfg.get("timeout_seconds", 30)), 24)
        sc_cfg["max_retries"] = min(int(sc_cfg.get("max_retries", 3)), 2)
        skip_mc = True

    if ultra_fast:
        sc_cfg["delay_min_seconds"] = min(float(sc_cfg.get("delay_min_seconds", 4.0)), 0.15)
        sc_cfg["delay_max_seconds"] = min(float(sc_cfg.get("delay_max_seconds", 10.0)), 0.5)
        sc_cfg["parallel_workers"] = max(int(sc_cfg.get("parallel_workers", 1)), 16)
        sc_cfg["timeout_seconds"] = min(int(sc_cfg.get("timeout_seconds", 30)), 18)
        sc_cfg["max_retries"] = min(int(sc_cfg.get("max_retries", 3)), 1)
        skip_mc = True
        config["_runtime_ultra_fast_mode"] = True

    if backfill_fast:
        # Sequential backfill only. Keep FATAL-003 intact, but cap dead-stock wait time
        # so one or two hanging codes do not stall an entire trading day.
        sc_cfg["delay_min_seconds"] = min(float(sc_cfg.get("delay_min_seconds", 4.0)), 2.0)
        sc_cfg["delay_max_seconds"] = min(float(sc_cfg.get("delay_max_seconds", 10.0)), 4.0)
        sc_cfg["parallel_workers"] = 1
        sc_cfg["timeout_seconds"] = min(int(sc_cfg.get("timeout_seconds", 30)), 20)
        sc_cfg["max_retries"] = min(int(sc_cfg.get("max_retries", 3)), 1)
        skip_mc = True
        config["_runtime_backfill_fast_mode"] = True

    sc_cfg["skip_market_cap_fetch"] = skip_mc
    config["_runtime_fast_mode"] = fast
    return config


def _active_cooldown_reason() -> str | None:
    if not COOLDOWN_PATH.exists():
        return None
    try:
        data = json.loads(COOLDOWN_PATH.read_text(encoding="utf-8"))
        until = datetime.fromisoformat(data["cooldown_until_utc"])
        from datetime import timezone
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < until:
            return f"HKEX cooldown active until {until.isoformat()}: {data.get('reason', '')}"
    except Exception:
        return "HKEX cooldown marker is corrupt; refusing scrape until marker is inspected"
    return None


def _mark_cooldown(reason: str) -> None:
    from datetime import timezone
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    payload = {
        "created_at_utc": now.isoformat(),
        "cooldown_until_utc": (now + timedelta(hours=COOLDOWN_HOURS)).isoformat(),
        "reason": reason[:500],
    }
    tmp = COOLDOWN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(COOLDOWN_PATH)


def _clear_cooldown() -> None:
    try:
        if COOLDOWN_PATH.exists():
            COOLDOWN_PATH.unlink()
    except OSError:
        logger.warning("Failed to clear cooldown marker: %s", COOLDOWN_PATH)


def should_refresh_universe(force: bool = False) -> bool:
    """每週一 refresh universe，或者 universe 係空。"""
    if force:
        return True
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM stock_universe WHERE is_active = 1"
        ).fetchone()
        if row["n"] < 100:
            return True
    return today_hk().weekday() == 0  # Monday


PER_STOCK_TIMEOUT = 180  # seconds — skip stock if scrape takes longer

def _scrape_stock_worker(args: tuple) -> tuple[str, bool, str]:
    """Module-level worker for ProcessPoolExecutor. Picklable args only.
    Returns (stock_code, success, error_msg_or_empty).
    """
    stock_code, date_str, sc_cfg = args
    from datetime import date as dt_date
    from src.scraper import HOLDINGSScraper

    query_date = dt_date.fromisoformat(date_str)
    scraper = HOLDINGSScraper(
        user_agent=sc_cfg["user_agent"],
        delay_min=sc_cfg["delay_min_seconds"],
        delay_max=sc_cfg["delay_max_seconds"],
        timeout=sc_cfg["timeout_seconds"],
        max_retries=sc_cfg["max_retries"],
    )
    try:
        snap = scraper.scrape_stock(stock_code, query_date)
        if snap:
            from src.scraper import save_snapshot
            save_snapshot(snap)
            return (stock_code, True, "")
        return (stock_code, False, "no data")
    except Exception as e:
        return (stock_code, False, str(e)[:200])


def _scrape_parallel(
    stocks: list[str],
    query_date: date,
    sc_cfg: dict,
    n_workers: int,
) -> tuple[int, int, list[str]]:
    """Scrape stocks with N ProcessPool workers — each worker is a subprocess
    that can be truly killed on timeout (unlike threads where cloudscraper hangs).
    """
    total = len(stocks)
    attempted = 0
    succeeded = 0
    failed_stocks: list[str] = []
    done_count = 0

    date_str = query_date.isoformat()
    args_list = [(code, date_str, sc_cfg) for code in stocks]

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        fut_map = {pool.submit(_scrape_stock_worker, args): args[0] for args in args_list}

        for fut in as_completed(fut_map):
            code = fut_map[fut]
            attempted += 1
            try:
                _, ok, err = fut.result(timeout=PER_STOCK_TIMEOUT)
                if ok:
                    succeeded += 1
                else:
                    failed_stocks.append(code)
                    if err:
                        logger.debug("Stock %s: %s", code, err)
            except TimeoutError:
                logger.warning("Stock %s timed out after %ds", code, PER_STOCK_TIMEOUT)
                failed_stocks.append(code)
            except Exception as e:
                logger.warning("Parallel scrape %s failed: %s", code, e)
                failed_stocks.append(code)

            # Progress logging
            done_count += 1
            if done_count % 50 == 0 or done_count == total:
                pct = 100.0 * done_count / total
                logger.info("Progress: %d/%d (%.1f%%)", done_count, total, pct)

    logger.info(
        "Parallel scrape done: %d/%d succeeded, %d failed",
        succeeded, attempted, len(failed_stocks),
    )
    return (attempted, succeeded, failed_stocks)


def _restore_db():
    """Restore holdings.db from holdings.db.gz if DB missing or empty (first run / fresh checkout)."""
    import gzip, shutil
    db_path = Path(__file__).parent.parent / "holdings.db"
    db_gz_path = Path(__file__).parent.parent / "holdings.db.gz"
    if db_path.exists() and db_path.stat().st_size > 0:
        return  # Already have a valid DB
    if db_gz_path.exists():
        logger.info("Restoring holdings.db from holdings.db.gz (%d bytes)", db_gz_path.stat().st_size)
        # ✅ P1-9: atomic restore via temp file (prevents race condition)
        tmp_path = db_path.with_suffix(".db.tmp")
        with gzip.open(db_gz_path, 'rb') as f_in:
            with open(tmp_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        tmp_path.replace(db_path)
        logger.info("Restored holdings.db: %d bytes", db_path.stat().st_size)


def run_daily(
    target_date: date | None = None,
    skip_scrape: bool = False,
    skip_alerts: bool = False,
    force_universe_refresh: bool = False,
    shard: int | None = None,
    shard_total: int | None = None,
    query_date_override: date | None = None,
    out_path: str | None = None,
) -> int:
    """
    Run 一個 cycle。
    Returns: 0 = success, 1 = partial, 2 = failed
    """
    # PID lock check — prevent cron + backfill from running simultaneously
    # skip_alerts=True means called from backfill (lock already held by backfill_range)
    if not skip_alerts:
        import atexit
        from scripts.backfill import _acquire_lock, _release_lock
        if not _acquire_lock():
            logger.error("FATAL-003: Backfill already running, skipping cron run")
            return 2
        atexit.register(_release_lock)  # auto-release on any exit

    init_db()
    _restore_db()  # Decompress holdings.db.gz if DB is empty (fresh checkout)
    config = _apply_runtime_tuning(load_config())
    target_date = target_date or today_hk()

    if not skip_scrape:
        provider = os.environ.get("HOLDINGS_PROVIDER", "hkex").lower()
        if provider == "hkex":
            cooldown_reason = _active_cooldown_reason()
            if cooldown_reason:
                logger.error("FATAL-003: %s", cooldown_reason)
                return 2

    logger.info("=" * 60)
    logger.info("HOLDINGS daily run for %s", target_date)
    logger.info("=" * 60)

    if not is_trading_day(target_date):
        # In shard mode, we're scraping a specific historical date — don't skip
        if not query_date_override:
            logger.info("%s is not a trading day, skip", target_date)
            return 0

    # HOLDINGS 通常公布前一個 trading day 嘅 data
    # 所以 query_date = 對上一次 trading day
    if query_date_override:
        query_date = query_date_override
    else:
        query_date = previous_trading_day(target_date)
    logger.info("Querying HOLDINGS data for %s", query_date)

    # 1. Start run log
    now_iso = datetime.now(tz=HK_TZ).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO scrape_runs (run_date, started_at, status)
               VALUES (?, ?, 'running')""",
            (target_date.strftime("%Y-%m-%d"), now_iso),
        )
        run_id = cur.lastrowid

    failed_stocks: list[str] = []
    succeeded = 0
    attempted = 0
    alerts_found: list[dict] = []

    try:
        # 2. Universe
        if should_refresh_universe(force_universe_refresh):
            try:
                refresh_universe()
            except Exception as e:
                logger.error("Universe refresh failed: %s", e)
                send_admin_alert(f"Universe refresh 失敗: {e}")

        stocks = get_active_stocks()
        logger.info("Universe: %d active stocks", len(stocks))

        # Shard support: slice stocks list for parallel shard scraping
        if shard is not None and shard_total is not None and shard_total > 1:
            stocks = stocks[shard::shard_total]
            logger.info("Shard %d/%d: %d stocks", shard + 1, shard_total, len(stocks))

        # Optional: limit to top-N stocks for speed (config max_stocks)
        max_stocks = config["scraping"].get("max_stocks")
        if max_stocks and len(stocks) > max_stocks:
            logger.info("Limiting scrape to top %d stocks (config max_stocks)", max_stocks)
            stocks = stocks[:max_stocks]

        if not stocks:
            raise RuntimeError("Empty universe — cannot proceed")

        # Resume mode: if today's run already wrote some rows, skip them on restart.
        # This makes an interrupted run restartable without re-scraping completed stocks.
        existing_rows = 0
        if not out_path and not skip_scrape:
            with get_conn() as conn:
                existing_row = conn.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM ccass_daily
                    WHERE trade_date = ? AND validation_failed = 0
                    """,
                    (query_date.strftime("%Y-%m-%d"),),
                ).fetchone()
                existing_rows = existing_row["n"] if existing_row else 0
            if existing_rows:
                before = len(stocks)
                with get_conn() as conn:
                    done_codes = {
                        r["stock_code"]
                        for r in conn.execute(
                            """
                            SELECT stock_code
                            FROM ccass_daily
                            WHERE trade_date = ? AND validation_failed = 0
                            """,
                            (query_date.strftime("%Y-%m-%d"),),
                        ).fetchall()
                    }
                stocks = [code for code in stocks if code not in done_codes]
                skipped = before - len(stocks)
                if skipped:
                    logger.info(
                        "Resume mode: skipping %d already-scraped stocks for %s",
                        skipped, query_date,
                    )
                if not stocks:
                    logger.info(
                        "Resume mode: all %d stocks already scraped for %s; continuing to trends/export",
                        existing_rows, query_date,
                    )

        # 3. Scrape
        collected_for_shard: list[dict] = []  # snapshots for shard JSON (out_path mode)
        if not skip_scrape:
            sc_cfg = config["scraping"]
            n_workers = sc_cfg.get("parallel_workers", 1)
            if config.get("_runtime_ultra_fast_mode") and len(stocks) > 1:
                # In ultra-fast mode, split the remaining universe across a few more workers
                # if the configured count is still conservative.
                n_workers = max(n_workers, 16)

            if n_workers > 1 and len(stocks) > 100:
                attempted, succeeded, failed_stocks = _scrape_parallel(
                    stocks, query_date, sc_cfg, n_workers,
                )
            else:
                # Sequential: subprocess per stock — kills reliably, ~2s overhead but never hangs.
                import subprocess as _sp
                import os as _os
                HARD_TIMEOUT = sc_cfg["timeout_seconds"] * sc_cfg["max_retries"] + 30  # P0-2: dynamic timeout
                _scrape_one = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "scrape_one.py")
                for i, code in enumerate(stocks, 1):
                    attempted += 1
                    if i % 50 == 0:
                        logger.info("Progress: %d/%d (%.1f%%)", i, len(stocks), 100 * i / len(stocks))
                    try:
                        result = _sp.run(
                            [sys.executable, _scrape_one, code, query_date.strftime("%Y-%m-%d"),
                             sc_cfg["user_agent"],
                             str(sc_cfg["delay_min_seconds"]),
                             str(sc_cfg["delay_max_seconds"]),
                             str(sc_cfg["timeout_seconds"]),
                             str(sc_cfg["max_retries"])],
                            capture_output=True, text=True, timeout=HARD_TIMEOUT,
                        )
                        if result.returncode != 0:
                            failed_stocks.append(code)
                            continue
                        data = json.loads(result.stdout)
                        if data.get("ok"):
                            # Save to DB in main process (avoids SQLite lock contention)
                            try:
                                with get_conn() as conn:
                                    now_iso = datetime.utcnow().isoformat()
                                    conn.execute("""
                                        INSERT OR REPLACE INTO ccass_daily
                                        (stock_code, trade_date, total_shares, total_pct,
                                         num_participants, top5_pct, top10_pct,
                                         adj_hhi, broker_top5_pct, top_broker_id,
                                         top_broker_name, top_broker_pct,
                                         futu_pct, a00005_pct, adjusted_float,
                                         scraped_at, validation_failed)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                                    """, (
                                        data["stock_code"], data["trade_date"],
                                        data.get("total_shares"), data.get("total_pct"),
                                        data.get("num_participants"), data.get("top5_pct"),
                                        data.get("top10_pct"), data.get("adj_hhi"),
                                        data.get("broker_top5_pct"), data.get("top_broker_id"),
                                        data.get("top_broker_name"), data.get("top_broker_pct"),
                                        data.get("futu_pct"), data.get("a00005_pct"),
                                        data.get("adjusted_float"),
                                        now_iso,
                                    ))
                                    # P1-5: DELETE old holdings + INSERT new (atomic replace)
                                    conn.execute(
                                        "DELETE FROM ccass_holdings WHERE stock_code = ? AND trade_date = ?",
                                        (data["stock_code"], data["trade_date"]),
                                    )
                                    for h in data.get("holdings", []):
                                        conn.execute("""
                                            INSERT OR REPLACE INTO ccass_holdings
                                            (stock_code, trade_date, participant_id,
                                             participant_name, shares, pct_of_issued)
                                            VALUES (?, ?, ?, ?, ?, ?)
                                        """, (
                                            data["stock_code"], data["trade_date"],
                                            h.get("participant_id"), h.get("participant_name"),
                                            h.get("shares"), h.get("pct_of_issued"),
                                        ))
                            except Exception as e:
                                logger.error("DB save failed for %s: %s", code, e)
                                failed_stocks.append(code)
                                continue
                            succeeded += 1
                            if out_path:
                                collected_for_shard.append({
                                    "stock_code": data["stock_code"],
                                    "trade_date": data["trade_date"],
                                    "total_shares": data.get("total_shares"),
                                    "total_pct": data.get("total_pct"),
                                    "num_participants": data.get("num_participants", 0),
                                    "holdings": data.get("holdings", []),
                                })
                        else:
                            failed_stocks.append(code)
                    except _sp.TimeoutExpired:
                        logger.warning("Stock %s timed out after %ds — skipping", code, HARD_TIMEOUT)
                        failed_stocks.append(code)
                    except Exception as e:
                        logger.exception("Unexpected error on %s", code)
                        failed_stocks.append(code)

        # Shard output mode: write artifact JSON + early return.
        # Trends / alerts / events / holdings.json are handled by the merge phase.
        if out_path:
            _write_shard_output(
                out_path, query_date, shard, shard_total,
                len(stocks), succeeded, failed_stocks, collected_for_shard,
            )
            logger.info(
                "Shard %s/%s: wrote %d snapshots → %s",
                shard, shard_total, len(collected_for_shard), out_path,
            )
            with get_conn() as conn:
                conn.execute(
                    """UPDATE scrape_runs
                         SET finished_at=?, stocks_attempted=?,
                             stocks_succeeded=?, stocks_failed=?, status=?
                       WHERE id=?""",
                    (
                        datetime.utcnow().isoformat(), attempted, succeeded,
                        len(failed_stocks),
                        "success" if not failed_stocks else "partial",
                        run_id,
                    ),
                )
            coverage = succeeded / max(attempted, 1)
            return 0 if coverage >= MIN_SUCCESS_COVERAGE else 1

        # Official outputs must only be produced from complete date snapshots.
        # Partial DB rows are useful for resume, but unsafe for dashboard stats.
        date_str = query_date.strftime("%Y-%m-%d")
        date_count, active_total, date_coverage = _date_coverage(date_str)
        if date_coverage < MIN_SUCCESS_COVERAGE:
            finished_iso = datetime.utcnow().isoformat()
            with get_conn() as conn:
                conn.execute(
                    """UPDATE scrape_runs SET
                         finished_at = ?, stocks_attempted = ?,
                         stocks_succeeded = ?, stocks_failed = ?,
                         status = ?,
                         error_summary = ?
                       WHERE id = ?""",
                    (
                        finished_iso,
                        attempted,
                        succeeded,
                        len(failed_stocks),
                        "partial",
                        (
                            f"date coverage {date_count}/{active_total} "
                            f"({date_coverage * 100:.1f}%)"
                        ),
                        run_id,
                    ),
                )
            logger.error(
                "Date coverage %.1f%% (%d/%d) < %.1f%%; skipping trends/alerts/export for %s",
                date_coverage * 100,
                date_count,
                active_total,
                MIN_SUCCESS_COVERAGE * 100,
                date_str,
            )
            return 1

        # 4. Trends
        trend_windows = _reliable_trend_windows(query_date, config["trend_windows"])
        if not trend_windows:
            finished_iso = datetime.utcnow().isoformat()
            with get_conn() as conn:
                conn.execute(
                    """UPDATE scrape_runs SET
                         finished_at = ?, stocks_attempted = ?,
                         stocks_succeeded = ?, stocks_failed = ?,
                         status = ?,
                         error_summary = ?
                       WHERE id = ?""",
                    (
                        finished_iso,
                        attempted,
                        succeeded,
                        len(failed_stocks),
                        "partial",
                        "no complete trend reference dates",
                        run_id,
                    ),
                )
            logger.error(
                "No complete trend reference dates for %s; skipping alerts/export",
                date_str,
            )
            return 1
        try:
            compute_trends_for_date(query_date, trend_windows)
        except Exception as e:
            logger.exception("Trend computation failed")
            send_admin_alert(f"Trend computation 失敗: {e}")

        # 5. Alerts
        if not skip_alerts:
            alert_cfg = config["alerts"]
            alerts_found = detect_alerts(
                query_date,
                spike_threshold_pct=alert_cfg["spike_threshold_pct"],
                consecutive_days=alert_cfg["consecutive_days"],
                consecutive_min_daily_pct=alert_cfg["consecutive_min_daily_pct"],
            )
            sent = send_alerts(
                alerts_found,
                query_date,
                throttle_seconds=alert_cfg["telegram_throttle_seconds"],
                max_per_batch=alert_cfg["max_alerts_per_batch"],
                summary_only_threshold=alert_cfg["summary_only_threshold"],
            )
            logger.info("Sent %d alert(s)", sent)

        # 5.5. HOLDINGS Events (Deposit / Transfer)
        try:
            yesterday_date = previous_trading_day(query_date)
            events_logged = _detect_and_log_events(query_date, yesterday_date)
            if events_logged:
                logger.info("Logged %d HOLDINGS events (deposit/transfer)", len(events_logged))
                if not skip_alerts:
                    ev_sent = send_event_alerts(events_logged, query_date)
                    logger.info("Sent %d event alert(s)", ev_sent)
            else:
                logger.info("No HOLDINGS events detected")
        except Exception as e:
            logger.exception("Event detection failed")
            send_admin_alert(f"Event detection 失敗: {e}")

        # 6. Run summary
        fail_rate = len(failed_stocks) / max(attempted, 1)
        if fail_rate > 0.05:
            send_admin_alert(
                f"⚠️ Scrape fail rate {fail_rate*100:.1f}% "
                f"({len(failed_stocks)}/{attempted})\n"
                f"Sample failed: {failed_stocks[:10]}"
            )

        coverage = succeeded / max(attempted, 1) if attempted else 1.0
        status = "success" if coverage >= MIN_SUCCESS_COVERAGE else "partial"
        finished_iso = datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute(
                """UPDATE scrape_runs SET
                     finished_at = ?, stocks_attempted = ?,
                     stocks_succeeded = ?, stocks_failed = ?,
                     status = ?,
                     error_summary = ?
                   WHERE id = ?""",
                (
                    finished_iso,
                    attempted,
                    succeeded,
                    len(failed_stocks),
                    status,
                    ",".join(failed_stocks[:50]) if failed_stocks else None,
                    run_id,
                ),
            )

        logger.info(
            "Done: %d/%d succeeded, %d failed, coverage %.1f%%",
            succeeded, attempted, len(failed_stocks), coverage * 100,
        )
        if succeeded == 0:
            if attempted == 0 and existing_rows > 0:
                logger.info(
                    "Resume mode: no rows scraped this run because %d rows already existed for %s",
                    existing_rows, query_date,
                )
            else:
                logger.error("No valid HOLDINGS rows scraped for %s; skipping holdings.json export", query_date)
                return 1
        _export_json(query_date, len(alerts_found))
        if coverage < MIN_SUCCESS_COVERAGE:
            logger.error("Coverage %.1f%% < %.1f%%; returning partial failure", coverage * 100, MIN_SUCCESS_COVERAGE * 100)
            return 1
        _clear_cooldown()
        return 0

    except HKEXBlockedError as e:
        logger.error("HKEX block detected: %s", e)
        _mark_cooldown(str(e))
        finished_iso = datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute(
                """UPDATE scrape_runs SET
                     finished_at = ?, status = 'blocked', error_summary = ?
                   WHERE id = ?""",
                (finished_iso, str(e)[:500], run_id),
            )
        return 2

    except Exception as e:
        logger.exception("Fatal error in run_daily")
        finished_iso = datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute(
                """UPDATE scrape_runs SET
                     finished_at = ?, status = 'failed', error_summary = ?
                   WHERE id = ?""",
                (finished_iso, str(e)[:500], run_id),
            )
        send_admin_alert(f"❌ HOLDINGS daily run 失敗:\n{traceback.format_exc()[:1500]}")
        return 2


def _fetch_market_caps(codes: list[str], fetch_remote: bool = True) -> dict[str, float]:
    """Load market caps from cache.

    Daily refresh must not block on an external market-cap provider.
    The cache is refreshed out-of-band by Futu / Longbridge scripts.
    """
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_path = cache_dir / "market_caps.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}

    if not fetch_remote:
        logger.info("Market cap cache-only mode: using %d cached entries", len(cache))
    return {c: cache.get(c) for c in codes}


def _export_json(query_date: date, alerts_today: int) -> None:
    """Export all stocks + top movers to holdings.json in repo root for dashboard."""
    date_str = query_date.strftime("%Y-%m-%d")
    top_increase: list[dict] = []
    top_decrease: list[dict] = []

    try:
        with get_conn() as conn:
            # P3: Query from holdings_daily first (not holdings_trends) so stocks without trends still appear.
            # This matches the merge_shards.py update_holdings_json behavior.
            rows = conn.execute(
                """SELECT cd.stock_code, u.stock_name,
                          cd.total_pct, cd.top5_pct, cd.top10_pct, cd.num_participants,
                          cd.adj_hhi, cd.broker_top5_pct, cd.top_broker_id,
                          cd.top_broker_name, cd.top_broker_pct,
                          cd.futu_pct, cd.a00005_pct,
                          t.delta_5d_pct, t.delta_20d_pct, t.delta_60d_pct, t.delta_120d_pct,
                          t.consecutive_increase_days, t.consecutive_decrease_days
                   FROM holdings_daily cd
                   LEFT JOIN stock_universe u ON u.stock_code = cd.stock_code
                   LEFT JOIN holdings_trends t ON t.stock_code = cd.stock_code AND t.trade_date = cd.trade_date
                   WHERE cd.trade_date = ? AND cd.validation_failed = 0
                     AND cd.stock_code NOT LIKE '029%'
                     AND cd.stock_code NOT LIKE '04621'
                     AND cd.stock_code NOT LIKE '8%'
                   ORDER BY t.delta_5d_pct DESC""",
                (date_str,),
            ).fetchall()

        # Full stocks array for standalone page (short keys to minimise size)
        stocks: list[dict] = []
        for r in rows:
            # P3: Include Sentinel Option A concentration fields (matches merge_shards.py)
            sc = r["stock_code"]
            tp_val = round(r["total_pct"] or 0, 2)
            np_val = r["num_participants"] or 0
            t5_val = round(r["top5_pct"] or 0, 2)
            t10_val = round(r["top10_pct"] or 0, 2)

            stocks.append({
                "c": sc,
                "n": r["stock_name"] or sc,
                "tp": tp_val,
                "t5": t5_val,
                "t10": t10_val,
                "d5": round(r["delta_5d_pct"], 2) if r["delta_5d_pct"] is not None else None,
                "d20": round(r["delta_20d_pct"], 2) if r["delta_20d_pct"] is not None else None,
                "d60": round(r["delta_60d_pct"], 2) if r["delta_60d_pct"] is not None else None,
                "d120": round(r["delta_120d_pct"], 2) if r["delta_120d_pct"] is not None else None,
                "su": r["consecutive_increase_days"] or 0,
                "sd": r["consecutive_decrease_days"] or 0,
                "np": np_val,
                # Sentinel Option A (compact keys)
                "ah": round(r["adj_hhi"], 1) if r["adj_hhi"] is not None else None,
                "bt5": round(r["broker_top5_pct"], 2) if r["broker_top5_pct"] is not None else None,
                "tb": r["top_broker_id"] or "",
                "tbn": r["top_broker_name"] or "",
                "tbp": round(r["top_broker_pct"], 2) if r["top_broker_pct"] is not None else None,
                "fp": round(r["futu_pct"], 2) if r["futu_pct"] is not None else None,
                "a5": round(r["a00005_pct"], 2) if r["a00005_pct"] is not None else None,
            })
            # Backward compat top_increase/top_decrease
            entry = {
                "code": r["stock_code"],
                "name": r["stock_name"] or r["stock_code"],
                "delta_5d": round(r["delta_5d_pct"], 2) if r["delta_5d_pct"] is not None else 0,
                "delta_20d": round(r["delta_20d_pct"] or 0, 2) if r["delta_20d_pct"] is not None else 0,
                "delta_60d": round(r["delta_60d_pct"], 2) if r["delta_60d_pct"] is not None else 0,
                "delta_120d": round(r["delta_120d_pct"], 2) if r["delta_120d_pct"] is not None else 0,
                "total_pct": round(r["total_pct"] or 0, 2),
                "top5_pct": round(r["top5_pct"] or 0, 2),
                "top10_pct": round(r["top10_pct"] or 0, 2),
                "streak_up": r["consecutive_increase_days"] or 0,
                "streak_dn": r["consecutive_decrease_days"] or 0,
            }
            delta = r["delta_5d_pct"]
            if delta is not None and delta > 0:
                top_increase.append(entry)
            elif delta is not None and delta < 0:
                top_decrease.append(entry)
            # P1-3 fix: skip NULL and zero delta — don't pollute top_decrease

        # Enrich stocks with market cap from Yahoo Finance
        try:
            mc_map = _fetch_market_caps(
                [s["c"] for s in stocks],
                fetch_remote=not config["scraping"].get("skip_market_cap_fetch", False),
            )
            for s in stocks:
                s["mc"] = mc_map.get(s["c"])
        except Exception:
            pass  # non-fatal if market cap fetch fails

        top_increase = top_increase[:10]
        top_decrease = sorted(top_decrease, key=lambda x: x["delta_5d"])[:10]

        # Aggregate stats for the standalone page
        total_participants = sum(s["np"] for s in stocks) if stocks else 0
        with get_conn() as conn:
            min_date_row = conn.execute(
                "SELECT MIN(trade_date) AS md FROM holdings_daily"
            ).fetchone()
            first_date = min_date_row["md"] if min_date_row and min_date_row["md"] else date_str
            active_total_row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM stock_universe
                WHERE is_active=1
                  AND stock_code NOT LIKE '029%'
                  AND stock_code NOT LIKE '04621'
                  AND stock_code NOT LIKE '8%'
                """
            ).fetchone()
            active_total = active_total_row["n"] if active_total_row else 0
            date_count_row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM holdings_daily
                WHERE trade_date = ? AND validation_failed = 0
                  AND stock_code NOT LIKE '029%'
                  AND stock_code NOT LIKE '04621'
                  AND stock_code NOT LIKE '8%'
                """,
                (date_str,),
            ).fetchone()
            date_count = date_count_row["n"] if date_count_row else 0
            coverage_pct = round((date_count / active_total) * 100, 1) if active_total else None

        payload = {
            "updated": date_str,
            "first_date": first_date,
            "alerts_today": alerts_today,
            "stock_count": len(stocks),
            "total_participants": total_participants,
            "coverage": date_count,
            "coverage_total": active_total,
            "coverage_pct": coverage_pct,
            "is_complete": bool(active_total and date_count >= active_total),
            "stocks": stocks,
            "top_increase": top_increase,
            "top_decrease": top_decrease,
        }
        # Sanitize NaN/Infinity → null (invalid in JSON spec)
        import math as _math
        def _sanitize(obj):
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(v) for v in obj]
            if isinstance(obj, float) and (_math.isnan(obj) or _math.isinf(obj)):
                return None
            return obj
        payload = _sanitize(payload)
        out_path = Path(__file__).parent.parent.parent / "holdings.json"
        ccass_path = Path(__file__).parent.parent.parent / "ccass.json"
        # ✅ P1-6: atomic write via temp file
        tmp_path = out_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(out_path)
        legacy_payload = dict(payload)
        legacy_payload.setdefault("alerts_today", alerts_today)
        legacy_tmp = ccass_path.with_suffix(".tmp")
        legacy_tmp.write_text(json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8")
        legacy_tmp.replace(ccass_path)
        verified = json.loads(out_path.read_text(encoding="utf-8"))
        if verified.get("updated") != date_str:
            raise RuntimeError(f"holdings.json stale date: {verified.get('updated')} != {date_str}")
        if verified.get("stock_count") != len(stocks):
            raise RuntimeError(f"holdings.json stock_count mismatch: {verified.get('stock_count')} != {len(stocks)}")
        ccass_verified = json.loads(ccass_path.read_text(encoding="utf-8"))
        if ccass_verified.get("updated") != date_str:
            raise RuntimeError(f"ccass.json stale date: {ccass_verified.get('updated')} != {date_str}")
        if ccass_verified.get("stock_count") != len(stocks):
            raise RuntimeError(f"ccass.json stock_count mismatch: {ccass_verified.get('stock_count')} != {len(stocks)}")
        logger.info(
            "Exported holdings.json + ccass.json (%d stocks, %d up, %d down)",
            len(stocks), len(top_increase), len(top_decrease),
        )
        _post_movers_to_gas(top_increase, top_decrease, date_str)
        _stage_outputs(out_path)
    except Exception as e:
        logger.warning("holdings.json export failed: %s", e)


def _post_movers_to_gas(
    top_increase: list[dict],
    top_decrease: list[dict],
    date_str: str,
) -> None:
    import os, sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scanner"))
    from local_alert_store import store_alert
    created_at = date_str + "T17:00:00"

    def _post(entry: dict, signal: str) -> None:
        code = str(entry["code"]).zfill(5)
        pct5 = entry.get("delta_5d", 0)
        pct20 = entry.get("delta_20d", 0)
        body: dict = {
            "source":     "holdings",
            "category":   "tech",
            "code":       code,
            "name":       entry.get("name") or code,
            "signal":     signal,
            "created_at": created_at,
            "message":    f"5日持倉 {pct5:+.1f}%（20日 {pct20:+.1f}%）",
            "tags":       "HOLDINGS",
        }
        try:
            store_alert(body)
        except Exception as exc:
            logger.warning("store_alert failed %s: %s", code, exc)

    for e in top_increase:
        _post(e, "HOLDINGS增持")
    for e in top_decrease:
        _post(e, "HOLDINGS減持")
    logger.info("Stored %d HOLDINGS signals locally", len(top_increase) + len(top_decrease))


def _stage_outputs(json_path):
    """Compress holdings.db → holdings.db.gz + stage both files for git commit.

    IMPORTANT: This function does NOT commit or push. It only stages files.
    The workflow YAML's "Commit holdings.json" step handles the actual
    git commit + push. Having TWO places do git push causes a race
    condition where the Python push loses to the workflow step push,
    and holdings.db.gz gets dropped. One pusher = no race.
    """
    import subprocess, gzip, shutil
    repo_root = json_path.parent
    db_path = json_path.parent / "holdings" / "holdings.db"
    db_gz_path = json_path.parent / "holdings" / "holdings.db.gz"
    try:
        # Compress holdings.db
        if db_path.exists():
            with open(db_path, 'rb') as f_in:
                with gzip.open(db_gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logger.info("Compressed holdings.db: %d → %d bytes",
                        db_path.stat().st_size, db_gz_path.stat().st_size)

        # Stage BOTH JSON files. The workflow YAML step runs a git commit
        # from the repo root, so both outputs need to be staged here.
        subprocess.run(["git","add","holdings.json"], cwd=repo_root, capture_output=True)
        subprocess.run(["git","add","ccass.json"], cwd=repo_root, capture_output=True)
        if db_gz_path.exists():
            subprocess.run(["git","add","holdings/holdings.db.gz"], cwd=repo_root, capture_output=True)
        logger.info("Staged holdings.json + ccass.json + holdings.db.gz for workflow commit")
    except Exception as e:
        logger.warning("Stage outputs failed: %s", e)


def _detect_and_log_events(t_date: date, y_date: date) -> list[dict]:
    """Compare per-broker HOLDINGS holdings between T and T-1 for all stocks.

    Queries holdings_holdings in bulk, groups by stock in Python, runs
    detect_events(), logs new events to holdings_events, and returns
    the list of newly logged events (with DB ids) for alert dispatch.
    """
    t_str = t_date.strftime("%Y-%m-%d")
    y_str = y_date.strftime("%Y-%m-%d")

    # 1. Get total_shares for all stocks on T (for % calculation)
    with get_conn() as conn:
        shares_rows = conn.execute(
            "SELECT stock_code, total_shares FROM holdings_daily WHERE trade_date = ?",
            (t_str,),
        ).fetchall()
    shares_map = {r["stock_code"]: r["total_shares"] for r in shares_rows if r["total_shares"]}

    # 2. Get ALL holdings for T and T-1 (bulk fetch)
    with get_conn() as conn:
        t_rows = conn.execute(
            "SELECT stock_code, participant_id, shares FROM holdings_holdings WHERE trade_date = ?",
            (t_str,),
        ).fetchall()
        y_rows = conn.execute(
            "SELECT stock_code, participant_id, shares FROM holdings_holdings WHERE trade_date = ?",
            (y_str,),
        ).fetchall()

    # 3. Group by stock_code
    t_map: dict[str, dict[str, int]] = {}
    for r in t_rows:
        t_map.setdefault(r["stock_code"], {})[r["participant_id"]] = r["shares"]

    y_map: dict[str, dict[str, int]] = {}
    for r in y_rows:
        y_map.setdefault(r["stock_code"], {})[r["participant_id"]] = r["shares"]

    # Only process stocks that have data on BOTH days
    common_codes = set(t_map.keys()) & set(y_map.keys())

    new_events: list[dict] = []
    now_iso = datetime.utcnow().isoformat()

    for code in common_codes:
        issued = shares_map.get(code)
        if not issued or issued <= 0:
            continue

        events = detect_events(t_map[code], y_map[code], issued)
        if not events:
            continue

        for ev in events:
            broker_from = ev.get("from") if ev["type"] == "transfer" else None
            broker_to = ev.get("to") if ev["type"] == "transfer" else None

            with get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO holdings_events
                         (stock_code, trade_date, event_type, broker_from, broker_to,
                          pct, shares, detected_at, alerted)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (code, t_str, ev["type"], broker_from, broker_to,
                     ev["pct"], ev["shares"], now_iso),
                )
                ev_id = cur.lastrowid

            new_events.append({
                "id": ev_id,
                "stock_code": code,
                "trade_date": t_str,
                "event_type": ev["type"],
                "pct": ev["pct"],
                "shares": ev["shares"],
                "broker_from": broker_from,
                "broker_to": broker_to,
            })

    if new_events:
        logger.info(
            "Detected %d HOLDINGS events (deposit/transfer) across %d stocks",
            len(new_events), len(common_codes),
        )
    return new_events


def _write_shard_json(
    out_path: str,
    query_date: date,
    shard: int | None,
    shard_total: int | None,
    stocks_total: int,
    succeeded: int,
    failed_stocks: list[str],
    snapshots: list,
) -> None:
    """Write shard output JSON matching the format expected by backfill/merge."""
    import json as _json
    payload = {
        "shard": shard if shard is not None else 0,
        "shard_total": shard_total or 1,
        "query_date": query_date.strftime("%Y-%m-%d"),
        "target_date": query_date.strftime("%Y-%m-%d"),
        "stocks_total": stocks_total,
        "stocks_in_shard": stocks_total,
        "succeeded": succeeded,
        "failed": len(failed_stocks),
        "failed_stocks": failed_stocks,
        "snapshots": [
            {
                "stock_code": s.stock_code,
                "trade_date": s.trade_date,
                "total_shares": s.total_shares,
                "total_pct": s.total_pct,
                "num_participants": s.num_participants,
                "holdings": s.holdings if hasattr(s, 'holdings') else [],
            }
            for s in snapshots
        ],
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_shard_output(
    out_path: str,
    query_date: date,
    shard: int | None,
    shard_total: int | None,
    stocks_total: int,
    succeeded: int,
    failed_stocks: list[str],
    snapshots: list[dict],
) -> None:
    """Write shard artifact JSON from pre-built dicts (subprocess scrape results).

    Accepts plain dicts (not HOLDINGSSnapshot objects) so it can be called
    directly from the sequential subprocess scrape loop in run_daily.
    """
    payload = {
        "shard": shard if shard is not None else 0,
        "shard_total": shard_total or 1,
        "query_date": query_date.strftime("%Y-%m-%d"),
        "target_date": query_date.strftime("%Y-%m-%d"),
        "stocks_total": stocks_total,
        "stocks_in_shard": stocks_total,
        "succeeded": succeeded,
        "failed": len(failed_stocks),
        "failed_stocks": failed_stocks,
        "snapshots": snapshots,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today HK)")
    parser.add_argument("--skip-scrape", action="store_true")
    parser.add_argument("--skip-alerts", action="store_true")
    parser.add_argument("--refresh-universe", action="store_true")
    parser.add_argument("--shard", type=int, help="Shard index (0-based)")
    parser.add_argument("--shard-total", type=int, help="Total number of shards")
    parser.add_argument("--query-date", help="HOLDINGS query date YYYY-MM-DD (overrides auto)")
    parser.add_argument("--out", help="Output JSON path for shard results")
    args = parser.parse_args()

    target = None
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()

    query_date_override = None
    if hasattr(args, 'query_date') and args.query_date:
        query_date_override = datetime.strptime(args.query_date, "%Y-%m-%d").date()

    rc = run_daily(
        target_date=target,
        skip_scrape=args.skip_scrape,
        skip_alerts=args.skip_alerts,
        force_universe_refresh=args.refresh_universe,
        shard=getattr(args, 'shard', None),
        shard_total=getattr(args, 'shard_total', None),
        query_date_override=query_date_override,
        out_path=getattr(args, 'out', None),
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
