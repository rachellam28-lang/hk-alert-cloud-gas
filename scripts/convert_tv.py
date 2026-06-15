"""TradingView export → raw/prices_YYYYMMDD.json converter.

Features:
  1. Timeframe detection: flags wrong-interval exports (4H/1W instead of 1D)
  2. Coverage report: missing codes, date ranges per file
  3. Sanity check: TV vs git raw/ overlap price comparison

Usage:
  python scripts/convert_tv.py ~/tv_exports/
"""

import csv, json, os, sys, re, shutil
from datetime import datetime, timezone, timedelta
from collections import defaultdict

HKT = timezone(timedelta(hours=8))

def parse_tv_time(val):
    """Unix timestamp (seconds/ms) or ISO → UTC datetime."""
    try:
        ts = float(val)
        if ts > 1e9:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    for fmt in ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S']:
        try:
            return datetime.strptime(str(val)[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None

def detect_wrong_timeframe(timestamps):
    """Check if consecutive timestamps are ~1 day apart (daily bars).
    Returns list of warnings."""
    if len(timestamps) < 5:
        return []
    gaps = []
    for i in range(1, min(len(timestamps), 20)):
        gap_sec = (timestamps[i] - timestamps[i-1]).total_seconds()
        gaps.append(gap_sec)
    
    # Median gap should be ~86400 (1 day)
    gaps.sort()
    med = gaps[len(gaps)//2]
    
    if med < 14400:  # < 4 hours
        return [f"⚠ TIMEFRAME: median bar gap {med/3600:.0f}h — looks like intraday (4H/1H), NOT daily!"]
    elif med < 64800:  # < 18 hours (1D bars can have gaps due to holidays)
        return [f"⚠ TIMEFRAME: median gap {med/3600:.0f}h — could be intraday or sparse"]
    elif med > 120000:  # > 33 hours
        return [f"⚠ TIMEFRAME: median gap {med/3600:.0f}h — looks like weekly or higher, NOT daily!"]
    return []

def convert_exports(export_dir, raw_dir, export_codes):
    """Convert TV CSV → raw/prices_YYYYMMDD.json. Returns coverage stats."""
    day_buckets = defaultdict(dict)
    stats = {
        'files': 0, 'rows': 0, 'skipped': 0, 'bad_date': 0,
        'processed_codes': set(), 'wrong_timeframe': [],
        'per_code_dates': {},  # code5 → (first_date, last_date)
    }
    
    for fname in sorted(os.listdir(export_dir)):
        if not fname.endswith('.csv'):
            continue
        
        code_match = re.match(r'(\d{4,5})', fname)
        if not code_match:
            continue
        code5 = code_match.group(1).zfill(5)
        
        fpath = os.path.join(export_dir, fname)
        stats['files'] += 1
        stats['processed_codes'].add(code5)
        
        timestamps = []
        file_rows = 0
        first_date, last_date = None, None
        
        with open(fpath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = parse_tv_time(row.get('time', ''))
                if dt is None:
                    stats['bad_date'] += 1
                    continue
                timestamps.append(dt)
                stats['rows'] += 1
                file_rows += 1
                
                hkt_date = dt.astimezone(HKT).strftime('%Y-%m-%d')
                date_short = hkt_date.replace('-', '')
                if first_date is None:
                    first_date = hkt_date
                last_date = hkt_date
                
                try:
                    ohlcv = {
                        'open': round(float(row.get('open', 0)), 4),
                        'high': round(float(row.get('high', 0)), 4),
                        'low': round(float(row.get('low', 0)), 4),
                        'close': round(float(row.get('close', 0)), 4),
                        'vol': int(float(row.get('Volume', row.get('volume', 0)))),
                    }
                except (ValueError, TypeError):
                    stats['skipped'] += 1
                    continue
                
                if ohlcv['open'] == 0 and ohlcv['high'] == 0 and \
                   ohlcv['low'] == 0 and ohlcv['close'] == 0:
                    stats['skipped'] += 1
                    continue
                
                day_buckets[date_short][code5] = ohlcv
        
        # Timeframe check
        tf_warnings = detect_wrong_timeframe(timestamps)
        if tf_warnings:
            stats['wrong_timeframe'].append((code5, tf_warnings))
        
        stats['per_code_dates'][code5] = (first_date, last_date, file_rows)
    
    # Write raw/ files (merge with existing)
    written, merged = 0, 0
    for date_short, day_data in day_buckets.items():
        fpath = os.path.join(raw_dir, f'prices_{date_short}.json')
        existing = {}
        if os.path.exists(fpath):
            with open(fpath) as f:
                existing = json.load(f)
            merged += 1
        existing.update(day_data)
        with open(fpath, 'w') as f:
            json.dump(existing, f, ensure_ascii=False, separators=(',', ':'))
        written += 1
    
    print(f"\n=== Conversion ===")
    print(f"Files: {stats['files']}, Rows: {stats['rows']}")
    print(f"Skipped: {stats['skipped']}, Bad dates: {stats['bad_date']}")
    print(f"Date files: {written} ({merged} merged)")
    
    return stats

def coverage_report(stats, export_codes):
    """Report missing codes and date range gaps."""
    print(f"\n=== Coverage Report ===")
    
    processed = stats['processed_codes']
    missing = [c for c in export_codes if c not in processed]
    
    print(f"Export list: {len(export_codes)} codes")
    print(f"Processed: {len(processed)}")
    print(f"Missing: {len(missing)}")
    
    if missing:
        print(f"Missing codes: {', '.join(missing[:20])}")
        if len(missing) > 20:
            print(f"  ... and {len(missing)-20} more")
    
    # Date range summary
    if stats['per_code_dates']:
        ranges = list(stats['per_code_dates'].values())
        min_date = min(r[0] for r in ranges if r[0])
        max_date = max(r[1] for r in ranges if r[1])
        print(f"\nCollective date range: {min_date} → {max_date}")
        
        # Flag codes with < 1 year of data
        short = []
        for code, (first, last, rows) in stats['per_code_dates'].items():
            if first and last and rows < 200:
                short.append((code, first, last, rows))
        if short:
            print(f"Short history (<200 bars): {len(short)} codes")
    
    # Wrong timeframe
    if stats['wrong_timeframe']:
        print(f"\n⚠ WRONG TIMEFRAME: {len(stats['wrong_timeframe'])} files!")
        for code, warnings in stats['wrong_timeframe'][:10]:
            print(f"  {code}: {'; '.join(warnings)}")

def sanity_check(raw_dir, git_backup_dir):
    """Compare TV data with git raw/ old data for overlapping dates."""
    if not os.path.exists(git_backup_dir):
        print("\n=== Sanity Check === (skipped — no git backup dir)")
        return
    
    git_files = sorted(f for f in os.listdir(git_backup_dir) if f.startswith('prices_'))
    tv_files = sorted(f for f in os.listdir(raw_dir) if f.startswith('prices_'))
    overlap = sorted(set(git_files) & set(tv_files))
    
    if not overlap:
        print("\n=== Sanity Check === (no overlapping dates)")
        return
    
    print(f"\n=== Sanity Check ({len(overlap)} overlapping dates) ===")
    issues = 0
    
    for fname in overlap[:3]:
        with open(os.path.join(git_backup_dir, fname)) as f:
            git_data = json.load(f)
        with open(os.path.join(raw_dir, fname)) as f:
            tv_data = json.load(f)
        
        common = set(git_data.keys()) & set(tv_data.keys())
        date_label = f"{fname[7:11]}-{fname[11:13]}-{fname[13:15]}"
        print(f"  {date_label}: {len(common)} common stocks")
        
        diffs = 0
        for code in sorted(common)[:10]:
            g_val = git_data[code]
            t_val = tv_data[code]
            g_close = float(g_val.get('close', g_val) if isinstance(g_val, dict) else g_val)
            t_close = float(t_val.get('close', t_val) if isinstance(t_val, dict) else t_val)
            if abs(g_close - t_close) > max(0.001, g_close * 0.001):
                print(f"    ⚠ {code}: git={g_close:.4f} vs tv={t_close:.4f}")
                diffs += 1
                issues += 1
        
        if diffs == 0:
            print(f"    ✅ All match")
    
    if issues == 0:
        print("✅ Sanity check PASSED")
    else:
        print(f"⚠ {issues} mismatches — investigate before trusting TV data")

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('export_dir', help='Directory with TV CSV exports')
    ap.add_argument('--list', default=None, help='Export list file (default: tv_export_list.txt)')
    args = ap.parse_args()
    
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RAW_DIR = os.path.join(BASE, 'raw')
    GIT_BACKUP = os.path.join(BASE, 'raw_git_backup')
    
    # Load export list
    list_path = args.list or os.path.join(BASE, 'tv_export_list.txt')
    export_codes = set()
    if os.path.exists(list_path):
        with open(list_path) as f:
            for line in f:
                c = line.strip().split()[0].zfill(5)
                if c.isdigit() and len(c) == 5:
                    export_codes.add(c)
    else:
        print(f"⚠ No export list at {list_path}")
    
    # Backup existing git raw/ files
    if os.path.exists(RAW_DIR):
        existing_git = [f for f in os.listdir(RAW_DIR) if f.startswith('prices_')]
        if existing_git and not os.path.exists(GIT_BACKUP):
            os.makedirs(GIT_BACKUP, exist_ok=True)
            for f in existing_git:
                shutil.copy2(os.path.join(RAW_DIR, f), os.path.join(GIT_BACKUP, f))
            print(f"Backed up {len(existing_git)} git raw/ files → raw_git_backup/")
    
    print(f"Converting from: {args.export_dir}")
    print(f"Output to: {RAW_DIR}")
    
    stats = convert_exports(args.export_dir, RAW_DIR, export_codes)
    coverage_report(stats, export_codes)
    sanity_check(RAW_DIR, GIT_BACKUP)
