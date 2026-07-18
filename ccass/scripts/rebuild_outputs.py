"""Windows-friendly rebuild pipeline after holdings DB updates.

Purpose:
- Rebuild all derived JSON/HTML artifacts from the current repo state
- Mirror the post-scrape stages from daily_refresh.sh without requiring bash
- Keep latest page data in sync after a manual/backfill DB repair
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


CCASS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CCASS_DIR.parent
PYTHON = Path(sys.executable)
TIMESFM_PY = REPO_ROOT / ".venv-timesfm" / "Scripts" / "python.exe"


def _run(cmd: list[str], cwd: Path, *, required: bool = True, env: dict[str, str] | None = None) -> bool:
    print(f"RUN  {cwd.name}: {' '.join(shlex.quote(str(x)) for x in cmd)}", flush=True)
    proc = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0:
        print("OK", flush=True)
        return True

    tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-800:]
    level = "ERROR" if required else "WARN"
    print(f"{level} rc={proc.returncode}\n{tail}", flush=True)
    if required:
        raise SystemExit(proc.returncode)
    return False


def _refresh_prices() -> None:
    futu = [PYTHON, CCASS_DIR / "scripts" / "daily_lp_futu.py"]
    if _run(futu, CCASS_DIR, required=False):
        return
    lb = [PYTHON, CCASS_DIR / "scripts" / "daily_lp_longbridge.py"]
    _run(lb, CCASS_DIR, required=True)


def _timesfm_available() -> bool:
    return TIMESFM_PY.exists()


def _stage_outputs() -> None:
    paths = [
        "holdings.json",
        "data/holdings.json",
        "ccass.json",
        "data/ccass.json",
        "market.json",
        "data/market.json",
        "data/stock_prices.json",
        "data/suspended_stocks.json",
        "data/prices.json",
        "data/fundflow.json",
        "data/announcements.json",
        "data/placements_enriched.json",
        "data/rights_analysis.json",
        "data/signals.json",
        "data/transfers.json",
        "ccass/data/transfers.json",
        "data/participant_anomalies.json",
        "ccass/data/participant_anomalies.json",
        "data/timesfm.json",
        "data/kbar_cache.json",
        "data/trade_engine.json",
        "data/options_levels.json",
        "data/repo_audit.json",
        "data/alerts.json",
        "data/watchlist.json",
        "data/history.json",
        "data/breakthroughs.json",
        "data/corp_graded_scan.json",
        "data/publish_bundle.json",
        "data/vqc_backtest.json",
        "data/distribution_day_backtest.json",
        "data/jieqi_backtest.json",
        "events.json",
        "events_watchlist.json",
        "daily_trade_prompt.html",
        "timing_analysis.html",
        "vqc_analysis.html",
        "distribution_day.html",
        "jieqi_analysis.html",
        "rights_analysis.html",
    ]
    _run(["git", "add", *paths], REPO_ROOT, required=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Explicit holdings publish date YYYY-MM-DD")
    parser.add_argument("--min-coverage", default="99.0")
    parser.add_argument("--stage", action="store_true", help="Stage refreshed files with git add")
    args = parser.parse_args()

    regen_cmd = [PYTHON, CCASS_DIR / "scripts" / "regenerate_json.py"]
    if args.date:
        regen_cmd.extend(["--date", args.date])
    else:
        regen_cmd.extend(["--min-coverage", str(args.min_coverage)])

    print("=== rebuild_outputs ===", flush=True)
    _run([PYTHON, CCASS_DIR / "scripts" / "repair_pct_scale.py"], CCASS_DIR, required=False)
    _run(regen_cmd, CCASS_DIR, required=True)
    _run([PYTHON, CCASS_DIR / "scripts" / "detect_transfers.py", "--allow-unavailable"], CCASS_DIR, required=True)
    _run([PYTHON, CCASS_DIR / "scripts" / "build_participant_anomalies.py", "--allow-unavailable"], CCASS_DIR, required=True)
    _refresh_prices()
    _run([PYTHON, CCASS_DIR / "scripts" / "generate_prices_json.py"], CCASS_DIR, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "dopamine_refresh.py"], REPO_ROOT, required=False)
    _run([PYTHON, REPO_ROOT / "scripts" / "fetch_fundflow.py"], REPO_ROOT, required=False)
    _run([PYTHON, REPO_ROOT / "scanner" / "_corp_scan_only.py"], REPO_ROOT, required=False)
    _run([PYTHON, REPO_ROOT / "scanner" / "_corp_graded_scan.py"], REPO_ROOT, required=False)
    _run([PYTHON, "-c", "from scanner.local_alert_store import export_all; export_all()"], REPO_ROOT, required=False)
    _run([PYTHON, REPO_ROOT / "scripts" / "sync_rights_from_announcements.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "refresh_placement_returns.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "gen_rights_page.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_signals.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "sync_publish_aliases.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_vqc_backtest.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_distribution_day_backtest.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_jieqi_backtest.py"], REPO_ROOT, required=True)
    if _timesfm_available():
        _run(
            [
                TIMESFM_PY,
                REPO_ROOT / "timesfm_daily.py",
                "--fields",
                os.environ.get("TIMESFM_FIELDS", "broker_top5_pct,total_pct,adj_hhi"),
                "--top",
                os.environ.get("TIMESFM_TOP", "15"),
                "--horizon",
                os.environ.get("TIMESFM_HORIZON", "5"),
                "--min-days",
                os.environ.get("TIMESFM_MIN_DAYS", "25"),
                "--lookback",
                os.environ.get("TIMESFM_LOOKBACK", "5"),
                "--json-only",
            ],
            REPO_ROOT,
            required=False,
        )
    _run([PYTHON, REPO_ROOT / "scripts" / "build_kbar_cache.py"], REPO_ROOT, required=False)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_hk_symbol_index.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_sector_rotation.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_options_levels.py", "--best-effort"], REPO_ROOT, required=False)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_trade_engine.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "repo_audit.py", "export"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "build_publish_bundle.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "gen_vqc_analysis.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "gen_distribution_day_analysis.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "gen_jieqi_analysis.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "gen_timing_analysis.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "gen_daily_trade_prompt.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "apply_shared_shell.py"], REPO_ROOT, required=True)
    _run([PYTHON, REPO_ROOT / "scripts" / "cleanup_logs.py"], REPO_ROOT, required=True)
    _run([PYTHON, CCASS_DIR / "scripts" / "audit_gate.py", "--min-coverage", str(args.min_coverage)], CCASS_DIR, required=False)
    if args.stage:
        _stage_outputs()
    print("=== rebuild_outputs done ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
