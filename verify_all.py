"""Comprehensive CCASS data verification — DB + ccass.json.
Run before deploy. Exits 0=PASS, 1=FAIL.
"""
import json, sys, math, sqlite3
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent
DB_PATH = ROOT / "ccass" / "holdings.db"
JSON_PATH = ROOT / "ccass.json"

def verify_all():
    errors = []
    warnings = []
    
    print("="*50)
    print("CCASS DATA VERIFICATION")
    print("="*50)
    
    # ─── 1. ccass.json format ───
    print("\n── 1. ccass.json ──")
    try:
        data = json.loads(JSON_PATH.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"  ❌ Invalid JSON: {e}")
        return 1
    
    stocks = data.get("stocks", [])
    n_json = len(stocks)
    print(f"  Stocks: {n_json} | Updated: {data.get('updated')}")
    
    # NaN check
    nan_count = sum(1 for s in stocks for v in s.values() if isinstance(v, float) and math.isnan(v))
    if nan_count:
        errors.append(f"NaN in ccass.json: {nan_count}")
    else:
        print(f"  ✓ No NaN")
    
    # Required fields
    for field in ["c","n","tp","t5","t10","np"]:
        missing = sum(1 for s in stocks if s.get(field) is None)
        if missing > 0:
            errors.append(f"Missing {field}: {missing} stocks")
    if not any("Missing" in e for e in errors):
        print(f"  ✓ All required fields present")
    
    # Coverage
    for field in ["d5","yo","lp","py","py_pct","mc"]:
        cnt = sum(1 for s in stocks if s.get(field) is not None)
        pct = round(cnt/n_json*100,1)
        status = "✓" if pct > 50 else ("⚠" if pct > 0 else "✗")
        print(f"  {status} {field}: {cnt}/{n_json} ({pct}%)")
    
    # Excluded stocks
    excluded = ["029","04621"]
    for pfx in excluded:
        found = [s["c"] for s in stocks if s.get("c","").startswith(pfx)]
        if found:
            errors.append(f"Excluded {pfx}xx present: {found}")
    rmb = [s["c"] for s in stocks if s.get("c","").startswith("8")]
    if rmb:
        errors.append(f"RMB counters present: {len(rmb)}")
    if not any("Excluded" in e or "RMB" in e for e in errors):
        print(f"  ✓ No excluded stocks")
    
    # ─── 2. DB integrity ───
    print("\n── 2. Database ──")
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    publish_where = """
        trade_date = ?
        AND validation_failed = 0
        AND stock_code NOT LIKE '029%'
        AND stock_code NOT LIKE '04621'
        AND stock_code NOT LIKE '8%'
    """
    
    # Per-date completeness
    print(f"  Per-date stock counts:")
    cur.execute("""
        SELECT trade_date, COUNT(*) as n,
               COUNT(CASE WHEN total_pct IS NULL THEN 1 END) as null_pct,
               COUNT(CASE WHEN adj_hhi IS NOT NULL AND adj_hhi != 0 THEN 1 END) as with_hhi
        FROM ccass_daily
        GROUP BY trade_date ORDER BY trade_date
    """)
    dates = []
    for r in cur.fetchall():
        dates.append(r[0])
        status = "✓" if r[2] < 10 else "⚠"
        print(f"    {r[0]}: {r[1]} stocks | null_pct={r[2]} | with_hhi={r[3]} {status}")
    
    db_json = dates[-1] if dates else "N/A"
    print(f"  Latest DB date: {db_json}")

    # Stock count consistency  
    cur.execute(f"SELECT COUNT(DISTINCT stock_code) FROM ccass_daily WHERE {publish_where}", (db_json,))
    db_count = cur.fetchone()[0]
    diff = abs(db_count - n_json)
    is_partial = (coverage_pct := data.get("coverage_pct")) is not None and coverage_pct < 100
    if diff > 50 and not is_partial:
        errors.append(f"DB vs JSON stock mismatch: DB={db_count}, JSON={n_json} (diff={diff})")
    elif diff > 50:
        warnings.append(f"DB vs JSON stock mismatch on partial publish: DB={db_count}, JSON={n_json} (diff={diff})")
        print(f"  ⚠ DB vs JSON: {db_count} vs {n_json} (Δ={diff})")
    else:
        print(f"  ✓ DB vs JSON: {db_count} vs {n_json} (Δ={diff})")
    
    # top5 > top10 sanity
    cur.execute("""
        SELECT COUNT(*) FROM ccass_daily
        WHERE top5_pct IS NOT NULL AND top10_pct IS NOT NULL
        AND top5_pct > top10_pct AND trade_date = ?
    """, (db_json,))
    t5_gt_t10 = cur.fetchone()[0]
    if t5_gt_t10 > 0:
        errors.append(f"top5 > top10 violations: {t5_gt_t10}")
    else:
        print(f"  ✓ top5 ≤ top10 sanity check")
    
    # Holdings consistency
    cur.execute("""
        SELECT COUNT(*), ROUND(AVG(mismatch_pct), 2)
        FROM (
            SELECT ABS(d.total_shares - SUM(h.shares)) * 100.0 / NULLIF(d.total_shares, 0) as mismatch_pct
            FROM ccass_daily d
            JOIN ccass_holdings h ON d.stock_code = h.stock_code AND d.trade_date = h.trade_date
            WHERE d.total_shares > 0 AND d.trade_date = ? AND d.validation_failed = 0
              AND d.stock_code NOT LIKE '029%'
              AND d.stock_code NOT LIKE '04621'
              AND d.stock_code NOT LIKE '8%'
            GROUP BY d.stock_code, d.trade_date
        )
    """, (db_json,))
    h_r = cur.fetchone()
    if h_r[0]:
        print(f"  Holdings mismatch: {h_r[0]} stocks, avg={h_r[1]}%")
        if h_r[1] and h_r[1] > 5:
            if is_partial:
                warnings.append(f"High holdings mismatch on partial publish: avg={h_r[1]}%")
            else:
                errors.append(f"High holdings mismatch: avg={h_r[1]}%")
    else:
        print(f"  ⚠ No holdings data for {db_json}")
    
    # ─── 3. Trends coverage ───
    print("\n── 3. Trends ──")
    cur.execute("""
        SELECT trade_date, COUNT(*) FROM ccass_trends 
        GROUP BY trade_date ORDER BY trade_date
    """)
    trend_dates = {}
    for r in cur.fetchall():
        trend_dates[r[0]] = r[1]
    
    missing_trends = [d for d in dates if d not in trend_dates]
    if missing_trends:
        warnings.append(f"Missing trends: {missing_trends}")
    else:
        print(f"  ✓ All dates have trends")
    
    for d, n in sorted(trend_dates.items(), reverse=True)[:5]:
        print(f"    {d}: {n} stocks")
    
    db.close()
    
    # ─── Summary ───
    print("\n" + "="*50)
    if errors:
        print(f"❌ FAIL — {len(errors)} errors, {len(warnings)} warnings")
        for e in errors:
            print(f"  ❌ {e}")
    else:
        print(f"✅ PASS — JSON={n_json}, DB latest={db_json}")
    
    for w in warnings:
        print(f"  ⚠ {w}")
    
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(verify_all())
