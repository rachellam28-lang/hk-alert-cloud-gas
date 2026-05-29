"""Detect unrecorded share consolidations using yo/py ratio and adjust.

Strategy: yo (2026 year-open) / py (2025 year-open) ratio captures the
mechanical consolidation effect during 2025, excluding 2026 price movement.
Snap to nearest common consolidation ratio [2,5,10,20,25,50,100].
"""
import json
from pathlib import Path

PROJECT = Path(__file__).parent.parent
PRICES_PATH = PROJECT / "data" / "stock_prices.json"

def load_prices():
    return json.loads(PRICES_PATH.read_text(encoding='utf-8'))

def save_prices(data):
    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRICES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

COMMON_RATIOS = [2, 5, 10, 20, 25, 50, 100]

def snap_ratio(r):
    """Snap to nearest common consolidation ratio."""
    return min(COMMON_RATIOS, key=lambda x: abs(x - r))

def main():
    data = load_prices()
    print(f"Total stocks in cache: {len(data)}")
    
    # Find stocks with py_pct > 500% (suspicious)
    adjusted = 0
    skipped = 0
    
    for code, entry in sorted(data.items()):
        py_pct = entry.get('py_pct', 0)
        if not py_pct or py_pct <= 500:
            continue
        
        py = entry.get('py', 0)
        yo = entry.get('yo', 0)
        lp = entry.get('lp', 0)
        
        if not py or not yo or py <= 0:
            skipped += 1
            continue
        
        ratio = yo / py
        
        if ratio > 2.0:
            # Likely consolidation
            snapped = snap_ratio(ratio)
            adjusted_py = round(py * snapped, 3)
            adjusted_pct = round((lp - adjusted_py) / adjusted_py * 100, 2) if adjusted_py > 0 else py_pct
            
            entry['apy'] = adjusted_py
            entry['apy_pct'] = adjusted_pct
            entry['split_ratio'] = snapped
            entry['_raw_ratio'] = round(ratio, 2)
            
            print(f"  {code}: py={py}→adj={adjusted_py}  "
                  f"(yo/py={ratio:.1f}x→snap {snapped}x)  "
                  f"{py_pct:.0f}%→{adjusted_pct:.0f}%")
            adjusted += 1
        else:
            skipped += 1
    
    save_prices(data)
    
    print(f"\nAdjusted: {adjusted}, Skipped: {skipped}")
    print(f"Output: {PRICES_PATH}")

if __name__ == "__main__":
    main()
