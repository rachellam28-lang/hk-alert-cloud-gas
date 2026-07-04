"""Bulk fill missing HOLDINGS stocks for specific dates."""
import argparse
import json, random, sqlite3, subprocess, sys, os, time, signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
import yaml

PROJECT = Path(__file__).parent.parent
DB = PROJECT / "holdings.db"
SCRAPE_ONE = PROJECT / "src" / "scrape_one.py"
CONFIG = PROJECT / "config.yaml"
sys.path.insert(0, str(PROJECT))


def _load_scraping_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    sc = cfg.get("scraping", {})
    out = {
        "user_agent": sc.get("user_agent", "Mozilla/5.0"),
        "delay_min_seconds": float(sc.get("delay_min_seconds", 4.0)),
        "delay_max_seconds": float(sc.get("delay_max_seconds", 10.0)),
        "timeout_seconds": int(sc.get("timeout_seconds", 30)),
        "max_retries": int(sc.get("max_retries", 3)),
    }
    if os.environ.get("HOLDINGS_BACKFILL_FAST", "0") == "1":
        out["delay_min_seconds"] = min(out["delay_min_seconds"], float(os.environ.get("FILL_DELAY_MIN", "1.5")))
        out["delay_max_seconds"] = min(out["delay_max_seconds"], float(os.environ.get("FILL_DELAY_MAX", "3.0")))
        out["timeout_seconds"] = min(out["timeout_seconds"], int(os.environ.get("FILL_TIMEOUT", "20")))
        out["max_retries"] = min(out["max_retries"], int(os.environ.get("FILL_RETRIES", "1")))
    return out


def _run_child(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from e


def _scrape_one(code: str, target_date: str, sc_cfg: dict) -> tuple[str, dict | None, str | None]:
    if os.environ.get("HOLDINGS_PROVIDER", "hkex").lower() == "longbridge":
        return _scrape_one_longbridge(code, target_date)

    hard_timeout = sc_cfg["timeout_seconds"] * sc_cfg["max_retries"] + 5
    result = _run_child(
        [
            sys.executable, str(SCRAPE_ONE), code, target_date,
            sc_cfg["user_agent"],
            str(sc_cfg["delay_min_seconds"]),
            str(sc_cfg["delay_max_seconds"]),
            str(sc_cfg["timeout_seconds"]),
            str(sc_cfg["max_retries"]),
        ],
        timeout=hard_timeout,
    )
    if result.returncode != 0:
        return code, None, result.stderr.strip() or result.stdout.strip() or f"exit={result.returncode}"

    data = None
    for line in result.stdout.strip().splitlines():
        if line.startswith('{"ok"'):
            data = json.loads(line)
            break
    if not data:
        return code, None, "missing json payload"
    if not data.get("ok"):
        return code, None, data.get("reason", "not ok")
    return code, data, None


def _snapshot_to_dict(snap) -> dict:
    from src.scraper import _compute_concentration_metrics

    sorted_shares = sorted(
        [h["shares"] for h in snap.holdings if h.get("shares")],
        reverse=True,
    )
    top5 = sum(sorted_shares[:5])
    top10 = sum(sorted_shares[:10])
    top5_pct = round(top5 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    top10_pct = round(top10 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    cm = _compute_concentration_metrics(snap.holdings)
    return {
        "ok": True,
        "stock_code": snap.stock_code,
        "trade_date": snap.trade_date,
        "total_shares": snap.total_shares,
        "total_pct": snap.total_pct,
        "num_participants": snap.num_participants,
        "top5_pct": top5_pct,
        "top10_pct": top10_pct,
        "adj_hhi": cm.get("adj_hhi"),
        "broker_top5_pct": cm.get("broker_top5_pct"),
        "top_broker_id": cm.get("top_broker_id", ""),
        "top_broker_name": cm.get("top_broker_name", ""),
        "top_broker_pct": cm.get("top_broker_pct"),
        "futu_pct": cm.get("futu_pct"),
        "a00005_pct": cm.get("a00005_pct"),
        "adjusted_float": cm.get("adjusted_float"),
        "holdings": snap.holdings,
    }


def _scrape_one_longbridge(code: str, target_date: str) -> tuple[str, dict | None, str | None]:
    from datetime import date
    from src.longbridge_provider import scrape_stock

    try:
        snap = scrape_stock(code, date.fromisoformat(target_date))
    except Exception as e:
        return code, None, str(e)[:200]
    if not snap or not snap.holdings:
        return code, None, "no_data"
    return code, _snapshot_to_dict(snap), None


def _save_snapshot(db: sqlite3.Connection, data: dict) -> None:
    now = datetime.utcnow().isoformat()
    db.execute("BEGIN IMMEDIATE")
    db.execute("""
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
        data.get("adjusted_float"), now,
    ))
    # ✅ P0-2 fix: DELETE old holdings before INSERT new (ghost data prevention)
    db.execute("DELETE FROM ccass_holdings WHERE stock_code = ? AND trade_date = ?",
               (data["stock_code"], data["trade_date"]))
    for h in data.get("holdings", []):
        db.execute("""
            INSERT OR REPLACE INTO ccass_holdings
            (stock_code, trade_date, participant_id,
             participant_name, shares, pct_of_issued)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data["stock_code"], data["trade_date"],
            h.get("participant_id"), h.get("participant_name"),
            h.get("shares"), h.get("pct_of_issued"),
        ))
    db.commit()

def fill_missing(target_date: str, max_stocks: int = 3000):
    sc_cfg = _load_scraping_config()
    provider = os.environ.get("HOLDINGS_PROVIDER", "hkex").lower()
    workers = max(1, int(os.environ.get("FILL_MISSING_WORKERS", "1")))
    db = sqlite3.connect(str(DB))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    # Use the active universe as the denominator. The previous implementation
    # used the historical date with the most DB rows, which skipped newly
    # listed/activated stocks and made coverage impossible to repair.
    EXCLUDE_PATTERNS = ["029%", "04%", "8%"]
    exclude_clauses = " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])

    full = set(r[0] for r in db.execute(
        f"""
        SELECT stock_code
        FROM stock_universe
        WHERE is_active=1 AND {exclude_clauses}
        """,
        tuple(EXCLUDE_PATTERNS),
    ))
    have = set(r[0] for r in db.execute(
        'SELECT DISTINCT stock_code FROM holdings_daily WHERE trade_date=?',
        (target_date,)
    ))
    missing = sorted(full - have)[:max_stocks]
    
    print(f"Target: {target_date}, Missing: {len(missing)} stocks")
    
    succeeded = 0
    failed = []

    def _handle(code: str, data: dict | None, err: str | None):
        nonlocal succeeded
        if err or not data:
            failed.append(code)
            if err:
                print(f"  {code}: {err}", file=sys.stderr)
            return
        _save_snapshot(db, data)
        succeeded += 1

    if workers > 1 and len(missing) > 1:
        print(f"Using {workers} workers")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_scrape_one, code, target_date, sc_cfg) for code in missing]
            for i, fut in enumerate(as_completed(futures), 1):
                code, data, err = fut.result()
                _handle(code, data, err)
                if i % 50 == 0:
                    print(f"  Progress: {i}/{len(missing)} ({100*i/len(missing):.1f}%), succeeded={succeeded}, failed={len(failed)}")
    else:
        for i, code in enumerate(missing, 1):
            try:
                code, data, err = _scrape_one(code, target_date, sc_cfg)
                _handle(code, data, err)
            except subprocess.TimeoutExpired:
                failed.append(code)
            except Exception as e:
                print(f"  {code}: {e}", file=sys.stderr)
                failed.append(code)

            if i % 50 == 0:
                print(f"  Progress: {i}/{len(missing)} ({100*i/len(missing):.1f}%), succeeded={succeeded}, failed={len(failed)}")
            if provider != "longbridge":
                time.sleep(random.uniform(sc_cfg["delay_min_seconds"], sc_cfg["delay_max_seconds"]))
    
    db.close()
    print(f"\nDone: {succeeded} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed: {failed[:20]}...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default="2026-05-20")
    parser.add_argument("--max-stocks", type=int, default=int(os.environ.get("FILL_MAX_STOCKS", "3000")))
    args = parser.parse_args()
    fill_missing(args.date, max_stocks=args.max_stocks)
