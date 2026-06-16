"""Bulk fill missing HOLDINGS stocks for specific dates."""
import json, random, sqlite3, subprocess, sys, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
import yaml

PROJECT = Path(__file__).parent.parent
DB = PROJECT / "holdings.db"
SCRAPE_ONE = PROJECT / "src" / "scrape_one.py"
CONFIG = PROJECT / "config.yaml"


def _load_scraping_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    sc = cfg.get("scraping", {})
    return {
        "user_agent": sc.get("user_agent", "Mozilla/5.0"),
        "delay_min_seconds": float(sc.get("delay_min_seconds", 4.0)),
        "delay_max_seconds": float(sc.get("delay_max_seconds", 10.0)),
        "timeout_seconds": int(sc.get("timeout_seconds", 30)),
        "max_retries": int(sc.get("max_retries", 3)),
    }


def _scrape_one(code: str, target_date: str, sc_cfg: dict) -> tuple[str, dict | None, str | None]:
    hard_timeout = sc_cfg["timeout_seconds"] * sc_cfg["max_retries"] + 30
    result = subprocess.run(
        [
            sys.executable, str(SCRAPE_ONE), code, target_date,
            sc_cfg["user_agent"],
            str(sc_cfg["delay_min_seconds"]),
            str(sc_cfg["delay_max_seconds"]),
            str(sc_cfg["timeout_seconds"]),
            str(sc_cfg["max_retries"]),
        ],
        capture_output=True, text=True, timeout=hard_timeout,
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
    workers = max(1, int(os.environ.get("FILL_MISSING_WORKERS", "1")))
    db = sqlite3.connect(str(DB))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    # Get full universe from the date with most stocks
    EXCLUDE_PATTERNS = ["029%", "04621", "8%"]
    exclude_clauses = " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS])
    
    # Find the date with the most stocks (reference universe)
    ref_row = db.execute(
        "SELECT trade_date, COUNT(*) AS n FROM holdings_daily "
        "WHERE " + " AND ".join(["stock_code NOT LIKE ?" for _ in EXCLUDE_PATTERNS]) +
        " GROUP BY trade_date ORDER BY n DESC LIMIT 1",
        tuple(EXCLUDE_PATTERNS)
    ).fetchone()
    if not ref_row:
        print("ERROR: No reference universe found")
        return
    ref_date = ref_row[0]
    
    full = set(r[0] for r in db.execute(
        f"SELECT DISTINCT stock_code FROM holdings_daily WHERE trade_date=? AND {exclude_clauses}",
        (ref_date, *EXCLUDE_PATTERNS)
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
        hard_timeout = sc_cfg["timeout_seconds"] * sc_cfg["max_retries"] + 30
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
            time.sleep(random.uniform(sc_cfg["delay_min_seconds"], sc_cfg["delay_max_seconds"]))
    
    db.close()
    print(f"\nDone: {succeeded} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed: {failed[:20]}...")

if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-05-20"
    fill_missing(date)
