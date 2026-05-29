"""
Detect CCASS 轉倉 (warehouse transfers) between last 2 trading days.
Output: data/transfers.json — list of significant position changes.
"""
import sqlite3, json, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "ccass.db"
OUT_PATH = PROJECT_ROOT / "data" / "transfers.json"

db = sqlite3.connect(str(DB_PATH))

# Get last 2 dates with actual data (skip 05-28=05-27 proxy)
dates = [r[0] for r in db.execute(
    "SELECT DISTINCT trade_date FROM ccass_holdings ORDER BY trade_date DESC LIMIT 10"
).fetchall()]
# Skip 05-28 if same as 05-27 (proxy data)
if len(dates) >= 3 and dates[0] == '2026-05-28' and dates[1] == '2026-05-27':
    d1, d2 = dates[2], dates[1]  # Use 05-26 vs 05-27, or better 05-22 vs 05-26
    # Actually use the biggest gap with data
    d1, d2 = dates[3], dates[2] if len(dates) >= 4 else (dates[1], dates[2])  # 05-22 vs 05-26
else:
    d1, d2 = dates[0], dates[1]
print(f"Comparing {d1} vs {d2}...")

# Get all participants with >500K share change per stock (indexed query)
changes = db.execute("""
    SELECT h1.stock_code, h1.participant_id, h1.participant_name,
           h1.shares - h2.shares AS share_chg,
           ROUND(h1.pct_of_issued - h2.pct_of_issued, 4) AS pct_chg,
           h1.shares AS today_shares
    FROM ccass_holdings h1
    JOIN ccass_holdings h2 
      ON h1.stock_code = h2.stock_code 
     AND h1.participant_id = h2.participant_id
    WHERE h1.trade_date = ? AND h2.trade_date = ?
      AND ABS(h1.shares - h2.shares) > 100000  -- >100K shares for transfer signal
    ORDER BY ABS(h1.shares - h2.shares) DESC
    LIMIT 500
""", (d1, d2)).fetchall()

# Group by stock to detect transfers
from collections import defaultdict
stock_changes = defaultdict(list)
for r in changes:
    stock_changes[r[0]].append({
        'pid': r[1],
        'pname': r[2],
        'chg': r[3],
        'pct_chg': r[4],
        'shares': r[5]
    })

# Detect transfers: stock has both big increase AND big decrease participants
transfers = []
for code, items in stock_changes.items():
    ins = [i for i in items if i['chg'] > 0]
    outs = [i for i in items if i['chg'] < 0]
    if ins and outs:
        # Get stock name and total CCASS shares
        name_row = db.execute(
            "SELECT stock_name FROM stock_universe WHERE stock_code=?", (code,)
        ).fetchone()
        name = name_row[0] if name_row else code
        
        # Get total CCASS shares on latest date
        total_shares_row = db.execute(
            "SELECT SUM(shares) FROM ccass_holdings WHERE stock_code=? AND trade_date=?",
            (code, d1)
        ).fetchone()
        total_shares = total_shares_row[0] if total_shares_row[0] else 0
        
        total_in = sum(i['chg'] for i in ins)
        total_out = sum(abs(i['chg']) for i in outs)
        
        transfers.append({
            'code': code,
            'name': name,
            'total_in': total_in,
            'total_out': total_out,
            'total_shares': total_shares,
            'ins': sorted(ins, key=lambda x: -x['chg']),
            'outs': sorted(outs, key=lambda x: x['chg']),
        })

# Sort by total volume
transfers.sort(key=lambda x: -(x['total_in'] + x['total_out']))

print(f"Found {len(transfers)} stocks with transfers (top 50)")
for t in transfers[:20]:
    print(f"  {t['code']} {t['name']}: in={t['total_in']:,.0f} out={t['total_out']:,.0f} from {len(t['ins'])}/{len(t['outs'])} participants")

# Save to both ccass/data/ (source) and repo data/ (dashboard)
os.makedirs(OUT_PATH.parent, exist_ok=True)
with open(OUT_PATH, 'w') as f:
    json.dump({
        'updated': f'{d1} vs {d2}',
        'count': len(transfers),
        'transfers': transfers[:50]  # Top 50
    }, f, ensure_ascii=False)

print(f"\nSaved {min(len(transfers), 50)} transfers to {OUT_PATH}")

# Also copy to repo data/ folder for dashboard
import shutil
REPO_DATA = PROJECT_ROOT.parent / "data" / "transfers.json"
shutil.copyfile(OUT_PATH, REPO_DATA)
print(f"Copied to {REPO_DATA}")

db.close()
