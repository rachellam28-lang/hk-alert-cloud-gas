"""Fill missing 05-27 stocks only — skip already-scraped ones."""
import subprocess, sys, sqlite3, os
from pathlib import Path

PROJECT = Path(__file__).parent / "ccass"
SCRAPE_ONE = PROJECT / "src" / "scrape_one.py"
DB_PATH = PROJECT / "ccass.db"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Find missing stocks
db = sqlite3.connect(str(DB_PATH))
all_stocks = [r[0] for r in db.execute("SELECT stock_code FROM stock_universe ORDER BY stock_code").fetchall()]
have = set(r[0] for r in db.execute("SELECT stock_code FROM ccass_daily WHERE trade_date='2026-05-27'").fetchall())
missing = [s for s in all_stocks if s not in have]
db.close()

print(f"Missing 05-27: {len(missing)} stocks ({missing[0]} - {missing[-1]})")
if not missing:
    print("Nothing to do!")
    sys.exit(0)

success = 0
fail = 0
for i, code in enumerate(missing, 1):
    try:
        r = subprocess.run(
            [sys.executable, str(SCRAPE_ONE), code, "2026-05-27", UA],
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT),
        )
        if r.returncode != 0:
            fail += 1
            continue
        data = __import__('json').loads(r.stdout)
        if not data.get("ok"):
            fail += 1
            continue
        
        # Save to DB
        conn = sqlite3.connect(str(DB_PATH))
        now = __import__('datetime').datetime.utcnow().isoformat()
        conn.execute("""
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
        conn.execute("DELETE FROM ccass_holdings WHERE stock_code=? AND trade_date=?", 
                     (data["stock_code"], data["trade_date"]))
        for h in data.get("holdings", []):
            conn.execute("""
                INSERT INTO ccass_holdings
                (stock_code, trade_date, participant_id, participant_name, shares, pct_of_issued)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (data["stock_code"], data["trade_date"],
                 h.get("participant_id"), h.get("participant_name"),
                 h.get("shares"), h.get("pct_of_issued")))
        conn.commit()
        conn.close()
        success += 1
    except Exception as e:
        fail += 1
    
    if i % 20 == 0:
        print(f"  {i}/{len(missing)} — {success} ok, {fail} fail")

print(f"\nDone: {success} ok, {fail} fail")
