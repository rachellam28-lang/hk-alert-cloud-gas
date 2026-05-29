"""Fetch daily stock prices from yfinance → stock_prices table.

Usage:
  python scripts/fetch_stock_prices_db.py              # incremental (last 90 days)
  python scripts/fetch_stock_prices_db.py --full        # full history 2024-01-01 → today
  python scripts/fetch_stock_prices_db.py --date 2026-05-28  # single date
"""
import sqlite3, time, argparse
from pathlib import Path
from datetime import date, timedelta

PROJECT = Path(__file__).parent.parent
DB = PROJECT / "ccass.db"

BATCH = 100  # yfinance batch download size

def get_codes():
    db = sqlite3.connect(str(DB))
    codes = sorted(r[0] for r in db.execute(
        "SELECT stock_code FROM stock_universe WHERE is_active=1 ORDER BY stock_code"
    ))
    db.close()
    return codes

def to_sym(code):
    return f"{int(code):04d}.HK"

def get_existing_dates(conn, code):
    """Return set of dates already in stock_prices for this code."""
    rows = conn.execute(
        "SELECT price_date FROM stock_prices WHERE stock_code=?",
        (code,)
    ).fetchall()
    return {r[0] for r in rows}

def fetch_and_store(codes, start_date, end_date):
    import yfinance as yf
    
    conn = sqlite3.connect(str(DB))
    total_new = 0
    total_skip = 0
    
    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        syms = [to_sym(c) for c in batch]
        
        # Check which dates are already stored
        # For efficiency, just check the first stock's coverage
        existing = get_existing_dates(conn, batch[0])
        if len(existing) > 0 and start_date:
            # If we have recent data, only fetch missing
            latest = max(existing)
            fetch_start = max(start_date, date.fromisoformat(latest) + timedelta(days=1))
        else:
            fetch_start = start_date
        
        if fetch_start > end_date:
            total_skip += len(batch)
            continue
        
        try:
            hist = yf.download(
                syms,
                start=fetch_start.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
                group_by='ticker',
            )
            
            if hist.empty:
                total_skip += len(batch)
                continue
            
            for c, sym in zip(batch, syms):
                try:
                    if sym not in hist.columns.levels[0]:
                        continue
                    
                    df = hist[sym]
                    if df.empty:
                        continue
                    
                    new_rows = 0
                    for idx, row in df.iterrows():
                        dt = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10]
                        
                        # Skip if already exists
                        conn.execute(
                            "INSERT OR IGNORE INTO stock_prices "
                            "(stock_code, price_date, open, high, low, close, volume, source) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 'yfinance')",
                            (
                                c,
                                dt,
                                round(float(row['Open']), 4) if pd.notna(row.get('Open')) else None,
                                round(float(row['High']), 4) if pd.notna(row.get('High')) else None,
                                round(float(row['Low']), 4) if pd.notna(row.get('Low')) else None,
                                round(float(row['Close']), 4) if pd.notna(row.get('Close')) else None,
                                int(row['Volume']) if pd.notna(row.get('Volume')) else None,
                            ),
                        )
                        if conn.total_changes > 0:
                            new_rows += 1
                    
                    total_new += new_rows
                    
                except Exception as e:
                    print(f"  {c}: ERROR {e}")
            
            conn.commit()
            
            if (i // BATCH) % 10 == 0:
                print(f"  {min(i + BATCH, len(codes))}/{len(codes)} — new rows: {total_new}")
            
        except Exception as e:
            print(f"  Batch {i}: {e}")
        
        time.sleep(1)
    
    conn.close()
    return total_new

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Full history from 2024-01-01")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    args = parser.parse_args()
    
    codes = get_codes()
    print(f"Total stocks: {len(codes)}")
    
    if args.date:
        d = date.fromisoformat(args.date)
        start_date = d
        end_date = d
        print(f"Fetching single date: {d}")
    elif args.full:
        start_date = date(2024, 1, 1)
        end_date = date.today()
        print(f"Full history: {start_date} → {end_date}")
    else:
        # Incremental: last 90 days
        end_date = date.today()
        start_date = end_date - timedelta(days=90)
        print(f"Incremental: {start_date} → {end_date}")
    
    import pandas as pd  # needed for pd.notna
    
    new_rows = fetch_and_store(codes, start_date, end_date)
    print(f"\nDone. New rows added: {new_rows}")

if __name__ == "__main__":
    main()
