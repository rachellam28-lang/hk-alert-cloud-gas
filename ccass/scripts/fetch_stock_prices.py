"""Fetch year-open (2024+2026) + latest price for all CCASS stocks via yfinance.
Stores in data/stock_prices.json for dashboard.
HK stock code "00001" → yfinance symbol "0001.HK" (drop leading zero).

Fields per stock:
  yo: 2026 year-open price
  py: 2024 year-open price (2 years ago)
  lp: latest price
  py_pct: (lp - py) / py * 100 — % change from 2024 open
"""
import json, sqlite3, sys, time
from pathlib import Path
from datetime import date

PROJECT = Path(__file__).parent.parent
DB = PROJECT / "ccass.db"
OUT = PROJECT.parent / "data" / "stock_prices.json"

def fetch_all():
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

    def to_sym(code):
        return f"{int(code):04d}.HK"

    import yfinance as yf
    BATCH = 50
    new_count = 0
    skip_count = 0
    fail_count = 0

    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        # Filter already-cached (with yo, py, lp all present)
        todo = []
        for c in batch:
            entry = cache.get(c, {})
            if entry.get('yo') and entry.get('py') and entry.get('lp'):
                skip_count += 1
                continue
            todo.append(c)

        if not todo:
            continue

        syms = [to_sym(c) for c in todo]

        # Fetch 2026 year-open (ytd first day)
        yo_data = {}
        try:
            ytd = yf.download(syms, period='ytd', progress=False, auto_adjust=False)
            for sym in syms:
                try:
                    if sym in ytd.columns.get_level_values(1):
                        col_open = ytd.xs(sym, axis=1, level=1)['Open']
                        if len(col_open) > 0:
                            yo_data[sym] = round(float(col_open.iloc[0]), 3)
                except Exception:
                    pass
        except Exception as e:
            print(f"  Batch ytd failed: {e}")

        # Fetch 2024 year-open (first week of 2024)
        py_data = {}
        try:
            py_hist = yf.download(syms, start='2024-01-01', end='2024-01-10', progress=False, auto_adjust=False)
            for sym in syms:
                try:
                    if sym in py_hist.columns.get_level_values(1):
                        col_open = py_hist.xs(sym, axis=1, level=1)['Open']
                        if len(col_open) > 0:
                            py_data[sym] = round(float(col_open.iloc[0]), 3)
                except Exception:
                    pass
        except Exception as e:
            print(f"  Batch 2024 failed: {e}")

        for c, sym in zip(todo, syms):
            try:
                entry = cache.get(c, {})

                if sym in yo_data:
                    entry['yo'] = yo_data[sym]
                if sym in py_data:
                    entry['py'] = py_data[sym]

                # Latest price
                try:
                    t = yf.Ticker(sym)
                    info = t.fast_info
                    if info.last_price:
                        entry['lp'] = round(float(info.last_price), 3)
                        entry['lp_time'] = str(date.today())
                except Exception:
                    pass

                # Compute py_pct (change from 2024 open)
                if entry.get('lp') and entry.get('py') and entry['py'] > 0:
                    entry['py_pct'] = round((entry['lp'] - entry['py']) / entry['py'] * 100, 2)

                if entry.get('yo') and entry.get('lp'):
                    cache[c] = entry
                    new_count += 1
            except Exception:
                fail_count += 1

        if (i // BATCH) % 5 == 0:
            print(f"  {min(i + BATCH, len(codes))}/{len(codes)} — new={new_count}, skip={skip_count}, fail={fail_count}")
        time.sleep(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nDone: {new_count} updated, {skip_count} cached, {fail_count} failed → {OUT}")

if __name__ == "__main__":
    fetch_all()
