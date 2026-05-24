"""Main daily runner.

Workflow:
1. Check 今日係咪 trading day。如果唔係，exit。
2. 攞 universe (refresh weekly)
3. Scrape 全部股票
4. Compute trends
5. Detect alerts → Telegram
6. Detect CCASS events (deposit/transfer) → Telegram
7. Log run metadata
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
from src.logger import setup_logger
from src.trading_calendar import today_hk, is_trading_day, previous_trading_day
from src.universe import refresh_universe, get_active_stocks
from src.scraper import CCASSScraper, save_snapshot
from src.trend import compute_trends_for_date
from src.alerts import detect_alerts, send_alerts, send_admin_alert, send_event_alerts

# scanner/events_detector.py lives at project root (not inside ccass/),
# so add project root to path for the import
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scanner.events_detector import detect_events  # type: ignore[import-unused]

logger = setup_logger("runner")
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def _scrape_parallel(
    stocks: list[str],
    query_date: date,
    sc_cfg: dict,
    n_workers: int,
) -> tuple[int, int, list[str]]:
    """Scrape stocks with N parallel workers (each worker = own cloudscraper session)."""
    total = len(stocks)
    attempted = 0
    succeeded = 0
    failed_stocks: list[str] = []
    lock = __import__("threading").Lock()
    progress_lock = __import__("threading").Lock()
    done_count = 0

    # Create one scraper per worker (each has its own cloudscraper session)
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

    def _scrape_one(code: str) -> tuple[str, bool]:
        """Scrape single stock, return (code, success)."""
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

            # Progress logging (thread-safe)
            with progress_lock:
                done_count += 1
                if done_count % 100 == 0 or done_count == total:
                    pct = 100.0 * done_count / total
                    logger.info("Progress: %d/%d (%.1f%%)", done_count, total, pct)

    logger.info(
        "Parallel scrape done: %d/%d succeeded, %d failed",
        succeeded, attempted, len(failed_stocks),
    )
    return (attempted, succeeded, failed_stocks)


def _restore_db():
    """Restore ccass.db from ccass.db.gz if DB missing or empty (first run / fresh checkout)."""
    import gzip, shutil
    db_path = Path(__file__).parent.parent / "ccass.db"
    db_gz_path = Path(__file__).parent.parent / "ccass.db.gz"
    if db_path.exists() and db_path.stat().st_size > 0:
        return  # Already have a valid DB
    if db_gz_path.exists():
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
    """
    Run 一個 cycle。
    Returns: 0 = success, 1 = partial, 2 = failed
    """
    init_db()
    _restore_db()  # Decompress ccass.db.gz if DB is empty (fresh checkout)
    config = load_config()
    target_date = target_date or today_hk()

    logger.info("=" * 60)
    logger.info("CCASS daily run for %s", target_date)
    logger.info("=" * 60)

    if not is_trading_day(target_date):
        logger.info("%s is not a trading day, skip", target_date)
        return 0

    # CCASS 通常公布前一個 trading day 嘅 data
    # 所以 query_date = 對上一次 trading day
    query_date = previous_trading_day(target_date)
    logger.info("Querying CCASS data for %s", query_date)

    # 1. Start run log
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
        # 2. Universe
        if should_refresh_universe(force_universe_refresh):
            try:
                refresh_universe()
            except Exception as e:
                logger.error("Universe refresh failed: %s", e)
                send_admin_alert(f"Universe refresh 失敗: {e}")

        stocks = get_active_stocks()
        logger.info("Universe: %d active stocks", len(stocks))

        # Optional: limit to top-N stocks for speed (config max_stocks)
        max_stocks = config["scraping"].get("max_stocks")
        if max_stocks and len(stocks) > max_stocks:
            logger.info("Limiting scrape to top %d stocks (config max_stocks)", max_stocks)
            stocks = stocks[:max_stocks]

        if not stocks:
            raise RuntimeError("Empty universe — cannot proceed")

        # 3. Scrape
        if not skip_scrape:
            sc_cfg = config["scraping"]
            n_workers = sc_cfg.get("parallel_workers", 1)

            if n_workers > 1 and len(stocks) > 100:
                attempted, succeeded, failed_stocks = _scrape_parallel(
                    stocks, query_date, sc_cfg, n_workers,
                )
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
                        logger.info("Progress: %d/%d (%.1f%%)", i, len(stocks), 100 * i / len(stocks))
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

        # 4. Trends
        try:
            compute_trends_for_date(query_date, config["trend_windows"])
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

        # 5.5. CCASS Events (Deposit / Transfer)
        try:
            yesterday_date = previous_trading_day(query_date)
            events_logged = _detect_and_log_events(query_date, yesterday_date)
            if events_logged:
                logger.info("Logged %d CCASS events (deposit/transfer)", len(events_logged))
                if not skip_alerts:
                    ev_sent = send_event_alerts(events_logged, query_date)
                    logger.info("Sent %d event alert(s)", ev_sent)
            else:
                logger.info("No CCASS events detected")
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

        status = "success" if not failed_stocks else "partial"
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

        logger.info("Done: %d/%d succeeded, %d failed", succeeded, attempted, len(failed_stocks))
        _export_json(query_date, len(alerts_found))
        return 0  # partial failures are normal; only fatal exceptions return non-zero

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
        send_admin_alert(f"❌ CCASS daily run 失敗:\n{traceback.format_exc()[:1500]}")
        return 2


def _fetch_market_caps(codes: list[str]) -> dict[str, float]:
    """Fetch market caps for HK stock codes via yfinance with caching.

    Uses ThreadPoolExecutor for parallel fetches. Results (including None
    for failed lookups) are cached in ccass/cache/market_caps.json to
    minimise re-fetches on subsequent runs.
    """
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_path = cache_dir / "market_caps.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}

    # Only fetch codes not yet in cache (including those cached as null)
    uncached = [c for c in codes if c not in cache]
    if uncached:
        import logging as _logging
        _logging.getLogger("yfinance").setLevel(_logging.CRITICAL)
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _yf_symbol(code: str) -> str:
            return f"{code.lstrip('0').zfill(4)}.HK"

        def _fetch_one(code: str) -> tuple[str, float | None]:
            try:
                t = yf.Ticker(_yf_symbol(code))
                info = t.info if hasattr(t, 'info') else {}
                mc = info.get("marketCap") if isinstance(info, dict) else None
                if mc is not None:
                    return code, round(float(mc) / 1e8, 2)
            except Exception:
                pass
            return code, None

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch_one, c): c for c in uncached}
            for fut in as_completed(futures):
                code, mc = fut.result()
                cache[code] = mc  # cache both hits and misses

        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))
        logger.info(
            "Fetched market caps: %d/%d in cache (%.0f%% with data)",
            len(cache), len(codes),
            sum(1 for v in cache.values() if v is not None) / max(len(cache), 1) * 100,
        )

    return cache


def _export_json(query_date: date, alerts_today: int) -> None:
    """Export all stocks + top movers to ccass.json in repo root for dashboard."""
    date_str = query_date.strftime("%Y-%m-%d")
    top_increase: list[dict] = []
    top_decrease: list[dict] = []

    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT t.stock_code, u.stock_name, t.delta_5d_pct, t.delta_20d_pct,
                          t.delta_60d_pct, t.delta_120d_pct,
                          d.total_pct, d.top5_pct, d.top10_pct, d.num_participants,
                          t.consecutive_increase_days, t.consecutive_decrease_days
                   FROM ccass_trends t
                   LEFT JOIN stock_universe u ON u.stock_code = t.stock_code
                   LEFT JOIN ccass_daily d ON d.stock_code = t.stock_code AND d.trade_date = t.trade_date
                   WHERE t.trade_date = ?
                   ORDER BY t.delta_5d_pct DESC""",
                (date_str,),
            ).fetchall()

        # Full stocks array for standalone page (short keys to minimise size)
        stocks: list[dict] = []
        for r in rows:
            stocks.append({
                "c": r["stock_code"],
                "n": r["stock_name"] or r["stock_code"],
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
            else:
                top_decrease.append(entry)

        # Enrich stocks with market cap from Yahoo Finance
        try:
            mc_map = _fetch_market_caps([s["c"] for s in stocks])
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
                "SELECT MIN(trade_date) AS md FROM ccass_daily"
            ).fetchone()
            first_date = min_date_row["md"] if min_date_row and min_date_row["md"] else date_str

        payload = {
            "updated": date_str,
            "first_date": first_date,
            "alerts_today": alerts_today,
            "total_stocks": len(stocks),
            "total_participants": total_participants,
            "stocks": stocks,
            "top_increase": top_increase,
            "top_decrease": top_decrease,
        }
        out_path = Path(__file__).parent.parent.parent / "ccass.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        logger.info(
            "Exported ccass.json (%d stocks, %d up, %d down)",
            len(stocks), len(top_increase), len(top_decrease),
        )
        _post_movers_to_gas(top_increase, top_decrease, date_str)
        _stage_outputs(out_path)
    except Exception as e:
        logger.warning("ccass.json export failed: %s", e)


def _post_movers_to_gas(
    top_increase: list[dict],
    top_decrease: list[dict],
    date_str: str,
) -> None:
    import os
    import requests as _req
    webhook_url = os.getenv("GAS_WEBHOOK_URL", "")
    secret = os.getenv("GAS_SECRET", "")
    if not webhook_url:
        logger.debug("GAS_WEBHOOK_URL not set, skip CCASS GAS post")
        return
    created_at = date_str + "T17:00:00"

    def _post(entry: dict, signal: str) -> None:
        code = str(entry["code"]).zfill(5)
        pct5 = entry.get("delta_5d", 0)
        pct20 = entry.get("delta_20d", 0)
        body: dict = {
            "source":     "ccass",
            "category":   "tech",
            "code":       code,
            "name":       entry.get("name") or code,
            "signal":     signal,
            "created_at": created_at,
            "message":    f"5日持倉 {pct5:+.1f}%（20日 {pct20:+.1f}%）",
            "tags":       "CCASS",
        }
        if secret:
            body["secret"] = secret
        try:
            r = _req.post(webhook_url, json=body, timeout=30)
            logger.debug("GAS %s %s → %s", code, signal, r.status_code)
        except Exception as exc:
            logger.warning("GAS post failed %s: %s", code, exc)

    for e in top_increase:
        _post(e, "CCASS增持")
    for e in top_decrease:
        _post(e, "CCASS減持")
    logger.info("Posted %d CCASS signals to GAS", len(top_increase) + len(top_decrease))


def _stage_outputs(json_path):
    """Compress ccass.db → ccass.db.gz + stage both files for git commit.

    IMPORTANT: This function does NOT commit or push. It only stages files.
    The workflow YAML's "Commit ccass.json" step handles the actual
    git commit + push. Having TWO places do git push causes a race
    condition where the Python push loses to the workflow step push,
    and ccass.db.gz gets dropped. One pusher = no race.
    """
    import subprocess, gzip, shutil
    repo_root = json_path.parent
    db_path = json_path.parent / "ccass" / "ccass.db"
    db_gz_path = json_path.parent / "ccass" / "ccass.db.gz"
    try:
        # Compress ccass.db
        if db_path.exists():
            with open(db_path, 'rb') as f_in:
                with gzip.open(db_gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logger.info("Compressed ccass.db: %d → %d bytes",
                        db_path.stat().st_size, db_gz_path.stat().st_size)

        # Stage BOTH files. The workflow YAML step runs 'git add ccass.json'
        # and then commits everything staged — so ccass.db.gz goes along.
        subprocess.run(["git","add","ccass.json"], cwd=repo_root, capture_output=True)
        if db_gz_path.exists():
            subprocess.run(["git","add","ccass/ccass.db.gz"], cwd=repo_root, capture_output=True)
        logger.info("Staged ccass.json + ccass.db.gz for workflow commit")
    except Exception as e:
        logger.warning("Stage outputs failed: %s", e)


def _detect_and_log_events(t_date: date, y_date: date) -> list[dict]:
    """Compare per-broker CCASS holdings between T and T-1 for all stocks.

    Queries ccass_holdings in bulk, groups by stock in Python, runs
    detect_events(), logs new events to ccass_events, and returns
    the list of newly logged events (with DB ids) for alert dispatch.
    """
    t_str = t_date.strftime("%Y-%m-%d")
    y_str = y_date.strftime("%Y-%m-%d")

    # 1. Get total_shares for all stocks on T (for % calculation)
    with get_conn() as conn:
        shares_rows = conn.execute(
            "SELECT stock_code, total_shares FROM ccass_daily WHERE trade_date = ?",
            (t_str,),
        ).fetchall()
    shares_map = {r["stock_code"]: r["total_shares"] for r in shares_rows if r["total_shares"]}

    # 2. Get ALL holdings for T and T-1 (bulk fetch)
    with get_conn() as conn:
        t_rows = conn.execute(
            "SELECT stock_code, participant_id, shares FROM ccass_holdings WHERE trade_date = ?",
            (t_str,),
        ).fetchall()
        y_rows = conn.execute(
            "SELECT stock_code, participant_id, shares FROM ccass_holdings WHERE trade_date = ?",
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
                    """INSERT INTO ccass_events
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
            "Detected %d CCASS events (deposit/transfer) across %d stocks",
            len(new_events), len(common_codes),
        )
    return new_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today HK)")
    parser.add_argument("--skip-scrape", action="store_true")
    parser.add_argument("--skip-alerts", action="store_true")
    parser.add_argument("--refresh-universe", action="store_true")
    args = parser.parse_args()

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
