"""Main daily runner — sharded version.

Workflow:
  SHARD MODE (--shard N --shard-total M --out PATH):
    1. Refresh universe
    2. Scrape subset (stocks[N::M])
    3. Serialise snapshots → backfill-shard-N.json
    ── NO trends, NO alerts, NO export ──

  SINGLE MODE (no --shard, or --shard without --out):
    1. Refresh universe (if needed)
    2. Scrape all active stocks sequentially
    3. Compute trends
    4. Detect & send alerts
    5. Export JSON + stage outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
import time
import traceback
from datetime import datetime, date
from pathlib import Path

import yaml

from src.db import init_db, get_conn
from src.logger import setup_logger
from src.trading_calendar import today_hk, is_trading_day, previous_trading_day
from src.universe import refresh_universe, get_active_stocks
from src.scraper import CCASSScraper, save_snapshot, CCASSSnapshot
from src.trend import compute_trends_for_date
from src.alerts import detect_alerts, send_alerts, send_admin_alert

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = setup_logger("runner")
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


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


def _snapshot_to_dict(snap: CCASSSnapshot) -> dict:
    return {
        "stock_code": snap.stock_code,
        "trade_date": snap.trade_date,
        "total_shares": snap.total_shares,
        "total_pct": snap.total_pct,
        "num_participants": snap.num_participants,
        "holdings": snap.holdings,
    }


def _write_shard_json(
    shard_idx: int,
    shard_total: int,
    query_date: date,
    target_date: date,
    total_stocks: int,
    shard_stocks: int,
    succeeded: int,
    failed_stocks: list[str],
    snapshots: list[dict],
    out_path: Path,
) -> None:
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
    # Atomic write: tmp → rename
    tmp_path = Path(str(out_path) + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.rename(out_path)
    logger.info(
        "Wrote %d snapshots → %s (%.1f KB)",
        len(snapshots), out_path.name, out_path.stat().st_size / 1024,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  SHARD MODE (JSON output — for parallel_backfill.py)
# ═══════════════════════════════════════════════════════════════════════════

def run_shard(
    shard_idx: int,
    shard_total: int,
    query_date: date,
    out_path: Path,
    force_universe_refresh: bool = False,
) -> int:
    """Scrape one shard, write JSON. No trends/alerts/export.

    Returns 0 on success (even with partial failures).
    Returns 2 on HKEX block / RuntimeError detected.
    """
    init_db()
    config = load_config()

    logger.info("SHARD %d/%d — query_date=%s", shard_idx + 1, shard_total, query_date)
    target_date = query_date  # backfill mode: scrape exact date

    # Refresh universe once (parent parallel_backfill also refreshes, but belt+suspenders)
    if force_universe_refresh:
        try:
            refresh_universe()
        except Exception as e:
            logger.error("Universe refresh failed in shard %d: %s", shard_idx, e)

    stocks = get_active_stocks()
    logger.info("Universe: %d active stocks", len(stocks))

    # Shard: interleaved assignment stocks[shard_idx::shard_total]
    my_stocks = stocks[shard_idx::shard_total]
    logger.info("Shard %d: %d stocks assigned", shard_idx, len(my_stocks))

    if not my_stocks:
        logger.warning("Shard %d: zero stocks — writing empty JSON and exiting", shard_idx)
        _write_shard_json(
            shard_idx, shard_total, query_date, target_date,
            len(stocks), 0, 0, [], [], out_path=out_path,
        )
        return 0

    sc_cfg = config["scraping"]
    _delay_min = float(os.environ.get("CCASS_DELAY_MIN", sc_cfg["delay_min_seconds"]))
    _delay_max = float(os.environ.get("CCASS_DELAY_MAX", sc_cfg["delay_max_seconds"]))
    _max_retries = int(os.environ.get("CCASS_MAX_RETRIES", sc_cfg.get("max_retries", 3)))
    _timeout = int(os.environ.get("CCASS_TIMEOUT", sc_cfg["timeout_seconds"]))

    scraper = CCASSScraper(
        user_agent=sc_cfg["user_agent"],
        delay_min=_delay_min,
        delay_max=_delay_max,
        timeout=_timeout,
        max_retries=_max_retries,
    )

    try:
        snapshots: list[dict] = []
        succeeded = 0
        failed_stocks: list[str] = []

        # Internal deadline: abort if shard takes too long
        deadline = time.monotonic() + 9000  # 150 minutes
        deadline_exceeded = False

        i = 0
        while i < len(my_stocks):
            code = my_stocks[i]

            if time.monotonic() > deadline:
                logger.error(
                    "Shard %d internal deadline exceeded at %d/%d",
                    shard_idx, i, len(my_stocks),
                )
                failed_stocks.extend(my_stocks[i:])
                deadline_exceeded = True
                break

            if (i + 1) % 50 == 0:
                logger.info(
                    "Shard %d progress: %d/%d (%.1f%%)",
                    shard_idx, i + 1, len(my_stocks), 100 * (i + 1) / len(my_stocks),
                )

            try:
                snap = scraper.scrape_stock(code, query_date)
                if snap:
                    snapshots.append(_snapshot_to_dict(snap))
                    succeeded += 1
                    i += 1
                elif scraper._is_in_cooldown():
                    # Scraper in cooldown — wait and retry same stock
                    remaining = (scraper._blocked_until - datetime.utcnow()).total_seconds()
                    if remaining > 0:
                        logger.warning(
                            "⏸️  Shard %d cooldown (%.0fs remaining). Waiting...",
                            shard_idx, remaining,
                        )
                        time.sleep(remaining + 5)
                        logger.info("Cooldown expired, resuming from %s", code)
                    else:
                        logger.info("Cooldown just expired, retrying %s", code)
                else:
                    # Genuine failure
                    failed_stocks.append(code)
                    i += 1
            except RuntimeError as e:
                # HKEX block detected — abort with exit code 2
                logger.error(
                    "Shard %d aborting on RuntimeError from %s: %s",
                    shard_idx, code, e,
                )
                failed_stocks.append(code)
                _write_shard_json(
                    shard_idx, shard_total, query_date, target_date,
                    len(stocks), len(my_stocks), succeeded, failed_stocks, snapshots,
                    out_path=out_path,
                )
                return 2
            except Exception:
                logger.exception("Shard %d unexpected error on %s", shard_idx, code)
                failed_stocks.append(code)
                i += 1

        logger.info(
            "Shard %d done: %d/%d succeeded, %d failed",
            shard_idx, succeeded, len(my_stocks), len(failed_stocks),
        )

        _write_shard_json(
            shard_idx, shard_total, query_date, target_date,
            len(stocks), len(my_stocks), succeeded, failed_stocks, snapshots,
            out_path=out_path,
        )

        if deadline_exceeded:
            return 3  # internal shard timeout (NOT HKEX block!)

        return 0  # partial failures are normal
    finally:
        scraper.close()


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN DAILY RUN
# ═══════════════════════════════════════════════════════════════════════════

def run_daily(
    target_date: date | None = None,
    skip_scrape: bool = False,
    skip_alerts: bool = False,
    skip_trends: bool = False,
    force_universe_refresh: bool = False,
    shard_index: int = 0,
    shard_total: int = 1,
    dry_run: bool = False,
) -> int:
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

        # Shard: divide stocks across parallel workers
        if shard_total > 1:
            chunk = len(stocks) // shard_total
            start = shard_index * chunk
            end = start + chunk if shard_index < shard_total - 1 else len(stocks)
            stocks = stocks[start:end]
            logger.info(
                "Shard %d/%d: %d stocks assigned (indices %d-%d)",
                shard_index + 1, shard_total, len(stocks), start, end - 1,
            )

        if not stocks:
            raise RuntimeError("Empty universe — cannot proceed")

        if not skip_scrape:
            sc_cfg = config["scraping"]
            # Environment variable overrides (used by parallel_backfill.py)
            _delay_min = float(os.environ.get("CCASS_DELAY_MIN", sc_cfg["delay_min_seconds"]))
            _delay_max = float(os.environ.get("CCASS_DELAY_MAX", sc_cfg["delay_max_seconds"]))
            _max_retries = int(os.environ.get("CCASS_MAX_RETRIES", sc_cfg.get("max_retries", 3)))
            scraper = CCASSScraper(
                user_agent=sc_cfg["user_agent"],
                delay_min=_delay_min,
                delay_max=_delay_max,
                timeout=sc_cfg["timeout_seconds"],
                max_retries=_max_retries,
            )
            i = 0
            while i < len(stocks):
                code = stocks[i]
                attempted += 1
                if attempted % 10 == 0:
                    logger.info("Progress: %d/%d (%.1f%%), succeeded=%d, failed=%d",
                                i + 1, len(stocks), 100 * (i + 1) / len(stocks),
                                succeeded, len(failed_stocks))
                try:
                    snap = scraper.scrape_stock(code, query_date)
                    if snap:
                        save_snapshot(snap)
                        succeeded += 1
                        i += 1
                    elif scraper._is_in_cooldown():
                        # Scraper is in cooldown — wait and retry same stock
                        remaining = (scraper._blocked_until - datetime.utcnow()).total_seconds()
                        if remaining > 0:
                            logger.warning(
                                "⏸️  Scraper in cooldown (%.0fs remaining). "
                                "Waiting before retry...",
                                remaining,
                            )
                            time.sleep(remaining + 5)  # +5s buffer
                            logger.info("Cooldown expired, resuming from %s (#%d)", code, i + 1)
                            # Don't increment i — retry same stock
                        else:
                            # Cooldown just expired, retry immediately
                            logger.info("Cooldown just expired, retrying %s", code)
                    else:
                        # Genuine failure (no data, parse error, etc.)
                        failed_stocks.append(code)
                        i += 1
                except Exception:
                    logger.exception("Unexpected error on %s", code)
                    failed_stocks.append(code)
                    i += 1

        try:
            if not skip_trends:
                compute_trends_for_date(query_date, config["trend_windows"])
            else:
                logger.info("Trends skipped (-no-trends)")
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
#  EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _export_json(query_date, alerts_today):
    date_str = query_date.strftime("%Y-%m-%d")
    top_increase = []
    top_decrease = []
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT t.stock_code, u.stock_name, t.delta_5d_pct, t.delta_20d_pct,
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
                "su": r["consecutive_increase_days"] or 0,
                "sd": r["consecutive_decrease_days"] or 0,
                "np": r["num_participants"] or 0,
            })
            entry = {
                "code": r["stock_code"], "name": r["stock_name"] or r["stock_code"],
                "delta_5d": round(r["delta_5d_pct"], 2) if r["delta_5d_pct"] is not None else 0,
                "delta_20d": round(r["delta_20d_pct"] or 0, 2) if r["delta_20d_pct"] is not None else 0,
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
        _stage_outputs(out_path)
    except Exception as e:
        logger.exception("ccass.json export failed")
        raise


def _stage_outputs(json_path):
    import gzip, shutil
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
    parser.add_argument("--skip-trends", action="store_true")
    parser.add_argument("--refresh-universe", action="store_true")
    parser.add_argument("--shard", type=int, default=0, help="Shard index (0-based)")
    parser.add_argument("--shard-total", type=int, default=1, help="Total shards")
    parser.add_argument("--query-date", help="Specific date YYYY-MM-DD (backfill mode)")
    parser.add_argument("--out", help="Output JSON path (shard mode)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # ── Shard mode with JSON output (for parallel_backfill.py) ──
    if args.out and args.query_date:
        qdate = datetime.strptime(args.query_date, "%Y-%m-%d").date()
        out_path = Path(args.out)
        rc = run_shard(
            shard_idx=args.shard,
            shard_total=args.shard_total,
            query_date=qdate,
            out_path=out_path,
            force_universe_refresh=args.refresh_universe,
        )
        sys.exit(rc)

    # ── Standard single mode ──
    target = None
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    rc = run_daily(
        target_date=target,
        skip_scrape=args.skip_scrape,
        skip_alerts=args.skip_alerts,
        skip_trends=args.skip_trends,
        force_universe_refresh=args.refresh_universe,
        shard_index=args.shard,
        shard_total=args.shard_total,
        dry_run=args.dry_run,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
