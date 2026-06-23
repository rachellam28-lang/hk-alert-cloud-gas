"""Verify holdings.json data integrity — JSON, coverage, price sanity."""
import json, sys, math
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOLDINGS_JSON = PROJECT_ROOT / "holdings.json"

THRESHOLDS = {
    "py_pct_max": 1000,   # >1000% likely share consolidation
    "py_pct_min": -99.9,  # < -99.9% suspicious
    "yo_pct_max": 1000,
    "yo_pct_min": -99.9,
}

errors = []
warnings = []

# ── 1. Load & validate JSON ──
try:
    raw = HOLDINGS_JSON.read_text(encoding="utf-8")
    if "NaN" in raw:
        errors.append("NaN found in raw JSON")
    data = json.loads(raw)
except Exception as e:
    errors.append(f"JSON parse failed: {e}")
    print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
    sys.exit(1)

# ── 2. Structural checks ──
required = ["updated", "stock_count", "stocks", "first_date"]
for k in required:
    if k not in data:
        errors.append(f"Missing top-level key: {k}")

stocks = data.get("stocks", [])
count = data.get("stock_count", 0)
coverage_pct = data.get("coverage_pct")
is_complete = data.get("is_complete")
if count == 0:
    errors.append("Stock count is zero")
elif count < 2000:
    if is_complete is True or coverage_pct == 100:
        errors.append(f"Stock count too low for a complete publish: {count} (expected >= 2000)")
    else:
        warnings.append(f"Partial publish stock count: {count} (latest data, incomplete coverage)")
if len(stocks) != count:
    errors.append(f"len(stocks)={len(stocks)} != stock_count={count}")

# ── 3. Per-stock checks ──
stock_keys = {"c", "n", "tp", "t5", "t10", "np"}
extreme_py = []
missing_py_count = 0

for s in stocks:
    # Required fields
    for k in stock_keys:
        if k not in s:
            errors.append(f"Stock {s.get('c','?')} missing key: {k}")
    
    # tp sanity
    tp = s.get("tp")
    if tp is not None and (tp < 0 or tp > 100):
        errors.append(f"Stock {s.get('c','?')}: tp={tp} out of range [0,100]")
    
    # Price sanity
    py = s.get("py")
    lp = s.get("lp")
    py_pct = s.get("py_pct")
    
    if py is None or lp is None:
        if py is None and lp is not None:
            missing_py_count += 1
        continue
    
    if py <= 0:
        continue
    
    if py_pct is None:
        continue
    calc = (lp - py) / py * 100
    if abs(calc - py_pct) > 0.5:
        warnings.append(f"Stock {s['c']} {s.get('n','')}: stored py_pct={py_pct}% != calculated={calc:.2f}%")
    
    if calc > THRESHOLDS["py_pct_max"] or calc < THRESHOLDS["py_pct_min"]:
        extreme_py.append(f"{s['c']} {s.get('n','')}: py={py} lp={lp} → {calc:.1f}%")

# ── 4. Coverage ──
total = len(stocks)
has_lp = sum(1 for s in stocks if s.get("lp") is not None)
has_py = sum(1 for s in stocks if s.get("py") is not None)
has_py_pct = sum(1 for s in stocks if s.get("py_pct") is not None)

# ── 5. Report ──
result = {
    "status": "FAIL" if errors else ("WARN" if warnings or extreme_py else "PASS"),
    "errors": errors,
    "warnings": warnings,
    "summary": {
        "total_stocks": total,
        "with_lp": has_lp,
        "with_py": has_py,
        "with_py_pct": has_py_pct,
        "missing_py": missing_py_count,
    },
    "extreme_py_pct": extreme_py if extreme_py else None,
}

print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(1 if result["status"] == "FAIL" else 0)
