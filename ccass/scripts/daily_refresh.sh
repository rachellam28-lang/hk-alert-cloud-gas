#!/bin/bash
# Daily: refresh yfinance prices + suspended detection + deploy
set -euo pipefail
cd /c/Users/Administrator/Desktop/automatic/ccass-debug/ccass

echo "=== $(date) ==="
echo "1/3 Refresh prices + suspended..."
python scripts/refresh_prices_and_suspended.py || { echo "ERROR: price refresh failed"; exit 1; }

echo "2/3 Regenerate ccass.json..."
python scripts/regenerate_json.py || { echo "ERROR: ccass.json regeneration failed"; exit 1; }

echo "3/3 Deploy to GitHub..."
cd ..
git add ccass.json ccass/data/stock_prices.json ccass/data/suspended_stocks.json
if git commit -m "daily: refresh prices + suspended $(date +%Y-%m-%d)"; then
    git push || { echo "ERROR: git push failed"; exit 1; }
else
    echo "No changes to commit"
fi

echo "Done!"
