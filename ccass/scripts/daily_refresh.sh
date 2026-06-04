#!/bin/bash
# Single CCASS cron: scrape, refresh prices/suspended, regenerate, verify, deploy.
set -euo pipefail
cd /c/Users/Administrator/Desktop/automatic/ccass-debug/ccass

LOCK_FILE="${TMPDIR:-/tmp}/ccass_backfill.lock"

if ! ( set -o noclobber; echo "$$" > "$LOCK_FILE" ) 2>/dev/null; then
    old_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        echo "Another CCASS job is running (PID $old_pid); skipping without killing it."
        exit 0
    fi
    echo "Removing stale CCASS lock for dead PID: ${old_pid:-unknown}"
    rm -f "$LOCK_FILE"
    ( set -o noclobber; echo "$$" > "$LOCK_FILE" ) 2>/dev/null || {
        echo "Another CCASS job acquired the lock; skipping."
        exit 0
    }
fi
trap 'rm -f "$LOCK_FILE"' EXIT

echo "=== $(date) ==="
echo "1/5 Run CCASS scrape..."
python -m src.runner || { echo "ERROR: CCASS scrape failed"; exit 1; }

echo "2/5 Refresh prices + suspended..."
python scripts/refresh_prices_and_suspended.py || { echo "ERROR: price refresh failed"; exit 1; }

echo "2.5/5 Generate prices.json for dashboard fallback..."
python scripts/generate_prices_json.py || { echo "ERROR: prices.json generation failed"; exit 1; }

echo "2.6/5 Generate signals.json for dashboard fallback..."
python scripts/generate_signals_json.py || { echo "ERROR: signals.json generation failed"; exit 1; }

echo "3/5 Regenerate ccass.json..."
python scripts/regenerate_json.py || { echo "ERROR: ccass.json regeneration failed"; exit 1; }

echo "4/5 Verify ccass.json..."
python ../verify_dashboard.py || { echo "ERROR: dashboard verification failed"; exit 1; }

echo "5/5 Deploy to GitHub..."
cd ..
git add ccass.json ccass/data/stock_prices.json ccass/data/suspended_stocks.json data/prices.json data/signals.json
if git commit -m "daily: ccass refresh $(date +%Y-%m-%d)"; then
    git push || { echo "ERROR: git push failed"; exit 1; }
else
    echo "No changes to commit"
fi

echo "Done!"
