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
import sys
import time
import traceback
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
        if row["n"] == 0:
            return True
    return today_hk().weekday() == 0  # Monday


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
    # 所以「今日 8am 跑」實際上係 query 噚日 trading day
    query_date = previous_trading_day(target_date + timedelta(days=1))
    logger.info("Querying CCASS data for %s", query_date)

    # 1. Start run log
    now_iso = datetime.utcnow().isoformat()
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
        return 0 if status == "success" else 1

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
