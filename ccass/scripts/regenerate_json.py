"""Regenerate holdings.json directly from DB — skips shard validation."""
import json, sys, sqlite3, argparse, shutil
from pathlib import Path

# Add holdings/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.merge_shards import update_holdings_json
from datetime import date


def _eligible_total(db: sqlite3.Connection) -> int:
    row = db.execute(
        """
        SELECT COUNT(*)
        FROM stock_universe
        WHERE is_active=1
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """
    ).fetchone()
    return int(row[0] or 0)


def pick_latest_trade_date(db: sqlite3.Connection, min_coverage: float) -> date | None:
    """Return the newest publishable trade date, not a partial scrape tail."""
    total = _eligible_total(db)
    rows = db.execute(
        """
        SELECT trade_date, COUNT(DISTINCT stock_code) AS stock_count
        FROM ccass_daily
        WHERE validation_failed = 0
        GROUP BY trade_date
        ORDER BY trade_date DESC
        """
    ).fetchall()
    for trade_date, count in rows:
        pct = (int(count or 0) / total * 100) if total else 0
        if pct >= min_coverage:
            return date.fromisoformat(trade_date)
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: latest in DB)")
    parser.add_argument("--min-coverage", type=float, default=99.0, help="Minimum DB coverage for default publish date")
    args = parser.parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        from src.db import DB_PATH
        db = sqlite3.connect(str(DB_PATH))
        target_date = pick_latest_trade_date(db, args.min_coverage)
        db.close()
        if not target_date:
            print(f"ERROR: No DB date reaches {args.min_coverage}% coverage")
            sys.exit(1)
        print(f"Using latest publishable date: {target_date}")

    print(f"Regenerating holdings.json for {target_date}...")
    update_holdings_json(target_date)
    out_path = Path(__file__).parent.parent.parent / "holdings.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    data_path = Path(__file__).parent.parent.parent / "data" / "holdings.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out_path, data_path)
    expected = target_date.isoformat()
    if data.get("updated") != expected:
        print(f"ERROR: holdings.json stale date: {data.get('updated')} != {expected}")
        sys.exit(1)
    print("Done.")
