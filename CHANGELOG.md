# Jump Column Audit Trail — 2026-06-10

## Problem
57 🟢 signals on rights_analysis.html was mathematically impossible.
raw/ has only 9 trading days (05-29 to 06-10). Only 22-41 placements
have announcements within the raw/ window. 57 required 230+ placements.

## Root Cause
`base_day = next((d for d in sorted(pxs) if d >= ann_date), None)` 
found 05-29 as base_day for ALL old placements (pre-05-29), computing
jump on a random recent 6-day window unrelated to the placement date.

## Fix Iterations

| Version | Guard | 🟢 Count | Issue |
|---------|-------|----------|-------|
| v1 | none | 57 | 49/57 = pre-05-29 fake jumps |
| v2 | gap≤4 | 14 | 64% jump rate (2.7x backtest 24%) |
| v3 | gap≤2 | 11 | Still had gap=2-3 boundary cases |
| v4 | **gap≤1** | **8** | 38% vs market baseline 13% = 3x |

## Final Guard
```python
gap = (base_day - ann_date).days
if gap > 1:
    return None, 'no_data'
```

## Market Baseline
In the 9-day window (05-29 to 06-10): 354/2,737 stocks (12.9%) had
at least one 5-day window with +8% close-to-close jump.

Placement jump rate 38% = 3x market baseline. Significant but small n=21.

## Volume Data Gap
All raw/ files from git rebuild contain only close prices. Volume data
will populate starting from next build_signals.py snapshot run.
Until then, all 🟢 signals have unknown liquidity — manual verification required.

## Pre-Trade Gates (permanent)
1. Liquidity: avg daily volume threshold (TBD, vol data pending)
2. Zombie check: exclude stocks with >60% zero-volume days
3. Position sizing: ≤1-2% per ticket, trailing stop, no target
