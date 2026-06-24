"""Regenerate holdings.json directly from DB — skips shard validation."""
import json, sys, sqlite3, argparse, shutil
from pathlib import Path

# Add holdings/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.merge_shards import update_holdings_json
from datetime import date


def pick_latest_trade_date(db: sqlite3.Connection) -> date | None:
    """Return the newest trade date that has at least one valid row."""
    row = db.execute(
        """
        SELECT trade_date
        FROM ccass_daily
        WHERE validation_failed = 0
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT 1
        """
    ).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: latest in DB)")
    args = parser.parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        from src.db import DB_PATH
        db = sqlite3.connect(str(DB_PATH))
        target_date = pick_latest_trade_date(db)
        db.close()
        if not target_date:
            print("ERROR: No data in DB")
            sys.exit(1)
        print(f"Using latest date: {target_date}")

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
