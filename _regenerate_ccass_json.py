"""
Monolithic script: Regenerate ccass.json from existing DB.

Reads ccass_daily + ccass_trends + stock_universe + market_caps,
applies the SAME logic as the fixed update_ccass_json() in merge_shards.py:
  - round() every float field to 2 decimal places
  - compute top_increase, top_decrease, total_participants, first_date
  - include market_cap

Fixes P2-2 (missing summary fields) and P2-3 (float precision artifacts).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent / "ccass"
DB_PATH = PROJECT_ROOT / "ccass.db"
OUT_PATH = Path(__file__).parent / "ccass.json"

# ── Which date to target ──────────────────────────────────────────────
# Use the latest trade_date present in ccass_daily
db = sqlite3.connect(str(DB_PATH))
db.row_factory = sqlite3.Row
latest = db.execute("SELECT MAX(trade_date) FROM ccass_daily").fetchone()
if not latest or not latest[0]:
    print("ERROR: No data in ccass_daily")
    exit(1)
TARGET_DATE = datetime.strptime(latest[0], "%Y-%m-%d").date()
print(f"Target date: {TARGET_DATE}")

# ── 1. Stock names ────────────────────────────────────────────────────
names = {}
for row in db.execute("SELECT stock_code, stock_name FROM stock_universe"):
    names[row[0]] = row[1] or row[0]
print(f"Stock names loaded: {len(names)}")

# ── 2. Daily data for target date ─────────────────────────────────────
rows = db.execute("""
    SELECT cd.stock_code, cd.total_pct, cd.num_participants,
           cd.top5_pct, cd.top10_pct
    FROM ccass_daily cd
    WHERE cd.trade_date = ?
""", (TARGET_DATE.strftime("%Y-%m-%d"),)).fetchall()
print(f"Daily rows for {TARGET_DATE}: {len(rows)}")

# ── 3. Trends (streaks + deltas) for target date ──────────────────────
trends = {}
for row in db.execute("""
    SELECT stock_code, delta_5d_pct, delta_20d_pct, delta_60d_pct, delta_120d_pct,
           consecutive_increase_days, consecutive_decrease_days
    FROM ccass_trends
    WHERE trade_date = ?
""", (TARGET_DATE.strftime("%Y-%m-%d"),)).fetchall():
    trends[row[0]] = {
        'd5': row[1], 'd20': row[2], 'd60': row[3], 'd120': row[4],
        'su': row[5] or 0, 'sd': row[6] or 0,
    }
print(f"Trends loaded: {len(trends)} stocks")

# ── 4. Market caps ─────────────────────────────────────────────────────
mc_map = {}
try:
    dated_path = PROJECT_ROOT / "cache" / f"market_caps_{TARGET_DATE.strftime('%Y-%m-%d')}.json"
    legacy_path = PROJECT_ROOT / "cache" / "market_caps.json"
    mc_path = dated_path if dated_path.exists() else (legacy_path if legacy_path.exists() else None)
    if mc_path and mc_path.exists():
        mc_data = json.loads(mc_path.read_text(encoding='utf-8'))
        for item in mc_data:
            mc_map[item.get('stock_code', '')] = item.get('market_cap')
    print(f"Market caps loaded: {len(mc_map)} (from {mc_path.name})")
except Exception as e:
    print(f"Market caps skipped: {e}")

# ── 5. Build stock list (with round() on every float) ─────────────────
stocks = []
for row in rows:
    sc = row[0]
    tp = round(row[1] or 0, 2)
    np_val = row[2] or 0
    t5 = round(row[3] or 0, 2)
    t10 = round(row[4] or 0, 2)

    tr = trends.get(sc, {})
    mc = mc_map.get(sc)

    d5_raw = tr.get('d5')
    d20_raw = tr.get('d20')
    d60_raw = tr.get('d60')
    d120_raw = tr.get('d120')

    stocks.append({
        'c': sc,
        'n': names.get(sc, sc),
        'tp': tp,
        't5': t5,
        't10': t10,
        'd5': round(d5_raw, 2) if d5_raw is not None else None,
        'd20': round(d20_raw, 2) if d20_raw is not None else None,
        'd60': round(d60_raw, 2) if d60_raw is not None else None,
        'd120': round(d120_raw, 2) if d120_raw is not None else None,
        'su': tr.get('su', 0),
        'sd': tr.get('sd', 0),
        'np': np_val,
        'mc': mc,
    })

# ── 6. Summary fields ─────────────────────────────────────────────────
total_participants = sum(s['np'] for s in stocks)

# Top increase / decrease (by 5-day delta)
sorted_up = sorted(
    [s for s in stocks if s['d5'] is not None and s['d5'] > 0],
    key=lambda s: -s['d5'],
)[:5]
sorted_dn = sorted(
    [s for s in stocks if s['d5'] is not None and s['d5'] < 0],
    key=lambda s: s['d5'],
)[:5]
top_increase = [{'c': s['c'], 'n': s['n'], 'd5': s['d5']} for s in sorted_up]
top_decrease = [{'c': s['c'], 'n': s['n'], 'd5': s['d5']} for s in sorted_dn]

# First date in DB
first_row = db.execute("SELECT MIN(trade_date) FROM ccass_daily").fetchone()
first_date = first_row[0] if first_row and first_row[0] else TARGET_DATE.strftime("%Y-%m-%d")

# ── 7. Assemble & write ────────────────────────────────────────────────
out = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    "stock_count": len(stocks),
    "stocks": stocks,
    "top_increase": top_increase,
    "top_decrease": top_decrease,
    "first_date": first_date,
    "total_participants": total_participants,
}

OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nccass.json written: {len(stocks)} stocks")
print(f"  top_increase: {len(top_increase)} entries")
print(f"  top_decrease: {len(top_decrease)} entries")
print(f"  total_participants: {total_participants}")
print(f"  first_date: {first_date}")

db.close()
print("\nDone.")
