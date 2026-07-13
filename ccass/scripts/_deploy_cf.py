#!/usr/bin/env python
"""
Direct deploy to Cloudflare Pages via Wrangler. Bypasses GitHub entirely.
Usage:
    python _deploy_cf.py                       # Deploy from cwd
    python _deploy_cf.py --dir ./_output       # Deploy specific dir
    python _deploy_cf.py --project hk-alert-cloud-gas
"""

import subprocess, os, sys, shutil, tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

DEFAULT_PROJECT = "hk-alert-cloud-gas"
DEFAULT_BRANCH = "main"

# Root files to deploy (relative to source dir). Keep this list tight: never
# deploy the repo root directly because it contains local tools and backups.
ROOT_DEPLOY_FILES = [
    "index.html",
    "404.html",
    "ccass.html",
    "daily_trade_prompt.html",
    "distribution_day.html",
    "fundflow.html",
    "gap_fvg.html",
    "guide.html",
    "history.html",
    "kbar_matrix.html",
    "rotation_matrix.html",
    "jieqi_analysis.html",
    "momentum_list.html",
    "rights_analysis.html",
    "signals.html",
    "timing_analysis.html",
    "vqc_analysis.html",
    "watchlist.html",
    "ccass.json",
    "holdings.json",
    "market.json",
    "manifest.json",
    "health.json",
    "events.json",
    "events_watchlist.json",
    "fvg.json",
    "robots.txt",
    "_headers",
    "service-worker.js",
    "shared-nav.js",
]

DATA_DEPLOY_FILES = {
    Path("data/alerts.json"),
    Path("data/announcements.json"),
    Path("data/breakthroughs.json"),
    Path("data/confluence.json"),
    Path("data/corp_graded_scan.json"),
    Path("data/distribution_day_backtest.json"),
    Path("data/fundflow.json"),
    Path("data/history.json"),
    Path("data/jieqi_backtest.json"),
    Path("data/jieqi_calendar.json"),
    Path("data/kbar_cache.json"),
    Path("data/kbar_symbols/index.json"),
    Path("data/market.json"),
    Path("data/participant_anomalies.json"),
    Path("data/placements_enriched.json"),
    Path("data/prices.json"),
    Path("data/publish_bundle.json"),
    Path("data/repo_audit.json"),
    Path("data/rights_analysis.json"),
    Path("data/signals.json"),
    Path("data/sector_rotation.json"),
    Path("data/stock_prices.json"),
    Path("data/trade_engine.json"),
    Path("data/timesfm.json"),
    Path("data/tradeable.json"),
    Path("data/suspended_stocks.json"),
    Path("data/transfers.json"),
    Path("data/vqc_backtest.json"),
    Path("data/watchlist.json"),
}

DATA_DEPLOY_SKIP = {
    Path("data/holdings.json"),
    Path("data/ccass.json"),
}


def load_env():
    """Load optional Cloudflare API env; Wrangler OAuth cache also works."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    for d in [Path.cwd(), Path.cwd().parent]:
        env_file = d / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = line.strip()
                if not token and line.startswith("CLOUDFLARE_API_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif not account_id and line.startswith("CLOUDFLARE_ACCOUNT_ID="):
                    account_id = line.split("=", 1)[1].strip()
    return token, account_id


def copy_site_files(src: Path, tmp: Path) -> int:
    copied = 0
    for rel in ROOT_DEPLOY_FILES:
        src_file = src / rel
        if not src_file.exists():
            continue
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        copied += 1

    for rel_dir in ("icons", "data", "docs", "functions"):
        src_dir = src / rel_dir
        if not src_dir.exists():
            continue
        for src_file in src_dir.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(src)
            if rel in DATA_DEPLOY_SKIP:
                continue
            is_kbar_shard = len(rel.parts) == 3 and rel.parts[:2] == ("data", "kbar_symbols") and rel.suffix.lower() == ".json"
            if rel.parts and rel.parts[0] == "data" and rel not in DATA_DEPLOY_FILES and not is_kbar_shard:
                continue
            if rel.suffix.lower() not in {".html", ".json", ".js", ".png", ".webp", ".jpg", ".jpeg", ".svg", ".ico", ".txt"}:
                continue
            if ".bak" in src_file.name or src_file.name == "scanner.db":
                continue
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)
            copied += 1
    return copied


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Deploy to Cloudflare Pages")
    parser.add_argument("--dir", default=".", help="Source directory to deploy")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Cloudflare Pages project name")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Deploy branch")
    args = parser.parse_args()

    src = Path(args.dir).resolve()
    if not src.is_dir():
        print(f"ERROR: {src} not found")
        sys.exit(1)

    token, account_id = load_env()

    # Check required files exist
    missing = [f for f in ("index.html", "holdings.json", "data/signals.json", "data/transfers.json") if not (src / f).exists()]
    if missing:
        print(f"ERROR: Missing required deploy files: {missing}")
        sys.exit(1)

    # Create temp deploy dir with only dashboard files
    tmp = Path(tempfile.mkdtemp(prefix="cf_deploy_"))
    try:
        copied = copy_site_files(src, tmp)

        if copied == 0:
            print("ERROR: No files to deploy")
            sys.exit(1)

        total_size = sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file())
        print(f"Deploying {copied} files ({total_size/1024/1024:.1f}MB) -> {args.project}")

        env = os.environ.copy()
        if token:
            env["CLOUDFLARE_API_TOKEN"] = token
        if account_id:
            env["CLOUDFLARE_ACCOUNT_ID"] = account_id

        r = subprocess.run(
            [
                "cmd.exe", "/c", "npx", "wrangler", "pages", "deploy", str(tmp),
                f"--project-name={args.project}",
                f"--branch={args.branch}",
                "--commit-dirty=true",
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

        output = (r.stderr or "") + "\n" + (r.stdout or "")
        print(output)

        if r.returncode != 0:
            print(f"\nFAIL (rc={r.returncode})")
            sys.exit(r.returncode)

        print("\nDeployed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
