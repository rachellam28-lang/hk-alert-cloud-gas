"""Verify ccass.json dashboard data integrity before deploy.
Run after regenerate. Exits 0=OK, 1=FAIL.
"""
import json, sys, math
from pathlib import Path

PROJECT = Path(__file__).parent
CCASS_JSON = PROJECT / "holdings.json"

def verify():
    errors = []
    warnings = []

    # 1. Valid JSON
    try:
        data = json.loads(CCASS_JSON.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"❌ FATAL: Invalid JSON — {e}")
        return 1

    stocks = data.get("stocks", [])
    n = len(stocks)

    # 2. Stock count sanity
    coverage_pct = data.get("coverage_pct")
    is_complete = data.get("is_complete")
    if n == 0:
        errors.append("Stock count is zero")
    elif n < 2000:
        if is_complete is True or coverage_pct == 100:
            errors.append(f"Stock count too low for a complete publish: {n} (expected >2000)")
        else:
            warnings.append(f"Partial publish stock count: {n} (latest data, incomplete coverage)")
    elif n < 2600:
        warnings.append(f"Stock count low: {n} (normal ~2700)")

    # 3. Top-level keys (only check keys that ccass.json actually has)
    for k in ["updated", "stocks"]:
        if k not in data:
            errors.append(f"Missing top-level key: {k}")

    # 4. Per-stock field check
    required = ["c", "n", "tp", "t5", "t10", "np"]
    optional = ["d5", "d20", "d60", "d120", "su", "sd", "mc", "yo", "lp", "py", "py_pct"]

    nan_count = 0
    null_tp = 0
    tp_range_issues = 0
    missing_c = 0
    missing_n = 0

    for i, s in enumerate(stocks):
        # NaN check
        for k, v in s.items():
            if isinstance(v, float) and math.isnan(v):
                nan_count += 1

        # Required fields
        if not s.get("c"):
            missing_c += 1
        if not s.get("n"):
            missing_n += 1

        # tp range
        tp = s.get("tp")
        if tp is None:
            null_tp += 1
        elif not (0 <= tp <= 100):
            tp_range_issues += 1

    if nan_count:
        errors.append(f"NaN values found: {nan_count}")
    if missing_c:
        errors.append(f"Stocks missing 'c' (code): {missing_c}")
    if missing_n:
        errors.append(f"Stocks missing 'n' (name): {missing_n}")
    if null_tp > n * 0.1:
        warnings.append(f"Many null tp: {null_tp}/{n}")

    # 5. Fields with data coverage
    for field in ["yo", "py", "lp", "py_pct", "d5", "mc"]:
        cnt = sum(1 for s in stocks if s.get(field) is not None)
        pct = round(cnt / n * 100, 1)
        if pct > 0:
            print(f"  {field}: {cnt}/{n} ({pct}%)")
        else:
            warnings.append(f"Zero coverage: {field}")

    # 6. Excluded stocks check (should NOT be present)
    excluded_prefixes = ["029", "04621"]
    for pfx in excluded_prefixes:
        found = [s["c"] for s in stocks if s.get("c", "").startswith(pfx)]
        if found:
            errors.append(f"Excluded stocks present ({pfx}): {found}")

    rmb_found = [s["c"] for s in stocks if s.get("c", "").startswith("8")]
    if rmb_found:
        errors.append(f"RMB counters present (8xxxx): {len(rmb_found)} stocks")

    # 7. Print results
    print(f"\n{'='*40}")
    print(f"ccass.json: {n} stocks | updated: {data.get('updated')}")
    print(f"top_increase: {len(data.get('top_increase', []))} | top_decrease: {len(data.get('top_decrease', []))}")

    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print(f"\n❌ FAIL — {len(errors)} errors, {len(warnings)} warnings")
        return 1
    else:
        print(f"\n✅ PASS — {n} stocks, {len(warnings)} warnings")
        return 0

if __name__ == "__main__":
    sys.exit(verify())
