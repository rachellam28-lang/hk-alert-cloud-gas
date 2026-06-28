#!/bin/bash
# Single HOLDINGS cron: bounded daily scrape, refresh prices/suspended, regenerate,
# verify, deploy. Slow tail stocks are handled by the separate resume job.
# Lock handled by Python (src/runner.py → backfill._acquire_lock) — no bash noclobber.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CCASS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$CCASS_DIR/.." && pwd)"

cd "$CCASS_DIR"

export HOLDINGS_FAST="${HOLDINGS_FAST:-1}"
export HOLDINGS_DAILY_MAX_MINUTES="${HOLDINGS_DAILY_MAX_MINUTES:-120}"
export HOLDINGS_SKIP_MARKET_CAP_FETCH="${HOLDINGS_SKIP_MARKET_CAP_FETCH:-1}"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || command -v python)"
fi

echo "=== $(date) ==="
echo "1/5 Run HOLDINGS scrape (bounded daily mode)..."
set +e
"$PYTHON_BIN" -m src.runner
runner_rc=$?
set -e
if [[ "$runner_rc" -eq 1 ]]; then
    echo "WARN: HOLDINGS scrape returned partial coverage; resume job will continue later"
elif [[ "$runner_rc" -ne 0 ]]; then
    echo "ERROR: HOLDINGS scrape failed (rc=$runner_rc)"
    exit "$runner_rc"
fi

echo "2/5 Regenerate holdings.json..."
"$PYTHON_BIN" scripts/regenerate_json.py --min-coverage "${AUDIT_MIN_COVERAGE:-99.0}" || { echo "ERROR: holdings.json regeneration failed"; exit 1; }

echo "2.2/5 Refresh prices + suspended (Futu)..."
set +e
timeout "${FUTU_PRICE_TIMEOUT_SECONDS:-180}" "$PYTHON_BIN" scripts/daily_lp_futu.py
futu_price_rc=$?
set -e
if [[ "$futu_price_rc" -ne 0 ]]; then
    echo "WARN: Futu price refresh failed/timed out (rc=$futu_price_rc); trying Longbridge quote fallback"
    "$PYTHON_BIN" scripts/daily_lp_longbridge.py || { echo "ERROR: Longbridge price fallback failed"; exit 1; }
fi

echo "2.5/5 Generate prices.json for dashboard fallback..."
"$PYTHON_BIN" scripts/generate_prices_json.py || { echo "ERROR: prices.json generation failed"; exit 1; }

echo "2.6/5 Generate signals.json for dashboard fallback..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_signals.py" || { echo "ERROR: signals.json generation failed"; exit 1; }

echo "2.7/5 Refresh Futu dopamine (best-effort)..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/dopamine_refresh.py" || echo "WARN: market sentiment refresh unavailable; keeping existing market cache"

echo "3.45/5 Refresh placement returns..."
"$PYTHON_BIN" scripts/refresh_placement_returns.py || { echo "ERROR: placement returns refresh failed"; exit 1; }

echo "3.5/5 Build publish bundle..."
"$PYTHON_BIN" scripts/build_publish_bundle.py || { echo "ERROR: publish bundle build failed"; exit 1; }

echo "3.6/5 Regenerate daily trade prompt..."
"$PYTHON_BIN" scripts/gen_daily_trade_prompt.py || { echo "ERROR: daily trade prompt generation failed"; exit 1; }

echo "3.65/5 Regenerate rights_analysis.html..."
"$PYTHON_BIN" scripts/gen_rights_page.py || { echo "ERROR: rights page generation failed"; exit 1; }

echo "3.7/5 Cleanup logs..."
"$PYTHON_BIN" scripts/cleanup_logs.py || { echo "ERROR: log cleanup failed"; exit 1; }

echo "4/5 Audit gate..."
"$PYTHON_BIN" scripts/audit_gate.py --min-coverage "${AUDIT_MIN_COVERAGE:-99.0}" || { echo "ERROR: audit gate failed"; exit 1; }

echo "5/5 Deploy to GitHub..."
cd "$REPO_ROOT"
git add holdings.json data/holdings.json ccass.json market.json data/market.json data/stock_prices.json data/suspended_stocks.json data/prices.json data/signals.json data/publish_bundle.json daily_trade_prompt.html rights_analysis.html
if git commit -m "daily: holdings refresh $(date +%Y-%m-%d)"; then
    git push || { echo "ERROR: git push failed"; exit 1; }
else
    echo "No changes to commit"
fi

echo "Done!"
