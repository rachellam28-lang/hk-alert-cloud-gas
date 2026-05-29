"""Fetch year-open + latest price for all CCASS stocks via yfinance.
Stores in data/stock_prices.json for dashboard.
HK stock code "00001" → yfinance symbol "0001.HK" (drop leading zero).
"""
import json, sqlite3, sys, time
from pathlib import Path
from datetime import date

PROJECT = Path(__file__).parent.parent
DB = PROJECT / "ccass.db"
OUT = PROJECT / "data" / "stock_prices.json"

def fetch_all():
    # Load stock codes from DB
    db = sqlite3.connect(str(DB))
    codes = sorted(r[0] for r in db.execute(
        "SELECT stock_code FROM stock_universe ORDER BY stock_code"
    ))
    db.close()

    print(f"Total stocks: {len(codes)}")

    # Load existing cache
    cache = {}
    if OUT.exists():
        cache = json.loads(OUT.read_text(encoding='utf-8'))

    # yfinance symbol: strip leading zero → 4-digit
    def to_sym(code):
        return f"{int(code):04d}.HK"

    import yfinance as yf
    BATCH = 50
    new_count = 0
    skip_count = 0
    fail_count = 0

    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        # Filter already-cached (with both yo and lp)
        todo = []
        for c in batch:
            if c in cache and cache[c].get('yo') and cache[c].get('lp'):
                skip_count += 1
                continue
            todo.append(c)

        if not todo:
            continue

        syms = [to_sym(c) for c in todo]

        # Fetch year-open (ytd first day)
        try:
            ytd = yf.download(syms, period='ytd', progress=False, auto_adjust=False)
        except Exception as e:
            print(f"  Batch ytd download failed: {e}")
            fail_count += len(todo)
            continue

        for c, sym in zip(todo, syms):
            try:
                entry = cache.get(c, {})
                # Year-open: first row of ytd
                if sym in ytd.columns.get_level_values(1) if hasattr(ytd.columns, 'get_level_values') else False:
                    col_open = ytd.xs(sym, axis=1, level=1)['Open']
                    if len(col_open) > 0:
                        entry['yo'] = round(float(col_open.iloc[0]), 3)
                        entry['yo_date'] = str(col_open.index[0].date())

                # Latest price
                t = yf.Ticker(sym)
                info = t.fast_info
                if info.last_price:
                    entry['lp'] = round(float(info.last_price), 3)
                    entry['lp_time'] = str(date.today())

                if entry.get('yo') and entry.get('lp'):
                    cache[c] = entry
                    new_count += 1
            except Exception as e:
                fail_count += 1

        if (i // BATCH) % 5 == 0:
            print(f"  {min(i + BATCH, len(codes))}/{len(codes)} — new={new_count}, skip={skip_count}, fail={fail_count}")
        time.sleep(1)  # rate limit

    # Save
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nDone: {new_count} updated, {skip_count} cached, {fail_count} failed → {OUT}")

if __name__ == "__main__":
    fetch_all()
