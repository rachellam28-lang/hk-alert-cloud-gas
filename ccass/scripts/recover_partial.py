"""Recover partial backfill data from existing JSON shard files.

Usage:
    cd ccass
    python -m scripts.recover_partial 2026-05-15

This scans for any existing backfill-shard-*-YYYY-MM-DD-*.json files
and merges whatever data is available into the DB. Useful after a
crash — the JSON files are atomic (tmp → rename), so any file that
exists has valid data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
# Project root is ccass/, the backfill files are one level up
# (parallel_backfill writes them to _PROJECT_ROOT which = ccass/)
# But the shard subprocess writes via --out with the parent giving
# the path: ccass/backfill-shard-YYYY-MM-DD-N.json


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.recover_partial YYYY-MM-DD")
        sys.exit(1)

    date_str = sys.argv[1]

    from src.db import init_db
    from src.scraper import save_snapshot, CCASSSnapshot

    init_db()

    # Find all shard JSON files for this date in the ccass directory
    pattern = f"backfill-shard-{date_str}-*.json"
    json_files = sorted(_PROJECT_ROOT.glob(pattern))

    if not json_files:
        print(f"❌ No backfill-shard-{date_str}-*.json files found in {_PROJECT_ROOT}")
        sys.exit(1)

    print(f"📂 Found {len(json_files)} shard file(s) for {date_str}:")
    for jf in json_files:
        print(f"   {jf.name} ({jf.stat().st_size / 1024:.1f} KB)")

    total_new = 0
    total_skipped = 0
    for jf in json_files:
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ❌ {jf.name}: JSON parse error: {e}")
            continue

        code = payload.get("query_date", "??")
        shard = payload.get("shard", "?")
        snapshots = payload.get("snapshots", [])

        if not snapshots:
            print(f"  ⚠️  {jf.name}: no snapshots")
            continue

        written = 0
        skipped = 0
        for snap_dict in snapshots:
            # Convert dict → CCASSSnapshot so we can use save_snapshot
            snap = CCASSSnapshot(
                stock_code=snap_dict["stock_code"],
                trade_date=snap_dict["trade_date"],
                total_shares=snap_dict["total_shares"],
                total_pct=snap_dict["total_pct"],
                num_participants=snap_dict.get("num_participants", 0),
                holdings=snap_dict.get("holdings", []),
            )
            try:
                save_snapshot(snap)
                written += 1
            except Exception:
                skipped += 1

        total_new += written
        total_skipped += skipped
        print(f"  ✅ {jf.name}: shard={shard} date={code} → {written} written, {skipped} skipped")

    # Verify
    import sqlite3
    db_path = _PROJECT_ROOT / "ccass.db"
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    count = conn.execute(
        "SELECT COUNT(*) FROM ccass_daily WHERE trade_date = ?", (date_str,)
    ).fetchone()[0]
    conn.close()

    print(f"\n📊 DB now has {count} snapshots for {date_str}")
    print(f"✅ Recovery complete: {total_new} new + {total_skipped} skipped")


if __name__ == "__main__":
    main()
