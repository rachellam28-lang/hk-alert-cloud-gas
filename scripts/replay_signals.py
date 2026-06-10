"""
replay_signals.py — Pull historical HK stock daily kline via akshare,
replay signal detection logic, compute forward returns, output summary.

Monolithic: one script, one run, one output file.
"""
import json
import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from collections import defaultdict

warnings.filterwarnings('ignore')
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
OUTCOMES_PATH = os.path.join(DATA_DIR, 'outcomes.json')
PRICE_HISTORY_PATH = os.path.join(DATA_DIR, 'price_history.json')
REPLAY_OUTPUT = os.path.join(DATA_DIR, 'replay_results.json')

# Market cap buckets
MC_BUCKETS = [
    (0, 20, 'nano'),
    (20, 100, 'micro'),
    (100, 500, 'small'),
    (500, 2000, 'mid'),
    (2000, float('inf'), 'large'),
]

LOOKBACK_YEARS = 2
CHUNK_SIZE = 50
DELAY_BETWEEN = 0.3  # seconds between akshare calls

def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_signal_codes():
    """Get unique stock codes from outcomes.json."""
    outcomes = load_json(OUTCOMES_PATH)
    if not outcomes:
        return []
    codes = list(set(e['code'] for e in outcomes['events']))
    codes.sort()
    return codes

def pull_price_history(codes, force_refresh=False):
    """Pull 2-year daily kline for given codes via yfinance."""
    import yfinance as yf
    
    existing = load_json(PRICE_HISTORY_PATH, {})
    if not force_refresh:
        missing = [c for c in codes if c not in existing or not existing[c]]
        if not missing:
            print(f"All {len(codes)} stocks already cached")
            return existing
        codes = missing
    
    total = len(codes)
    pulled = 0
    failed = 0
    
    for i, code in enumerate(codes):
        try:
            # yfinance HK ticker format
            ticker = yf.Ticker(f"{code}.HK")
            df = ticker.history(period=f"{LOOKBACK_YEARS}y")
            
            if df is None or df.empty:
                # Try with leading zeros stripped
                ticker2 = yf.Ticker(f"{int(code)}.HK")
                df = ticker2.history(period=f"{LOOKBACK_YEARS}y")
            
            if df is None or df.empty:
                failed += 1
                continue
            
            records = []
            for idx, row in df.iterrows():
                records.append({
                    'date': str(idx)[:10],
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': float(row['Volume']),
                })
            
            existing[code] = records
            pulled += 1
            
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i+1}/{total} stocks pulled ({pulled} ok, {failed} fail)")
                save_json(PRICE_HISTORY_PATH, existing)
            
            time.sleep(0.15)  # rate limit
            
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  Failed {code}: {e}")
            time.sleep(1)
    
    save_json(PRICE_HISTORY_PATH, existing)
    print(f"Done: {pulled} pulled, {failed} failed, total cached: {len(existing)}")
    return existing

def detect_poc_signal(code, prices, today_idx):
    """
    Replicate POC signal detection.
    Detect if today's close crosses above a POC level.
    POC = highest volume price over a given lookback period.
    Simplified: detect if close > highest close of last 120/250/750 days.
    """
    if today_idx < 120:
        return None
    
    today = prices[today_idx]
    close = today['close']
    
    signals = []
    # 半年POC proxy: close > max close of last 120 days
    if today_idx >= 120:
        max_120 = max(p['high'] for p in prices[today_idx-120:today_idx])
        if close > max_120:
            signals.append(('半年POC', close, max_120))
    
    # 12个月POC proxy: close > max close of last 250 days  
    if today_idx >= 250:
        max_250 = max(p['high'] for p in prices[today_idx-250:today_idx])
        if close > max_250:
            signals.append(('12個月POC', close, max_250))
    
    # 3年POC proxy: close > max close of last 750 days
    if today_idx >= 750:
        max_750 = max(p['high'] for p in prices[today_idx-750:today_idx])
        if close > max_750:
            signals.append(('3年POC', close, max_750))
    
    return signals

def detect_year_open_breakout(prices, today_idx):
    """
    Detect if today's high > year-start open price.
    Year open = first trading day's open of the current year.
    """
    if today_idx < 5:
        return None
    
    today = prices[today_idx]
    today_date = today['date'][:4]
    
    # Find year-open: first trading day of the year
    year_start = None
    for p in prices[:today_idx+1]:
        if p['date'][:4] == today_date and p['open'] > 0:
            year_start = p['open']
            break
    
    if year_start is None:
        return None
    
    if today['high'] > year_start:
        pct = (today['high'] / year_start - 1) * 100
        return [('年開突破', today['high'], year_start, pct)]
    
    return None

def detect_ipo_breakout(prices, today_idx):
    """IPO首日高/開突破."""
    if today_idx < 2:
        return None
    
    today = prices[today_idx]
    
    # Simplified: if first 30 days have valid data, check if it's an IPO
    # Look for a price jump from near-zero
    signals = []
    for lookback in [5, 20]:
        if today_idx < lookback:
            continue
        window = prices[today_idx-lookback:today_idx]
        closes = [p['close'] for p in window if p['close'] > 0.001]
        if len(closes) < lookback * 0.8:
            continue
        avg = sum(closes) / len(closes)
        if today['close'] > avg * 1.1:
            signals.append((f'{lookback}日新高', today['close'], avg))
    
    return signals if signals else None

def detect_fvg(prices, today_idx):
    """
    Fair Value Gap detection.
    FVG = gap between candle 1 low and candle 3 high (or reverse).
    Three-candle pattern where middle candle's range is completely
    contained within the gap between candle 1 and candle 3.
    """
    if today_idx < 3:
        return None
    
    c1, c2, c3 = prices[today_idx-3], prices[today_idx-2], prices[today_idx-1]
    
    signals = []
    # Bullish FVG: c3.low > c1.high (gap up)
    if c3['low'] > c1['high']:
        fvg_pct = (c3['low'] - c1['high']) / c1['high'] * 100
        if fvg_pct > 1.0:
            signals.append(('向上FVG', fvg_pct))
    
    # Bearish FVG: c3.high < c1.low (gap down)
    if c3['high'] < c1['low']:
        fvg_pct = (c1['low'] - c3['high']) / c1['low'] * 100
        if fvg_pct > 1.0:
            signals.append(('向下FVG', fvg_pct))
    
    return signals if signals else None

def replay_all_signals(price_history):
    """Replay signal detection on historical prices.
    KEY FIX: Only record FIRST breakthrough, not every day above the level."""
    all_signals = []
    skipped = 0
    
    for code, prices in price_history.items():
        if not prices or len(prices) < 30:
            skipped += 1
            continue
        
        # Sort by date
        prices.sort(key=lambda p: p['date'])
        
        # Track state: has this stock already broken year_open / POC this year?
        yo_broken_this_year = {}
        poc_broken = {}  # (period_days) -> True once broken
        
        for idx in range(30, len(prices)):
            date = prices[idx]['date']
            close = prices[idx]['close']
            year = date[:4]
            
            # ---- POC signals (first break only) ----
            for period_days, label in [(120, '半年POC'), (250, '12個月POC'), (750, '3年POC')]:
                if idx >= period_days and (code, period_days) not in poc_broken:
                    prev_high = max(p['high'] for p in prices[idx-period_days:idx])
                    prev_close = prices[idx-1]['close']
                    if prev_close <= prev_high and close > prev_high:  # FIRST break
                        all_signals.append({
                            'code': code,
                            'date': date,
                            'category': 'poc',
                            'signal_type': label,
                            'entry_price': close,
                            'poc_level': prev_high,
                            'break_value': close,
                        })
                        poc_broken[(code, period_days)] = True
            
            # ---- Year open (first break only) ----
            # Find year-open
            year_start = None
            for p in prices[:idx+1]:
                if p['date'][:4] == year and p['open'] > 0:
                    year_start = p['open']
                    break
            
            if year_start and (code, year) not in yo_broken_this_year:
                prev_high = prices[idx-1]['high']
                today_high = prices[idx]['high']
                if prev_high <= year_start and today_high > year_start:  # FIRST break
                    pct = (today_high / year_start - 1) * 100
                    all_signals.append({
                        'code': code,
                        'date': date,
                        'category': 'year_open',
                        'signal_type': '年開突破',
                        'entry_price': close,
                        'break_pct': round(pct, 2),
                    })
                    yo_broken_this_year[(code, year)] = True
            
            # ---- FVG (daily pattern, inherently one-off) ----
            if idx >= 3:
                c1, c2, c3 = prices[idx-3], prices[idx-2], prices[idx-1]
                # Bullish FVG
                if c3['low'] > c1['high']:
                    fvg_pct = (c3['low'] - c1['high']) / c1['high'] * 100
                    if fvg_pct > 1.0:
                        all_signals.append({
                            'code': code,
                            'date': date,
                            'category': 'fvg_gap',
                            'signal_type': '向上FVG',
                            'entry_price': close,
                            'fvg_pct': round(fvg_pct, 2),
                        })
                # Bearish FVG
                if c3['high'] < c1['low']:
                    fvg_pct = (c1['low'] - c3['high']) / c1['low'] * 100
                    if fvg_pct > 1.0:
                        all_signals.append({
                            'code': code,
                            'date': date,
                            'category': 'fvg_gap',
                            'signal_type': '向下FVG',
                            'entry_price': close,
                            'fvg_pct': round(fvg_pct, 2),
                        })
    
    print(f"Replayed: {len(all_signals)} signals from {len(price_history)-skipped} stocks ({skipped} skipped <30 bars)")
    return all_signals

def compute_forward_returns(signals, price_history):
    """Compute 5d/20d/60d forward returns for each signal."""
    results = []
    no_data = 0
    
    for sig in signals:
        code = sig['code']
        date = sig['date']
        entry = sig['entry_price']
        
        prices = price_history.get(code, [])
        if not prices:
            no_data += 1
            continue
        
        # Find the index of signal date
        sig_idx = None
        for i, p in enumerate(prices):
            if p['date'] == date:
                sig_idx = i
                break
        
        if sig_idx is None:
            no_data += 1
            continue
        
        # Compute forward returns
        def fwd_return(days):
            target_idx = sig_idx + days
            if target_idx >= len(prices):
                return None, None
            target_close = prices[target_idx]['close']
            if entry <= 0.001 or target_close <= 0.001:
                return None, None
            return round((target_close / entry - 1) * 100, 2), target_close
        
        fwd_5d, _ = fwd_return(5)
        fwd_20d, close_20d = fwd_return(20)
        fwd_60d, _ = fwd_return(60)
        
        # Max gain / max drawdown in 20d window
        max_gain = 0
        max_dd = 0
        for offset in range(1, 21):
            if sig_idx + offset >= len(prices):
                break
            p = prices[sig_idx + offset]['close']
            if entry > 0.001:
                ret = (p / entry - 1) * 100
                max_gain = max(max_gain, ret)
                max_dd = min(max_dd, ret)
        
        results.append({
            **sig,
            'fwd_5d': fwd_5d,
            'fwd_20d': fwd_20d,
            'fwd_60d': fwd_60d,
            'max_gain_20d': round(max_gain, 2),
            'max_drawdown_20d': round(max_dd, 2),
            'benchmark_fwd_20d': None,  # computed later
        })
    
    print(f"Forward returns computed: {len(results)} signals ({no_data} no data)")
    return results

def compute_benchmarks(results, price_history):
    """Compute benchmark (median return of all stocks) for each date."""
    # Build date → all stock returns map
    date_returns = defaultdict(list)
    
    for code, prices in price_history.items():
        if not prices:
            continue
        for idx in range(len(prices) - 20):
            date = prices[idx]['date']
            entry = prices[idx]['close']
            exit_price = prices[idx + 20]['close'] if idx + 20 < len(prices) else entry
            if entry > 0.001 and exit_price > 0.001:
                ret = (exit_price / entry - 1) * 100
                date_returns[date].append(ret)
    
    # Compute median per date
    date_median = {}
    for date, returns in date_returns.items():
        if returns:
            returns.sort()
            date_median[date] = returns[len(returns) // 2]
    
    # Assign to signals
    for r in results:
        r['benchmark_fwd_20d'] = round(date_median.get(r['date'], 0), 2)
    
    return results

def summarize(results):
    """Produce evaluation summary by signal_type × mc_bucket."""
    groups = defaultdict(list)
    
    for r in results:
        key = f"{r['category']}|{r['signal_type']}"
        groups[key].append(r)
    
    print("\n=== Signal Backtest Summary ===")
    print(f"Total signals: {len(results)}")
    print(f"Date range: {results[0]['date'] if results else 'N/A'} to {results[-1]['date'] if results else 'N/A'}")
    print()
    
    # Overall stats
    all_fwd20 = [r['fwd_20d'] for r in results if r['fwd_20d'] is not None]
    all_bench = [r['benchmark_fwd_20d'] for r in results if r['benchmark_fwd_20d'] is not None]
    
    if all_fwd20:
        all_fwd20.sort()
        all_bench.sort()
        median_ret = all_fwd20[len(all_fwd20)//2]
        median_bench = all_bench[len(all_bench)//2] if all_bench else 0
        win_rate = sum(1 for r in results if r['fwd_20d'] is not None and r['benchmark_fwd_20d'] is not None and r['fwd_20d'] > r['benchmark_fwd_20d'])
        total_valid = sum(1 for r in results if r['fwd_20d'] is not None and r['benchmark_fwd_20d'] is not None)
        
        print(f"Overall (n={total_valid}):")
        print(f"  Median 20d return: {median_ret:+.2f}%")
        print(f"  Median benchmark: {median_bench:+.2f}%")
        print(f"  Excess vs benchmark: {median_ret - median_bench:+.2f}%")
        print(f"  Win rate (>benchmark): {win_rate}/{total_valid} ({win_rate/total_valid*100:.1f}%)" if total_valid > 0 else "")
    
    print(f"\nBy signal type:")
    for key in sorted(groups.keys()):
        group = groups[key]
        fwd20 = [r['fwd_20d'] for r in group if r['fwd_20d'] is not None]
        bench = [r['benchmark_fwd_20d'] for r in group if r['benchmark_fwd_20d'] is not None]
        dd = [r['max_drawdown_20d'] for r in group if r['max_drawdown_20d'] is not None]
        
        if len(fwd20) < 10:
            print(f"  {key}: n={len(group)} (insufficient)")
            continue
        
        fwd20.sort()
        bench.sort()
        dd.sort()
        
        median_ret = fwd20[len(fwd20)//2]
        median_bench = bench[len(bench)//2] if bench else 0
        median_dd = dd[len(dd)//2] if dd else 0
        excess = median_ret - median_bench
        
        wins = sum(1 for r in group if r['fwd_20d'] is not None and r['benchmark_fwd_20d'] is not None and r['fwd_20d'] > r['benchmark_fwd_20d'])
        valid = sum(1 for r in group if r['fwd_20d'] is not None and r['benchmark_fwd_20d'] is not None)
        
        print(f"  {key}: n={len(group)}, median_20d={median_ret:+.1f}%, excess={excess:+.1f}%, maxDD_median={median_dd:+.1f}%, win_rate={wins}/{valid}" if valid > 0 else f"  {key}: n={len(group)}")

    return groups

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    
    if mode == 'pull':
        # Only pull price data, don't replay
        codes = get_signal_codes()
        print(f"Pulling price history for {len(codes)} stocks...")
        pull_price_history(codes)
        
    elif mode == 'replay':
        # Replay on cached price data
        price_history = load_json(PRICE_HISTORY_PATH, {})
        if not price_history:
            print("No price history. Run --pull first: python replay_signals.py pull")
            sys.exit(1)
        
        print(f"Replaying signals on {len(price_history)} stocks...")
        signals = replay_all_signals(price_history)
        results = compute_forward_returns(signals, price_history)
        results = compute_benchmarks(results, price_history)
        
        save_json(REPLAY_OUTPUT, {"signals": results, "updated_at": datetime.now().isoformat()})
        summarize(results)
        
    elif mode == 'summary':
        results = load_json(REPLAY_OUTPUT, {})
        if results and results.get('signals'):
            summarize(results['signals'])
        else:
            print("No replay results. Run --replay first")
    
    elif mode == 'full':
        # Pull + replay + summarize
        codes = get_signal_codes()
        print(f"=== Step 1: Pull price history for {len(codes)} stocks ===")
        price_history = pull_price_history(codes)
        
        print(f"\n=== Step 2: Replay signal detection ===")
        signals = replay_all_signals(price_history)
        
        print(f"\n=== Step 3: Compute forward returns ===")
        results = compute_forward_returns(signals, price_history)
        
        print(f"\n=== Step 4: Compute benchmarks ===")
        results = compute_benchmarks(results, price_history)
        
        save_json(REPLAY_OUTPUT, {"signals": results, "updated_at": datetime.now().isoformat()})
        
        print(f"\n=== Step 5: Summary ===")
        summarize(results)
        
    else:
        print(f"Usage: python replay_signals.py [pull|replay|summary|full]")
