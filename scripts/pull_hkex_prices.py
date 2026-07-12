"""Pull historical daily kline from Futu OpenD → raw/prices_YYYYMMDD.json"""
import json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

try:
    from futu import *
except ImportError:
    print("Installing futu-api...")
    os.system(f"{sys.executable} -m pip install futu-api -q")
    from futu import *

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, 'raw')
os.makedirs(RAW_DIR, exist_ok=True)
sys.path.insert(0, os.path.join(BASE, "scripts"))
from futu_env import ensure_futu_quote_backend_or_die

def get_hk_stocks(q):
    """Get all HK stock codes from Futu."""
    ret, data = q.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
    if ret != RET_OK:
        print(f"Stock list failed: {data}")
        return []
    # Filter: main board + GEM
    codes = data['code'].tolist()
    print(f"Total HK stocks: {len(codes)}")
    return codes

def pull_history(q, code, start_date='2024-01-01', end_date=None):
    """Pull daily kline for one stock. Returns {date: {open,high,low,close,vol}}."""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    ret, data, _ = q.request_history_kline(
        code, start=start_date, end=end_date,
        ktype=KLType.K_DAY, autype=AuType.QFQ,
        max_count=1000
    )
    if ret != RET_OK:
        return None
    
    result = {}
    for _, row in data.iterrows():
        date = str(row['time_key'])[:10]
        result[date] = {
            'open': round(float(row['open']), 4),
            'high': round(float(row['high']), 4),
            'low': round(float(row['low']), 4),
            'close': round(float(row['close']), 4),
            'vol': int(row['volume']),
        }
    return result

def merge_to_raw(code, hist):
    """Merge pulled history into raw/ files by date."""
    for date, ohlcv in hist.items():
        date_short = date.replace('-', '')
        fpath = os.path.join(RAW_DIR, f'prices_{date_short}.json')
        
        # Load existing or create new
        day_data = {}
        if os.path.exists(fpath):
            with open(fpath) as f:
                day_data = json.load(f)
        
        code5 = str(code).split('.')[-1].zfill(5)
        day_data[code5] = ohlcv
        
        with open(fpath, 'w') as f:
            json.dump(day_data, f, ensure_ascii=False)

# ===== MAIN =====
if __name__ == '__main__':
    start_date = sys.argv[1] if len(sys.argv) > 1 else '2024-01-01'
    max_stocks = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    print(f"Connecting to Futu OpenD...")
    futu_host, futu_port = ensure_futu_quote_backend_or_die(Path(BASE))
    q = OpenQuoteContext(futu_host, futu_port)
    
    codes = get_hk_stocks(q)
    if max_stocks:
        codes = codes[:max_stocks]
    
    print(f"Pulling {len(codes)} stocks from {start_date}...")
    
    pulled, failed, nodata = 0, 0, 0
    t0 = time.time()
    
    for i, code in enumerate(codes):
        hist = pull_history(q, code, start_date)
        if hist is None:
            failed += 1
        elif not hist:
            nodata += 1
        else:
            merge_to_raw(code, hist)
            pulled += 1
        
        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(codes) - i - 1) / rate / 60 if rate > 0 else 0
            print(f"  Progress: {i+1}/{len(codes)} ({pulled} ok, {nodata} empty, {failed} fail) "
                  f"[{rate:.0f}/s, ETA {eta:.0f}m]")
    
    q.close()
    elapsed = time.time() - t0
    print(f"Done: {pulled} pulled, {nodata} empty, {failed} fail in {elapsed/60:.1f}m")
    
    # Count date files
    dates = set()
    for f in os.listdir(RAW_DIR):
        if f.startswith('prices_') and f.endswith('.json'):
            dates.add(f)
    print(f"Date files in raw/: {len(dates)}")
