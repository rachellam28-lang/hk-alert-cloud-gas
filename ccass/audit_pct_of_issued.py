import sqlite3

DB_PATH = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass\ccass.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("=== FIXING pct_of_issued OVER-MULTIPLICATION ===")

# Strategy: For 06-01 to 06-04 holdings, if a holding's pct_of_issued was 
# multiplied by ~100x compared to 05-29 (or 06-05), divide it back.
# We compare each (stock_code, participant_id) on 06-01 vs 05-29.
# If ratio is between 50 and 150, it was incorrectly multiplied.

for target_date in ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04']:
    # Find reference date: use 05-29 for 06-01/02, 06-05 for 06-03/04
    ref_date = '2026-05-29' if target_date <= '2026-06-02' else '2026-06-05'
    
    # Count rows where ratio suggests 100x over-multiplication
    cur.execute(f"""
        SELECT COUNT(*) FROM ccass_holdings h1
        JOIN ccass_holdings h2 ON h1.stock_code = h2.stock_code 
            AND h1.participant_id = h2.participant_id
        WHERE h1.trade_date = '{target_date}' 
          AND h2.trade_date = '{ref_date}'
          AND h2.pct_of_issued > 0 
          AND h2.pct_of_issued < 1.0
          AND h1.pct_of_issued / h2.pct_of_issued > 50
          AND h1.pct_of_issued / h2.pct_of_issued < 150
    """)
    cnt = cur.fetchone()[0]
    
    # Also count the approach: rows where pct > 50 AND exists in same stock 
    # where some holdings are in normal range (1-50)
    cur.execute(f"""
        SELECT COUNT(DISTINCT h1.stock_code) FROM ccass_holdings h1
        WHERE h1.trade_date = '{target_date}'
          AND h1.pct_of_issued > 50
          AND EXISTS (
              SELECT 1 FROM ccass_holdings h2 
              WHERE h2.stock_code = h1.stock_code 
                AND h2.trade_date = '{target_date}'
                AND h2.pct_of_issued > 1.0 AND h2.pct_of_issued < 50
          )
    """)
    stocks_with_overmult = cur.fetchone()[0]
    
    # Count affected holdings
    cur.execute(f"""
        SELECT COUNT(*) FROM ccass_holdings h1
        WHERE h1.trade_date = '{target_date}'
          AND h1.pct_of_issued > 50
          AND EXISTS (
              SELECT 1 FROM ccass_holdings h2 
              WHERE h2.stock_code = h1.stock_code 
                AND h2.trade_date = '{target_date}'
                AND h2.pct_of_issued > 1.0 AND h2.pct_of_issued < 50
          )
    """)
    affected_rows = cur.fetchone()[0]
    
    print(f"\n{target_date} (ref={ref_date}):")
    print(f"  Ratio-based overmult: {cnt}")
    print(f"  Stocks with mixed pct ranges (>50 AND 1-50): {stocks_with_overmult}")
    print(f"  Affected holdings (pct>50 in mixed stocks): {affected_rows}")

# Let me check a specific case more carefully
print("\n=== Detailed check: 00858 holdings that were over-multiplied ===")
cur.execute("""
    SELECT h1.participant_id, h1.pct_of_issued as pct_0601, 
           h2.pct_of_issued as pct_0529,
           h1.pct_of_issued / h2.pct_of_issued as ratio
    FROM ccass_holdings h1
    JOIN ccass_holdings h2 ON h1.stock_code = h2.stock_code 
        AND h1.participant_id = h2.participant_id
    WHERE h1.stock_code = '00858' 
      AND h1.trade_date = '2026-06-01' 
      AND h2.trade_date = '2026-05-29'
      AND h1.pct_of_issued > 50
    ORDER BY h1.pct_of_issued DESC
    LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r[0]}: 06-01={r[1]:.2f} 05-29={r[2]:.4f} ratio={r[3]:.1f}x")

# Also check: any genuine holdings with pct > 50 (not over-multiplied)?
print("\n=== Genuine large holders (>50%) on normal dates ===")
cur.execute("""
    SELECT stock_code, participant_id, pct_of_issued 
    FROM ccass_holdings 
    WHERE trade_date = '2026-05-29' AND pct_of_issued > 50
    ORDER BY pct_of_issued DESC LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r[0]} {r[1]}: {r[2]:.2f}%")

conn.close()
