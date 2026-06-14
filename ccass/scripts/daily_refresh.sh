#!/bin/bash
# Single HOLDINGS cron: scrape, refresh prices/suspended, regenerate, verify, deploy.
# Lock handled by Python (src/runner.py → backfill._acquire_lock) — no bash noclobber.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CCASS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$CCASS_DIR/.." && pwd)"

cd "$CCASS_DIR"

export HOLDINGS_FAST="${HOLDINGS_FAST:-1}"
export HOLDINGS_ULTRA_FAST="${HOLDINGS_ULTRA_FAST:-1}"
export HOLDINGS_SKIP_MARKET_CAP_FETCH="${HOLDINGS_SKIP_MARKET_CAP_FETCH:-1}"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || command -v python)"
fi

echo "=== $(date) ==="
echo "1/5 Run HOLDINGS scrape..."
"$PYTHON_BIN" -m src.runner || { echo "ERROR: HOLDINGS scrape failed"; exit 1; }

echo "2/5 Refresh prices + suspended (Futu)..."
"$PYTHON_BIN" scripts/daily_lp_futu.py || { echo "ERROR: price refresh failed"; exit 1; }

echo "2.5/5 Generate prices.json for dashboard fallback..."
"$PYTHON_BIN" scripts/generate_prices_json.py || { echo "ERROR: prices.json generation failed"; exit 1; }

echo "2.6/5 Generate signals.json for dashboard fallback..."
"$PYTHON_BIN" scripts/generate_signals_json.py || { echo "ERROR: signals.json generation failed"; exit 1; }

echo "3/5 Regenerate holdings.json..."
"$PYTHON_BIN" scripts/regenerate_json.py || { echo "ERROR: holdings.json regeneration failed"; exit 1; }

echo "4/5 Verify holdings.json..."
"$PYTHON_BIN" scripts/verify_dashboard.py || { echo "ERROR: dashboard verification failed"; exit 1; }

echo "5/5 Deploy to GitHub..."
cd "$REPO_ROOT"
git add holdings.json ccass.json ccass/data/stock_prices.json ccass/data/suspended_stocks.json data/prices.json data/signals.json
if git commit -m "daily: holdings refresh $(date +%Y-%m-%d)"; then
    git push || { echo "ERROR: git push failed"; exit 1; }
else
    echo "No changes to commit"
fi

echo "Done!"
