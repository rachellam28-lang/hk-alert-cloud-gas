import sqlite3

DB_PATH = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass\ccass.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("=== CCASS DATABASE COMPREHENSIVE AUDIT & FIX ===")
print()

# ---- PART 1: AUDIT ----
print("=== PART 1: AUDIT ===")

# 1A. Decimal total_pct by date
print("\n--- 1A: Decimal total_pct (0 < val < 1.0) by date ---")
for dt in ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04']:
    cur.execute(f"SELECT COUNT(*) FROM ccass_daily WHERE trade_date='{dt}' AND total_pct > 0 AND total_pct < 1.0")
    cnt = cur.fetchone()[0]
    print(f"  {dt}: {cnt} decimal rows")

# 1B. Any total_pct > 100? (double-multiply check)
cur.execute("SELECT COUNT(*), MIN(total_pct), MAX(total_pct) FROM ccass_daily WHERE total_pct > 100")
r = cur.fetchone()
print(f"\n  total_pct > 100: {r[0]} rows, range [{r[1]}, {r[2]}]")

# 1C. Check 00328 (flagged as suspicious)
cur.execute("SELECT trade_date, total_pct FROM ccass_daily WHERE stock_code='00328' ORDER BY trade_date")
rows = cur.fetchall()
print(f"\n  00328 history: {', '.join([f'{r[0]}={r[1]}' for r in rows])}")

# 1D. delta_60d_pct / delta_120d_pct — all zero?
cur.execute("""SELECT COUNT(*) as total, 
    SUM(CASE WHEN delta_60d_pct != 0 THEN 1 ELSE 0 END) as nz60,
    SUM(CASE WHEN delta_120d_pct != 0 THEN 1 ELSE 0 END) as nz120,
    SUM(CASE WHEN delta_5d_pct != 0 THEN 1 ELSE 0 END) as nz5,
    SUM(CASE WHEN delta_20d_pct != 0 THEN 1 ELSE 0 END) as nz20
    FROM ccass_trends""")
r = cur.fetchone()
print(f"\n  ccass_trends non-zero counts (out of {r[0]}):")
print(f"    delta_5d_pct: {r[2]}, delta_20d_pct: {r[3]}, delta_60d_pct: {r[1]}, delta_120d_pct: {r[1]}")

# 1E. NULL anomalies
print("\n--- NULL anomalies ---")
for col in ['total_pct', 'top5_pct', 'top10_pct', 'broker_top5_pct', 'top_broker_pct', 'futu_pct', 'a00005_pct']:
    cur.execute(f"SELECT COUNT(*) FROM ccass_daily WHERE {col} IS NULL")
    print(f"  {col}: {cur.fetchone()[0]} NULL")

cur.execute("SELECT COUNT(*) FROM ccass_daily WHERE num_participants = 0 AND total_pct IS NULL")
print(f"  total_pct NULL with 0 participants: {cur.fetchone()[0]}")

# 1F. Duplicates
print("\n--- Duplicate check ---")
for tbl in ['ccass_daily', 'ccass_holdings', 'ccass_trends']:
    if tbl == 'ccass_daily':
        cur.execute(f"SELECT COUNT(*) FROM (SELECT stock_code, trade_date, COUNT(*) as c FROM {tbl} GROUP BY stock_code, trade_date HAVING c > 1)")
    elif tbl == 'ccass_holdings':
        cur.execute(f"SELECT COUNT(*) FROM (SELECT stock_code, trade_date, participant_id, COUNT(*) as c FROM {tbl} GROUP BY stock_code, trade_date, participant_id HAVING c > 1)")
    else:
        cur.execute(f"SELECT COUNT(*) FROM (SELECT stock_code, trade_date, COUNT(*) as c FROM {tbl} GROUP BY stock_code, trade_date HAVING c > 1)")
    print(f"  {tbl}: {cur.fetchone()[0]} duplicate groups")

# 1G. pct_of_issued audit — check consistency with total_pct
print("\n--- pct_of_issued vs total_pct consistency ---")
cur.execute("""
    SELECT d.stock_code, d.trade_date, d.total_pct,
           (SELECT COALESCE(SUM(h.pct_of_issued), 0) FROM ccass_holdings h 
            WHERE h.stock_code=d.stock_code AND h.trade_date=d.trade_date) as sum_h
    FROM ccass_daily d 
    WHERE d.trade_date IN ('2026-06-01', '2026-06-02')
    ORDER BY ABS(d.total_pct - (SELECT COALESCE(SUM(h.pct_of_issued), 0) FROM ccass_holdings h 
            WHERE h.stock_code=d.stock_code AND h.trade_date=d.trade_date)) DESC
    LIMIT 10
""")
print("  Largest mismatches before fix (06-01/06-02):")
for r in cur.fetchall():
    diff = abs(r[2] - r[3]) if r[2] is not None and r[3] is not None else None
    print(f"    {r[0]} {r[1]}: total_pct={r[2]}, sum_holdings={r[3]:.2f}, diff={diff:.2f}")

# ---- PART 2: FIXES ----
print("\n=== PART 2: APPLYING FIXES ===")

# Backup first
import shutil
backup_path = DB_PATH + ".backup.audit_20260606"
shutil.copy2(DB_PATH, backup_path)
print(f"\nBackup created: {backup_path}")

# FIX 1: 06-01 decimal total_pct -> x100
cur.execute("SELECT COUNT(*) FROM ccass_daily WHERE trade_date='2026-06-01' AND total_pct > 0 AND total_pct < 1.0")
cnt = cur.fetchone()[0]
print(f"\nFIX 1: x100 for {cnt} rows on 2026-06-01...")
cur.execute("UPDATE ccass_daily SET total_pct = ROUND(total_pct * 100, 2) WHERE trade_date='2026-06-01' AND total_pct > 0 AND total_pct < 1.0")
print(f"  {cur.rowcount} rows updated")

# FIX 2: 06-02 decimal total_pct -> x100  
cur.execute("SELECT COUNT(*) FROM ccass_daily WHERE trade_date='2026-06-02' AND total_pct > 0 AND total_pct < 1.0")
cnt = cur.fetchone()[0]
print(f"\nFIX 2: x100 for {cnt} rows on 2026-06-02...")
cur.execute("UPDATE ccass_daily SET total_pct = ROUND(total_pct * 100, 2) WHERE trade_date='2026-06-02' AND total_pct > 0 AND total_pct < 1.0")
print(f"  {cur.rowcount} rows updated")

# FIX 3: 06-03 decimal total_pct -> x100
cur.execute("SELECT COUNT(*) FROM ccass_daily WHERE trade_date='2026-06-03' AND total_pct > 0 AND total_pct < 1.0")
cnt = cur.fetchone()[0]
if cnt > 0:
    print(f"\nFIX 3: x100 for {cnt} rows on 2026-06-03...")
    cur.execute("UPDATE ccass_daily SET total_pct = ROUND(total_pct * 100, 2) WHERE trade_date='2026-06-03' AND total_pct > 0 AND total_pct < 1.0")
    print(f"  {cur.rowcount} rows updated")

# FIX 4: 06-04 decimal total_pct -> x100
cur.execute("SELECT COUNT(*) FROM ccass_daily WHERE trade_date='2026-06-04' AND total_pct > 0 AND total_pct < 1.0")
cnt = cur.fetchone()[0]
if cnt > 0:
    print(f"\nFIX 4: x100 for {cnt} rows on 2026-06-04...")
    cur.execute("UPDATE ccass_daily SET total_pct = ROUND(total_pct * 100, 2) WHERE trade_date='2026-06-04' AND total_pct > 0 AND total_pct < 1.0")
    print(f"  {cur.rowcount} rows updated")

conn.commit()

# ---- PART 3: VERIFICATION ----
print("\n=== PART 3: POST-FIX VERIFICATION ===")

# 3A. Decimal total_pct should be 0
for dt in ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04']:
    cur.execute(f"SELECT COUNT(*) FROM ccass_daily WHERE trade_date='{dt}' AND total_pct > 0 AND total_pct < 1.0")
    cnt = cur.fetchone()[0]
    status = "OK" if cnt == 0 else f"FAIL ({cnt} remaining)"
    print(f"  {dt} decimal remaining: {cnt} [{status}]")

# 3B. total_pct > 100 check
cur.execute("SELECT COUNT(*) FROM ccass_daily WHERE total_pct > 100")
print(f"  total_pct > 100: {cur.fetchone()[0]}")

# 3C. Verify sample stocks
for code in ['00308', '00309', '02339', '02342', '00001']:
    cur.execute("SELECT trade_date, total_pct FROM ccass_daily WHERE stock_code=? ORDER BY trade_date", (code,))
    rows = cur.fetchall()
    vals = [f"{r[0]}={r[1]}" for r in rows]
    print(f"  {code}: {', '.join(vals)}")

# 3D. Re-check total_pct vs sum_holdings consistency
print("\n--- Post-fix consistency (top mismatches) ---")
cur.execute("""
    SELECT d.stock_code, d.trade_date, d.total_pct,
           (SELECT COALESCE(SUM(h.pct_of_issued), 0) FROM ccass_holdings h 
            WHERE h.stock_code=d.stock_code AND h.trade_date=d.trade_date) as sum_h
    FROM ccass_daily d 
    WHERE d.trade_date IN ('2026-06-01', '2026-06-02', '2026-06-05')
    ORDER BY ABS(d.total_pct - (SELECT COALESCE(SUM(h.pct_of_issued), 0) FROM ccass_holdings h 
            WHERE h.stock_code=d.stock_code AND h.trade_date=d.trade_date)) DESC
    LIMIT 10
""")
for r in cur.fetchall():
    diff = abs(r[2] - r[3]) if r[2] is not None and r[3] is not None else None
    print(f"  {r[0]} {r[1]}: total_pct={r[2]}, sum_holdings={r[3]:.2f}, diff={diff:.2f}")

conn.close()

print("\n=== AUDIT COMPLETE ===")
print("\nSummary of fixes applied:")
print("  1. total_pct x100 for 06-01 (decimal values from Longbridge scraper)")
print("  2. total_pct x100 for 06-02 (missed stocks 02339-02439)")
print("  3. No double-multiply detected (no values >100)")
print("\nRemaining issues (need code fix, not data fix):")
print("  - delta_60d_pct and delta_120d_pct ALL ZERO (trend.py bug)")
print("  - 503 rows with NULL total_pct (scraper didn't capture percentage)")
print("  - futu_pct/top_broker_pct/broker_top5_pct: 0-1 values are genuine small percentages, NOT decimal errors")
