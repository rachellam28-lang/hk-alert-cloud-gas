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
export HOLDINGS_PROVIDER="${HOLDINGS_PROVIDER:-longbridge}"
export HOLDINGS_DAILY_MAX_MINUTES="${HOLDINGS_DAILY_MAX_MINUTES:-120}"
export HOLDINGS_SKIP_MARKET_CAP_FETCH="${HOLDINGS_SKIP_MARKET_CAP_FETCH:-1}"
export CCASS_TELEGRAM_REQUIRE_DEDICATED="${CCASS_TELEGRAM_REQUIRE_DEDICATED:-1}"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif [[ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/Scripts/python.exe"
else
    PYTHON_BIN="$(command -v python3 || command -v python)"
fi
if [[ -x "$REPO_ROOT/.venv-timesfm/bin/python" ]]; then
    TIMESFM_PY="$REPO_ROOT/.venv-timesfm/bin/python"
elif [[ -x "$REPO_ROOT/.venv-timesfm/Scripts/python.exe" ]]; then
    TIMESFM_PY="$REPO_ROOT/.venv-timesfm/Scripts/python.exe"
else
    TIMESFM_PY=""
fi
if [[ "${SENTRY_CRON_WRAPPED:-0}" != "1" && "${SENTRY_CRON_DISABLED:-0}" != "1" ]]; then
    export SENTRY_CRON_WRAPPED=1
    exec "$PYTHON_BIN" "$REPO_ROOT/scripts/cron_monitor.py" \
        --slug "${SENTRY_DAILY_REFRESH_SLUG:-hk-alert-daily-refresh}" \
        -- "$0" "$@"
fi

echo "=== $(date) ==="
if [[ "${HOLDINGS_SKIP_SCRAPE:-0}" == "1" ]]; then
    echo "1/5 Skip HOLDINGS scrape (HOLDINGS_SKIP_SCRAPE=1)"
else
    echo "1/5 Run HOLDINGS scrape (bounded daily mode)..."
    RUNNER_ARGS=()
    if [[ "${HOLDINGS_PROVIDER:-}" == "longbridge" ]]; then
        echo "1.0/5 Probe latest observed Longbridge CCASS date..."
        if [[ -n "${HOLDINGS_QUERY_DATE:-}" ]]; then
            provider_date="$HOLDINGS_QUERY_DATE"
        else
            provider_date="$($PYTHON_BIN scripts/latest_longbridge_ccass_date.py)" || {
                echo "ERROR: cannot resolve Longbridge CCASS date; refusing a full-universe blind scrape"
                exit 1
            }
        fi
        if [[ ! "$provider_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            echo "ERROR: invalid Longbridge CCASS date: $provider_date"
            exit 1
        fi
        echo "Longbridge latest observed CCASS date: $provider_date"
        RUNNER_ARGS+=(--query-date "$provider_date")
    fi
    set +e
    "$PYTHON_BIN" -m src.runner "${RUNNER_ARGS[@]}"
    runner_rc=$?
    set -e
    if [[ "$runner_rc" -eq 1 ]]; then
        echo "WARN: HOLDINGS scrape returned partial coverage; resume job will continue later"
    elif [[ "$runner_rc" -ne 0 ]]; then
        echo "ERROR: HOLDINGS scrape failed (rc=$runner_rc)"
        exit "$runner_rc"
    fi
fi

echo "2/5 Regenerate holdings.json..."
"$PYTHON_BIN" scripts/repair_pct_scale.py || echo "WARN: pct scale repair unavailable; continuing"
"$PYTHON_BIN" scripts/regenerate_json.py --min-coverage "${AUDIT_MIN_COVERAGE:-99.0}" || { echo "ERROR: holdings.json regeneration failed"; exit 1; }

echo "2.1/5 Detect deposit/transfer monitor..."
"$PYTHON_BIN" scripts/detect_transfers.py --allow-unavailable || { echo "ERROR: transfer monitor generation failed"; exit 1; }

echo "2.15/5 Build participant delta/anomaly monitor..."
"$PYTHON_BIN" scripts/build_participant_anomalies.py --allow-unavailable || { echo "ERROR: participant anomaly generation failed"; exit 1; }

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

echo "2.7/5 Refresh Futu dopamine (best-effort)..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/dopamine_refresh.py" || echo "WARN: market sentiment refresh unavailable; keeping existing market cache"

echo "2.8/5 Refresh HK fund flow (best-effort)..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/fetch_fundflow.py" || echo "WARN: fund flow refresh unavailable; keeping existing fundflow cache"

echo "3.40/5 Refresh corporate announcement feed (best-effort)..."
"$PYTHON_BIN" "$REPO_ROOT/scanner/_corp_scan_only.py" || echo "WARN: corporate announcement scan unavailable; keeping existing announcements/breakthroughs"

echo "3.41/5 Run same-day corporate grading (best-effort)..."
"$PYTHON_BIN" "$REPO_ROOT/scanner/_corp_graded_scan.py" || echo "WARN: corporate grading unavailable; keeping existing corp_graded_scan"

echo "3.42/5 Export local alerts/watchlist/history..."
(cd "$REPO_ROOT" && "$PYTHON_BIN" -c "from scanner.local_alert_store import export_all; export_all()") || echo "WARN: local alert exports unavailable; keeping existing alerts/watchlist/history"

echo "3.44/5 Sync placement/rights announcements..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/sync_rights_from_announcements.py" || { echo "ERROR: rights announcement sync failed"; exit 1; }

echo "3.45/5 Refresh placement returns..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/refresh_placement_returns.py" || { echo "ERROR: placement returns refresh failed"; exit 1; }

echo "3.46/5 Regenerate rights_analysis source..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/gen_rights_page.py" || { echo "ERROR: rights page generation failed"; exit 1; }

echo "3.47/5 Generate signals.json for dashboard fallback..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_signals.py" || { echo "ERROR: signals.json generation failed"; exit 1; }

echo "3.48/5 Sync publish aliases..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/sync_publish_aliases.py" || { echo "ERROR: publish alias sync failed"; exit 1; }

echo "3.49/5 Rebuild timing sample JSON..."
if [[ "${TIMING_BACKTEST_REFRESH_ENABLED:-0}" == "1" ]]; then
    timeout "${TIMING_BACKTEST_TIMEOUT_SECONDS:-180}" "$PYTHON_BIN" "$REPO_ROOT/scripts/build_vqc_backtest.py" || echo "WARN: VQC timing cache refresh unavailable; keeping existing observed cache"
    timeout "${TIMING_BACKTEST_TIMEOUT_SECONDS:-180}" "$PYTHON_BIN" "$REPO_ROOT/scripts/build_distribution_day_backtest.py" || echo "WARN: distribution-day cache refresh unavailable; keeping existing observed cache"
    timeout "${TIMING_BACKTEST_TIMEOUT_SECONDS:-180}" "$PYTHON_BIN" "$REPO_ROOT/scripts/build_jieqi_backtest.py" || echo "WARN: jieqi timing cache refresh unavailable; keeping existing observed cache"
else
    echo "Skip legacy TradingView backtests (TIMING_BACKTEST_REFRESH_ENABLED=0); timing pages keep observed cache"
fi

echo "3.495/5 Build TimesFM multi-field cache (best-effort)..."
if [[ -n "${TIMESFM_PY:-}" ]]; then
    "$TIMESFM_PY" "$REPO_ROOT/timesfm_daily.py" --fields "${TIMESFM_FIELDS:-broker_top5_pct,total_pct,adj_hhi}" --top "${TIMESFM_TOP:-15}" --horizon "${TIMESFM_HORIZON:-5}" --min-days "${TIMESFM_MIN_DAYS:-25}" --lookback "${TIMESFM_LOOKBACK:-5}" --json-only || echo "WARN: TimesFM refresh unavailable; keeping existing timesfm cache"
else
    echo "WARN: TimesFM env unavailable; keeping existing timesfm cache"
fi

echo "3.497/5 Build Kbar preset cache (best-effort)..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_kbar_cache.py" || echo "WARN: Kbar cache refresh unavailable; keeping existing kbar cache"
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_hk_symbol_index.py" || { echo "ERROR: HK symbol index build failed"; exit 1; }

echo "3.498/5 Build HK sector rotation snapshot..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_sector_rotation.py" || { echo "ERROR: sector rotation build failed"; exit 1; }

echo "3.499/5 Build shared trading engine..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_trade_engine.py" || { echo "ERROR: trade engine build failed"; exit 1; }

echo "3.4995/5 Build repo audit snapshot..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/repo_audit.py" export || { echo "ERROR: repo audit snapshot build failed"; exit 1; }

echo "3.5/5 Build publish bundle..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/build_publish_bundle.py" || { echo "ERROR: publish bundle build failed"; exit 1; }

echo "3.55/5 Regenerate timing analysis pages..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/gen_vqc_analysis.py" || { echo "ERROR: VQC analysis page generation failed"; exit 1; }
"$PYTHON_BIN" "$REPO_ROOT/scripts/gen_distribution_day_analysis.py" || { echo "ERROR: distribution day page generation failed"; exit 1; }
"$PYTHON_BIN" "$REPO_ROOT/scripts/gen_jieqi_analysis.py" || { echo "ERROR: jieqi page generation failed"; exit 1; }
"$PYTHON_BIN" "$REPO_ROOT/scripts/gen_timing_analysis.py" || { echo "ERROR: timing analysis page generation failed"; exit 1; }

echo "3.6/5 Regenerate daily trade prompt..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/gen_daily_trade_prompt.py" || { echo "ERROR: daily trade prompt generation failed"; exit 1; }
"$PYTHON_BIN" "$REPO_ROOT/scripts/apply_shared_shell.py" || { echo "ERROR: shared page shell generation failed"; exit 1; }

echo "3.7/5 Cleanup logs..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/cleanup_logs.py" || { echo "ERROR: log cleanup failed"; exit 1; }

echo "4/5 Audit gate..."
set +e
"$PYTHON_BIN" scripts/audit_gate.py --min-coverage "${AUDIT_MIN_COVERAGE:-99.0}"
audit_rc=$?
set -e
if [[ "$audit_rc" -ne 0 ]]; then
    echo "WARN: audit gate failed (rc=$audit_rc); continuing to stage refreshed non-CCASS feeds with publish_bundle marked partial/fail"
fi

echo "5/5 Stage refreshed files..."
cd "$REPO_ROOT"
if [[ "${AUTO_STAGE_REFRESHED_FILES:-1}" == "1" ]]; then
    git add holdings.json data/holdings.json ccass.json data/ccass.json market.json data/market.json data/stock_prices.json data/suspended_stocks.json data/prices.json data/fundflow.json data/announcements.json data/placements_enriched.json data/rights_analysis.json data/signals.json data/transfers.json ccass/data/transfers.json data/participant_anomalies.json ccass/data/participant_anomalies.json data/timesfm.json data/kbar_cache.json data/trade_engine.json data/repo_audit.json data/alerts.json data/watchlist.json data/history.json data/breakthroughs.json data/corp_graded_scan.json data/publish_bundle.json data/vqc_backtest.json data/distribution_day_backtest.json data/jieqi_backtest.json events.json events_watchlist.json raw/prices_*.json daily_trade_prompt.html timing_analysis.html vqc_analysis.html distribution_day.html jieqi_analysis.html rights_analysis.html
    echo "Refreshed files staged. Commit/deploy should be handled explicitly; no GitHub push from daily_refresh.sh."
else
    echo "AUTO_STAGE_REFRESHED_FILES=0; leaving the git index unchanged for unattended refresh."
fi

echo "Done!"
