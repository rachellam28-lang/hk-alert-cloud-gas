"""Main daily runner.

Workflow:
1. Check 今日係咪 trading day。如果唔係，exit。
2. 攞 universe (refresh weekly)
3. Scrape 全部股票
4. Compute trends
5. Detect alerts → Telegram
6. Log run metadata
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
from src.alerts import detect_alerts, send_alerts, send_admin_alert

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


def _export_json(query_date: date, alerts_today: int) -> None:
    """Export top movers to ccass.json in repo root for dashboard."""
    date_str = query_date.strftime("%Y-%m-%d")
    top_increase: list[dict] = []
    top_decrease: list[dict] = []

    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT t.stock_code, u.stock_name, t.delta_5d_pct, t.delta_20d_pct,
                          d.total_pct, d.top5_pct, d.top10_pct,
                          t.consecutive_increase_days, t.consecutive_decrease_days
                   FROM ccass_trends t
                   LEFT JOIN stock_universe u ON u.stock_code = t.stock_code
                   LEFT JOIN ccass_daily d ON d.stock_code = t.stock_code AND d.trade_date = t.trade_date
                   WHERE t.trade_date = ? AND t.delta_5d_pct IS NOT NULL
                   ORDER BY t.delta_5d_pct DESC""",
                (date_str,),
            ).fetchall()

        for r in rows:
            entry = {
                "code": r["stock_code"],
                "name": r["stock_name"] or r["stock_code"],
                "delta_5d": round(r["delta_5d_pct"], 2),
                "delta_20d": round(r["delta_20d_pct"] or 0, 2),
                "total_pct": round(r["total_pct"] or 0, 2),
                "top5_pct": round(r["top5_pct"] or 0, 2),
                "top10_pct": round(r["top10_pct"] or 0, 2),
                "streak_up": r["consecutive_increase_days"] or 0,
                "streak_dn": r["consecutive_decrease_days"] or 0,
            }
            if r["delta_5d_pct"] > 0:
                top_increase.append(entry)
            else:
                top_decrease.append(entry)

        top_increase = top_increase[:10]
        top_decrease = sorted(top_decrease, key=lambda x: x["delta_5d"])[:10]

        payload = {
            "updated": date_str,
            "alerts_today": alerts_today,
            "top_increase": top_increase,
            "top_decrease": top_decrease,
        }
        out_path = Path(__file__).parent.parent.parent / "ccass.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Exported ccass.json (%d up, %d down)", len(top_increase), len(top_decrease))
        _post_movers_to_gas(top_increase, top_decrease, date_str)
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
