"""Verify holdings.json data integrity: JSON, coverage, and price sanity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOLDINGS_JSON = PROJECT_ROOT / "holdings.json"

THRESHOLDS = {
    "py_pct_max": 1000,
    "py_pct_min": -99.9,
    "yo_pct_max": 1000,
    "yo_pct_min": -99.9,
}

errors: list[str] = []
warnings: list[str] = []


def safe_name(value) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "/")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
        .strip()
    )


def load_holdings() -> dict:
    raw = HOLDINGS_JSON.read_text(encoding="utf-8")
    if "NaN" in raw:
        errors.append("NaN found in raw JSON")
    return json.loads(raw)


try:
    data = load_holdings()
except Exception as exc:
    errors.append(f"JSON parse failed: {exc}")
    print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=True, indent=2))
    raise SystemExit(1)


required = ["updated", "stock_count", "stocks", "first_date"]
for key in required:
    if key not in data:
        errors.append(f"Missing top-level key: {key}")

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


stock_keys = {"c", "n", "tp", "t5", "t10", "np"}
extreme_py: list[str] = []
missing_py_count = 0

for stock in stocks:
    code = str(stock.get("c", "?"))
    name = safe_name(stock.get("n", ""))

    for key in stock_keys:
        if key not in stock:
            errors.append(f"Stock {code} missing key: {key}")

    tp = stock.get("tp")
    if tp is not None and (tp < 0 or tp > 100):
        errors.append(f"Stock {code}: tp={tp} out of range [0,100]")

    py = stock.get("py")
    lp = stock.get("lp")
    py_pct = stock.get("py_pct")

    if py is None or lp is None:
        if py is None and lp is not None:
            missing_py_count += 1
        continue

    if py <= 0 or py_pct is None:
        continue

    calc = (lp - py) / py * 100
    if abs(calc - py_pct) > 0.5:
        warnings.append(f"Stock {code} {name}: stored py_pct={py_pct}% != calculated={calc:.2f}%")

    if calc > THRESHOLDS["py_pct_max"] or calc < THRESHOLDS["py_pct_min"]:
        extreme_py.append(f"Stock {code} {name}: py={py} lp={lp} -> {calc:.1f}%")


total = len(stocks)
has_lp = sum(1 for stock in stocks if stock.get("lp") is not None)
has_py = sum(1 for stock in stocks if stock.get("py") is not None)
has_py_pct = sum(1 for stock in stocks if stock.get("py_pct") is not None)

result = {
    "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
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

print(json.dumps(result, ensure_ascii=True, indent=2))
raise SystemExit(1 if result["status"] == "FAIL" else 0)
