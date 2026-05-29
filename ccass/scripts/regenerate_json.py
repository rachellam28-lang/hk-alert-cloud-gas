"""Regenerate ccass.json directly from DB — skips shard validation."""
import sys, sqlite3, argparse
from pathlib import Path

# Add ccass/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.merge_shards import update_ccass_json
from datetime import date

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: latest in DB)")
    args = parser.parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        from src.db import DB_PATH
        db = sqlite3.connect(str(DB_PATH))
        row = db.execute("SELECT MAX(trade_date) FROM ccass_daily").fetchone()
        db.close()
        if not row or not row[0]:
            print("ERROR: No data in DB")
            sys.exit(1)
        target_date = date.fromisoformat(row[0])
        print(f"Using latest date: {target_date}")

    print(f"Regenerating ccass.json for {target_date}...")
    update_ccass_json(target_date)
    print("Done.")
