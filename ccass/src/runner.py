"""Main daily runner — sharded version.

Workflow:
  SHARD MODE (--shard N --shard-total M):
    1. Refresh universe
    2. Scrape subset (stocks[N::M])
    3. Serialise snapshots → ccass-shard-N.json
    ── NO trends, NO alerts, NO events, NO export ──

  MERGE MODE (--merge):
    1. Restore ccass.db from ccass.db.gz (historical data)
    2. Read all ccass-shard-*.json, replay snapshots → DB
    3. Trends → Alerts → Events → Export → Stage

  SINGLE MODE (no --shard, no --merge): original behaviour, unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path

import yaml

from src.db import init_db, get_conn
from src.logger import setup_logger, disable_file_handler
from src.trading_calendar import today_hk, is_trading_day, previous_trading_day
from src.universe import refresh_universe, get_active_stocks
from src.scraper import CCASSScraper, save_snapshot, CCASSSnapshot
from src.trend import compute_trends_for_date
from src.alerts import detect_alerts, send_alerts, send_admin_alert, send_event_alerts

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scanner.events_detector import detect_events  # type: ignore[import-unused]

logger = setup_logger("runner")
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
SHARD_GLOB = "ccass-shard-*.json"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def should_refresh_universe(force: bool = False) -> bool:
    if force:
        return True
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM stock_universe WHERE is_active = 1"
        ).fetchone()
        if row["n"] < 2500:
            return True
    return today_hk().weekday() == 0


# ═══════════════════════════════════════════════════════════════════════════
#  SHARD MODE
# ═══════════════════════════════════════════════════════════════════════════

def run_shard(shard_idx: int, shard_total: int, force_universe_refresh: bool = False,
              query_date: date | None = None, out_path: Path | None = None) -> int:
    """Scrape one shard, write JSON. No trends/alerts/events/export.

    If query_date is provided, scrape that exact date (backfill mode).
    Otherwise scrape previous_trading_day of today (normal shard mode).

    If out_path is provided, write JSON there. Otherwise write to
    ccass-shard-N.json at project root.
    """
    init_db()
    config = load_config()

    if query_date is not None:
        # Backfill mode: scrape the exact requested date
        target_date = query_date
        # Don't check is_trading_day — caller validated the date
        # Don't refresh universe — caller manages that
    else:
        target_date = today_hk()
        if not is_trading_day(target_date):
            logger.info("%s is not a trading day, skip shard %d", target_date, shard_idx)
            return 0
        query_date = previous_trading_day(target_date)

    logger.info("SHARD %d/%d — query_date=%s", shard_idx + 1, shard_total, query_date)

    if not query_date and should_refresh_universe(force_universe_refresh):
        try:
            refresh_universe()
        except Exception as e:
            logger.error("Universe refresh failed: %s", e)
            send_admin_alert(f"Universe refresh failed in shard {shard_idx}: {e}")

    stocks = get_active_stocks()
    logger.info("Universe: %d active stocks", len(stocks))

    my_stocks = stocks[shard_idx::shard_total]
    logger.info("Shard %d: %d stocks assigned", shard_idx, len(my_stocks))

    if not my_stocks:
        logger.warning("Shard %d: zero stocks — writing empty JSON and exiting", shard_idx)
        _write_shard_json(shard_idx, shard_total, query_date, target_date,
                          len(stocks), 0, 0, [], [], out_path=out_path)
        return 0

    sc_cfg = config["scraping"]
    scraper = CCASSScraper(
        user_agent=sc_cfg["user_agent"],
        delay_min=sc_cfg["delay_min_seconds"],
        delay_max=sc_cfg["delay_max_seconds"],
        timeout=sc_cfg["timeout_seconds"],
        max_retries=sc_cfg["max_retries"],
    )

    try:
        snapshots: list[dict] = []
        succeeded = 0
        failed_stocks: list[str] = []

        # Internal deadline: abort if shard takes too long (HKEX block detection)
        deadline = time.monotonic() + 9000  # 150 minutes
        deadline_exceeded = False

        for i, code in enumerate(my_stocks, 1):
            if time.monotonic() > deadline:
                logger.error("Shard %d internal deadline exceeded at %d/%d",
                             shard_idx, i - 1, len(my_stocks))
                failed_stocks.extend(my_stocks[i - 1:])
                deadline_exceeded = True
                break
            if i % 50 == 0:
                logger.info("Shard %d progress: %d/%d (%.1f%%)",
                            shard_idx, i, len(my_stocks), 100 * i / len(my_stocks))
            try:
                snap = scraper.scrape_stock(code, query_date)
                if snap:
                    snapshots.append(_snapshot_to_dict(snap))
                    succeeded += 1
                else:
                    failed_stocks.append(code)
            except RuntimeError as e:
                logger.error("Shard %d aborting on runtime error from %s: %s",
                             shard_idx, code, e)
                failed_stocks.append(code)
                _write_shard_json(shard_idx, shard_total, query_date, target_date,
                                  len(stocks), len(my_stocks), succeeded, failed_stocks, snapshots,
                                  out_path=out_path)
                return 2
            except Exception:
                logger.exception("Unexpected error on %s", code)
                failed_stocks.append(code)

        logger.info("Shard %d done: %d/%d succeeded, %d failed",
                    shard_idx, succeeded, len(my_stocks), len(failed_stocks))

        _write_shard_json(shard_idx, shard_total, query_date, target_date,
                          len(stocks), len(my_stocks), succeeded, failed_stocks, snapshots,
                          out_path=out_path)

        if deadline_exceeded:
            return 3  # internal shard timeout (NOT HKEX block!)

        return 0  # partial failures are normal; merge job will still run
    finally:
        scraper.close()


def _snapshot_to_dict(snap: CCASSSnapshot) -> dict:
    return {
        "stock_code": snap.stock_code,
        "trade_date": snap.trade_date,
        "total_shares": snap.total_shares,
        "total_pct": snap.total_pct,
        "num_participants": snap.num_participants,
        "holdings": snap.holdings,
    }


def _dict_to_snapshot(d: dict) -> CCASSSnapshot:
    return CCASSSnapshot(
        stock_code=d["stock_code"],
        trade_date=d["trade_date"],
        total_shares=d["total_shares"],
        total_pct=d["total_pct"],
        num_participants=d["num_participants"],
        holdings=d["holdings"],
    )


def _write_shard_json(shard_idx, shard_total, query_date, target_date,
                      total_stocks, shard_stocks, succeeded, failed_stocks, snapshots,
                      out_path: Path | None = None):
    payload = {
        "shard": shard_idx,
        "shard_total": shard_total,
        "query_date": query_date.strftime("%Y-%m-%d"),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "stocks_total": total_stocks,
        "stocks_in_shard": shard_stocks,
        "succeeded": succeeded,
        "failed": len(failed_stocks),
        "failed_stocks": failed_stocks,
        "snapshots": snapshots,
    }
    if out_path is None:
        out_path = _PROJECT_ROOT / f"ccass-shard-{shard_idx}.json"
    # Atomic write: tmp → rename
    tmp_path = Path(str(out_path) + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.rename(out_path)
    logger.info("Wrote %d snapshots → %s (%.1f KB)",
                len(snapshots), out_path.name, out_path.stat().st_size / 1024)


# ═══════════════════════════════════════════════════════════════════════════
#  MERGE MODE
# ═══════════════════════════════════════════════════════════════════════════

def run_merge() -> int:
    """Collect all ccass-shard-*.json, replay into DB, then full pipeline."""
    _restore_db()
    init_db()
    config = load_config()
    target_date = today_hk()

    if not is_trading_day(target_date):
        logger.info("%s is not a trading day, skip merge", target_date)
        return 0

    query_date = previous_trading_day(target_date)
    logger.info("MERGE mode — query_date=%s", query_date)

    shard_files = sorted(_PROJECT_ROOT.glob(SHARD_GLOB))
    if not shard_files:
        logger.error("No ccass-shard-*.json files found — nothing to merge")
        return 2

    total_snapshots = 0
    total_failed = 0
    for sf in shard_files:
        logger.info("Reading %s (%.1f KB)", sf.name, sf.stat().st_size / 1024)
        data = json.loads(sf.read_text())
        for snap_dict in data["snapshots"]:
            try:
                save_snapshot(_dict_to_snapshot(snap_dict))
                total_snapshots += 1
            except Exception:
                logger.warning("save_snapshot failed for %s", snap_dict.get("stock_code", "??"))
                total_failed += 1
        logger.info("  → %d snapshots replayed", len(data["snapshots"]))

    logger.info("Replay done: %d ok, %d failed", total_snapshots, total_failed)
    if total_snapshots == 0:
        logger.error("Zero snapshots replayed — aborting")
        return 2

    # ── Post-scrape pipeline ──

    try:
        compute_trends_for_date(query_date, config["trend_windows"])
    except Exception as e:
        logger.exception("Trend computation failed")
        send_admin_alert(f"Trend computation 失敗: {e}")

    alert_cfg = config["alerts"]
    alerts_found = detect_alerts(
        query_date,
        spike_threshold_pct=alert_cfg["spike_threshold_pct"],
        consecutive_days=alert_cfg["consecutive_days"],
        consecutive_min_daily_pct=alert_cfg["consecutive_min_daily_pct"],
    )
    sent = send_alerts(
        alerts_found, query_date,
        throttle_seconds=alert_cfg["telegram_throttle_seconds"],
        max_per_batch=alert_cfg["max_alerts_per_batch"],
        summary_only_threshold=alert_cfg["summary_only_threshold"],
    )
    logger.info("Sent %d alert(s)", sent)

    try:
        yesterday_date = previous_trading_day(query_date)
        events_logged = _detect_and_log_events(query_date, yesterday_date)
        if events_logged:
            logger.info("Logged %d CCASS events", len(events_logged))
            ev_sent = send_event_alerts(events_logged, query_date)
            logger.info("Sent %d event alert(s)", ev_sent)
    except Exception as e:
        logger.exception("Event detection failed")
        send_admin_alert(f"Event detection 失敗: {e}")

    _export_json(query_date, len(alerts_found))
    logger.info("Merge complete: %d snapshots, %d alerts", total_snapshots, sent)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
#  SINGLE MODE (original, unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def _scrape_parallel(stocks, query_date, sc_cfg, n_workers):
    total = len(stocks)
    attempted = 0
    succeeded = 0
    failed_stocks: list[str] = []
    lock = __import__("threading").Lock()
    progress_lock = __import__("threading").Lock()
    done_count = 0

    scrapers = [
        CCASSScraper(
            user_agent=sc_cfg["user_agent"],
            delay_min=sc_cfg["delay_min_seconds"],
            delay_max=sc_cfg["delay_max_seconds"],
            timeout=sc_cfg["timeout_seconds"],
            max_retries=sc_cfg["max_retries"],
        )
        for _ in range(n_workers)
    ]

    def _scrape_one(code):
        worker_idx = hash(code) % n_workers
        scraper = scrapers[worker_idx]
        snap = scraper.scrape_stock(code, query_date)
        if snap:
            save_snapshot(snap)
            return (code, True)
        return (code, False)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        fut_map = {pool.submit(_scrape_one, code): code for code in stocks}
        for fut in as_completed(fut_map):
            code = fut_map[fut]
            attempted += 1
            try:
                _, ok = fut.result()
                if ok:
                    succeeded += 1
                else:
                    with lock:
                        failed_stocks.append(code)
            except Exception as e:
                logger.warning("Parallel scrape %s failed: %s", code, e)
                with lock:
                    failed_stocks.append(code)
            with progress_lock:
                done_count += 1
                if done_count % 100 == 0 or done_count == total:
                    logger.info("Progress: %d/%d (%.1f%%)", done_count, total, 100*done_count/total)

    logger.info("Parallel scrape done: %d/%d succeeded, %d failed",
                succeeded, attempted, len(failed_stocks))
    return (attempted, succeeded, failed_stocks)

def _restore_db():
    """Restore ccass.db from ccass.db.gz if DB missing, empty, or corrupt."""
    import gzip, shutil
    db_path = Path(__file__).parent.parent / "ccass.db"
    db_gz_path = Path(__file__).parent.parent / "ccass.db.gz"
    if not db_gz_path.exists():
        return  # Nothing to restore from
    # Force restore if DB missing, empty, or only contains partial data
    should_restore = False
    if not db_path.exists() or db_path.stat().st_size == 0:
        should_restore = True
    else:
        # Heuristic: if DB has fewer than 100 ccass_daily rows, treat as partial
        try:
            import sqlite3
            tmp_conn = sqlite3.connect(str(db_path))
            row = tmp_conn.execute("SELECT COUNT(*) FROM ccass_daily").fetchone()
            tmp_conn.close()
            if row and row[0] < 100:
                should_restore = True
        except Exception:
            should_restore = True  # corrupt DB
    if should_restore:
        logger.info("Restoring ccass.db from ccass.db.gz (%d bytes)", db_gz_path.stat().st_size)
        with gzip.open(db_gz_path, 'rb') as f_in:
            with open(db_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        logger.info("Restored ccass.db: %d bytes", db_path.stat().st_size)


def run_daily(
    target_date: date | None = None,
    skip_scrape: bool = False,
    skip_alerts: bool = False,
    force_universe_refresh: bool = False,
) -> int:
    _restore_db()
    init_db()
    config = load_config()
    target_date = target_date or today_hk()

    logger.info("=" * 60)
    logger.info("CCASS daily run for %s", target_date)
    logger.info("=" * 60)

    if not is_trading_day(target_date):
        logger.info("%s is not a trading day, skip", target_date)
        return 0

    query_date = previous_trading_day(target_date)
    logger.info("Querying CCASS data for %s", query_date)

    now_iso = datetime.now(tz=__import__("pytz").timezone("Asia/Hong_Kong")).isoformat()
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
        if should_refresh_universe(force_universe_refresh):
            try:
                refresh_universe()
            except Exception as e:
                logger.error("Universe refresh failed: %s", e)
                send_admin_alert(f"Universe refresh 失敗: {e}")

        stocks = get_active_stocks()
        logger.info("Universe: %d active stocks", len(stocks))

        max_stocks = config["scraping"].get("max_stocks")
        if max_stocks and len(stocks) > max_stocks:
            logger.info("Limiting scrape to top %d stocks", max_stocks)
            stocks = stocks[:max_stocks]

        if not stocks:
            raise RuntimeError("Empty universe — cannot proceed")

        if not skip_scrape:
            sc_cfg = config["scraping"]
            n_workers = sc_cfg.get("parallel_workers", 1)
            if n_workers > 1 and len(stocks) > 100:
                attempted, succeeded, failed_stocks = _scrape_parallel(
                    stocks, query_date, sc_cfg, n_workers)
            else:
                scraper = CCASSScraper(
                    user_agent=sc_cfg["user_agent"],
                    delay_min=sc_cfg["delay_min_seconds"],
                    delay_max=sc_cfg["delay_max_seconds"],
                    timeout=sc_cfg["timeout_seconds"],
                    max_retries=sc_cfg["max_retries"],
                )
                for i, code in enumerate(stocks, 1):
                    attempted += 1
                    if i % 50 == 0:
                        logger.info("Progress: %d/%d (%.1f%%)", i, len(stocks), 100*i/len(stocks))
                    try:
                        snap = scraper.scrape_stock(code, query_date)
                        if snap:
                            save_snapshot(snap)
                            succeeded += 1
                        else:
                            failed_stocks.append(code)
                    except Exception as e:
                        logger.exception("Unexpected error on %s", code)
                        failed_stocks.append(code)

        try:
            compute_trends_for_date(query_date, config["trend_windows"])
        except Exception as e:
            logger.exception("Trend computation failed")
            send_admin_alert(f"Trend computation 失敗: {e}")

        if not skip_alerts:
            alert_cfg = config["alerts"]
            alerts_found = detect_alerts(
                query_date,
                spike_threshold_pct=alert_cfg["spike_threshold_pct"],
                consecutive_days=alert_cfg["consecutive_days"],
                consecutive_min_daily_pct=alert_cfg["consecutive_min_daily_pct"],
            )
            sent = send_alerts(
                alerts_found, query_date,
                throttle_seconds=alert_cfg["telegram_throttle_seconds"],
                max_per_batch=alert_cfg["max_alerts_per_batch"],
                summary_only_threshold=alert_cfg["summary_only_threshold"],
            )
            logger.info("Sent %d alert(s)", sent)

        try:
            yesterday_date = previous_trading_day(query_date)
            events_logged = _detect_and_log_events(query_date, yesterday_date)
            if events_logged:
                logger.info("Logged %d CCASS events", len(events_logged))
                if not skip_alerts:
                    ev_sent = send_event_alerts(events_logged, query_date)
                    logger.info("Sent %d event alert(s)", ev_sent)
            else:
                logger.info("No CCASS events detected")
        except Exception as e:
            logger.exception("Event detection failed")
            send_admin_alert(f"Event detection 失敗: {e}")

        fail_rate = len(failed_stocks) / max(attempted, 1)
        if fail_rate > 0.05:
            send_admin_alert(
                f"⚠️ Scrape fail rate {fail_rate*100:.1f}% "
                f"({len(failed_stocks)}/{attempted})\n"
                f"Sample failed: {failed_stocks[:10]}"
            )

        status = "success" if not failed_stocks else "partial"
        finished_iso = datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute(
                """UPDATE scrape_runs SET
                     finished_at = ?, stocks_attempted = ?,
                     stocks_succeeded = ?, stocks_failed = ?,
                     status = ?, error_summary = ?
                   WHERE id = ?""",
                (finished_iso, attempted, succeeded, len(failed_stocks),
                 status, ",".join(failed_stocks[:50]) if failed_stocks else None, run_id),
            )

        logger.info("Done: %d/%d succeeded, %d failed", succeeded, attempted, len(failed_stocks))
        _export_json(query_date, len(alerts_found))
        return 0

    except Exception as e:
        logger.exception("Fatal error in run_daily")
        finished_iso = datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute(
                """UPDATE scrape_runs SET finished_at = ?, status = 'failed', error_summary = ?
                   WHERE id = ?""",
                (finished_iso, str(e)[:500], run_id),
            )
        send_admin_alert(f"❌ CCASS daily run 失敗:\n{traceback.format_exc()[:1500]}")
        return 2


# ═══════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _fetch_market_caps(codes):
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_path = cache_dir / "market_caps.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}
    uncached = [c for c in codes if c not in cache]
    if uncached:
        import logging as _logging
        _logging.getLogger("yfinance").setLevel(_logging.CRITICAL)
        import yfinance as yf
        def _sym(c):
            return f"{c.lstrip('0').zfill(4)}.HK"
        def _one(c):
            try:
                t = yf.Ticker(_sym(c))
                info = t.info if hasattr(t, 'info') else {}
                mc = info.get("marketCap") if isinstance(info, dict) else None
                if mc is not None:
                    return c, round(float(mc)/1e8, 2)
            except Exception:
                pass
            return c, None
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_one, c): c for c in uncached}
            for fut in as_completed(futures):
                c, mc = fut.result()
                cache[c] = mc
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    return cache


def _export_json(query_date, alerts_today):
    date_str = query_date.strftime("%Y-%m-%d")
    top_increase = []
    top_decrease = []
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT t.stock_code, u.stock_name, t.delta_5d_pct, t.delta_20d_pct,
                          t.delta_60d_pct, t.delta_120d_pct,
                          d.total_pct, d.top5_pct, d.top10_pct, d.num_participants,
                          t.consecutive_increase_days, t.consecutive_decrease_days
                   FROM ccass_daily d
                   LEFT JOIN stock_universe u ON u.stock_code = d.stock_code
                   LEFT JOIN ccass_trends t ON t.stock_code = d.stock_code AND t.trade_date = d.trade_date
                   WHERE d.trade_date = ? AND d.validation_failed = 0
                   ORDER BY t.delta_5d_pct DESC""",
                (date_str,),
            ).fetchall()

        stocks = []
        for r in rows:
            stocks.append({
                "c": r["stock_code"], "n": r["stock_name"] or r["stock_code"],
                "tp": round(r["total_pct"] or 0, 2),
                "t5": round(r["top5_pct"] or 0, 2),
                "t10": round(r["top10_pct"] or 0, 2),
                "d5": round(r["delta_5d_pct"], 2) if r["delta_5d_pct"] is not None else None,
                "d20": round(r["delta_20d_pct"] or 0, 2) if r["delta_20d_pct"] is not None else None,
                "d60": round(r["delta_60d_pct"], 2) if r["delta_60d_pct"] is not None else None,
                "d120": round(r["delta_120d_pct"], 2) if r["delta_120d_pct"] is not None else None,
                "su": r["consecutive_increase_days"] or 0,
                "sd": r["consecutive_decrease_days"] or 0,
                "np": r["num_participants"] or 0,
            })
            entry = {
                "code": r["stock_code"], "name": r["stock_name"] or r["stock_code"],
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
            else:
                top_decrease.append(entry)

        try:
            mc_map = _fetch_market_caps([s["c"] for s in stocks])
            for s in stocks:
                s["mc"] = mc_map.get(s["c"])
        except Exception:
            pass

        top_increase = top_increase[:10]
        top_decrease = sorted(top_decrease, key=lambda x: x["delta_5d"])[:10]
        total_participants = sum(s["np"] for s in stocks) if stocks else 0
        with get_conn() as conn:
            min_date_row = conn.execute("SELECT MIN(trade_date) AS md FROM ccass_daily").fetchone()
            first_date = min_date_row["md"] if min_date_row and min_date_row["md"] else date_str

        payload = {
            "updated": date_str, "first_date": first_date,
            "alerts_today": alerts_today, "total_stocks": len(stocks),
            "total_participants": total_participants,
            "stocks": stocks, "top_increase": top_increase, "top_decrease": top_decrease,
        }
        out_path = _PROJECT_ROOT / "ccass.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        logger.info("Exported ccass.json (%d stocks)", len(stocks))
        _post_movers_to_gas(top_increase, top_decrease, date_str)
        _stage_outputs(out_path)
    except Exception as e:
        logger.exception("ccass.json export failed")
        raise


def _post_movers_to_gas(top_increase, top_decrease, date_str):
    import os, requests as _req
    url = os.getenv("GAS_WEBHOOK_URL", "")
    secret = os.getenv("GAS_SECRET", "")
    if not url:
        return
    created_at = date_str + "T17:00:00"
    def _post(entry, signal):
        code = str(entry["code"]).zfill(5)
        body = {
            "source": "ccass", "category": "tech", "code": code,
            "name": entry.get("name") or code, "signal": signal,
            "created_at": created_at,
            "message": f"5日持倉 {entry.get('delta_5d',0):+.1f}%（20日 {entry.get('delta_20d',0):+.1f}%）",
            "tags": "CCASS",
        }
        if secret:
            body["secret"] = secret
        try:
            _req.post(url, json=body, timeout=30)
        except Exception:
            pass
    for e in top_increase:
        _post(e, "CCASS增持")
    for e in top_decrease:
        _post(e, "CCASS減持")


def _detect_and_log_events(t_date, y_date):
    t_str = t_date.strftime("%Y-%m-%d")
    y_str = y_date.strftime("%Y-%m-%d")
    with get_conn() as conn:
        shares_rows = conn.execute(
            "SELECT stock_code, total_shares FROM ccass_daily WHERE trade_date = ?", (t_str,)
        ).fetchall()
    shares_map = {r["stock_code"]: r["total_shares"] for r in shares_rows if r["total_shares"]}
    with get_conn() as conn:
        t_rows = conn.execute(
            "SELECT stock_code, participant_id, shares FROM ccass_holdings WHERE trade_date = ?", (t_str,)
        ).fetchall()
        y_rows = conn.execute(
            "SELECT stock_code, participant_id, shares FROM ccass_holdings WHERE trade_date = ?", (y_str,)
        ).fetchall()
    t_map = {}
    for r in t_rows:
        t_map.setdefault(r["stock_code"], {})[r["participant_id"]] = r["shares"]
    y_map = {}
    for r in y_rows:
        y_map.setdefault(r["stock_code"], {})[r["participant_id"]] = r["shares"]
    common_codes = set(t_map) & set(y_map)
    now_iso = datetime.utcnow().isoformat()
    new_events = []
    for code in common_codes:
        issued = shares_map.get(code)
        if not issued or issued <= 0:
            continue
        events = detect_events(t_map[code], y_map[code], issued)
        if not events:
            continue
        for ev in events:
            bf = ev.get("from") if ev["type"] == "transfer" else None
            bt = ev.get("to") if ev["type"] == "transfer" else None
            with get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO ccass_events (stock_code, trade_date, event_type, broker_from,
                         broker_to, pct, shares, detected_at, alerted)
                       VALUES (?,?,?,?,?,?,?,?,0)""",
                    (code, t_str, ev["type"], bf, bt, ev["pct"], ev["shares"], now_iso),
                )
                ev_id = cur.lastrowid
            new_events.append({
                "id": ev_id, "stock_code": code, "trade_date": t_str,
                "event_type": ev["type"], "pct": ev["pct"], "shares": ev["shares"],
                "broker_from": bf, "broker_to": bt,
            })
    if new_events:
        logger.info("Detected %d CCASS events across %d stocks", len(new_events), len(common_codes))
    return new_events


def _stage_outputs(json_path):
    import subprocess, gzip, shutil
    repo_root = json_path.parent
    db_path = json_path.parent / "ccass" / "ccass.db"
    db_gz_path = json_path.parent / "ccass" / "ccass.db.gz"
    try:
        if db_path.exists():
            with open(db_path, 'rb') as f_in:
                with gzip.open(db_gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logger.info("Compressed ccass.db: %d → %d bytes", db_path.stat().st_size, db_gz_path.stat().st_size)
        subprocess.run(["git", "add", "ccass.json"], cwd=repo_root, capture_output=True)
        if db_gz_path.exists():
            subprocess.run(["git", "add", "ccass/ccass.db.gz"], cwd=repo_root, capture_output=True)
        logger.info("Staged ccass.json + ccass.db.gz for workflow commit")
    except Exception as e:
        logger.warning("Stage outputs failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--skip-scrape", action="store_true")
    parser.add_argument("--skip-alerts", action="store_true")
    parser.add_argument("--refresh-universe", action="store_true")
    parser.add_argument("--shard", type=int, help="Shard index (0-based)")
    parser.add_argument("--shard-total", type=int, default=6)
    parser.add_argument("--query-date", help="Specific date YYYY-MM-DD (backfill mode)")
    parser.add_argument("--out", help="Output JSON path (backfill mode)")
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()

    # ── Shard mode ──
    if args.shard is not None:
        # Disable shared file logging to avoid midnight-rotation
        # race conditions on Windows (PermissionError on os.rename)
        disable_file_handler("runner")
        disable_file_handler("scraper")
        disable_file_handler("universe")
        qdate = None
        out = None
        if args.query_date:
            qdate = datetime.strptime(args.query_date, "%Y-%m-%d").date()
        if args.out:
            out = Path(args.out)
        rc = run_shard(args.shard, args.shard_total, args.refresh_universe,
                       query_date=qdate, out_path=out)
        sys.exit(rc)

    # ── Merge mode ──
    if args.merge:
        rc = run_merge()
        sys.exit(rc)

    # ── Single mode (backward compatible) ──
    target = None
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    rc = run_daily(
        target_date=target,
        skip_scrape=args.skip_scrape,
        skip_alerts=args.skip_alerts,
        force_universe_refresh=args.refresh_universe,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
