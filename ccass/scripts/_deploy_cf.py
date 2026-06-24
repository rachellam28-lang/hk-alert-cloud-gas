#!/usr/bin/env python
"""
Direct deploy to Cloudflare Pages via Wrangler — bypasses GitHub entirely.
Usage:
    python _deploy_cf.py                       # Deploy from cwd
    python _deploy_cf.py --dir ./_output       # Deploy specific dir
    python _deploy_cf.py --project hk-alert-cloud-gas
"""

import subprocess, os, sys, shutil, tempfile
from pathlib import Path

DEFAULT_PROJECT = "hk-alert-cloud-gas"
DEFAULT_BRANCH = "main"

# Files to deploy (relative to source dir)
DEPLOY_FILES = [
    "index.html",
    "ccass.json",
    "holdings.json",
    "data/prices.json",
    "data/signals.json",
]


def load_env():
    """Load CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID from .env in cwd or parent."""
    token = None
    account_id = None
    for d in [Path.cwd(), Path.cwd().parent]:
        env_file = d / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("CLOUDFLARE_API_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("CLOUDFLARE_ACCOUNT_ID="):
                    account_id = line.split("=", 1)[1].strip()
    return token, account_id


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
    if not token:
        print("ERROR: CLOUDFLARE_API_TOKEN not found in .env")
        sys.exit(1)

    if not account_id:
        print("ERROR: CLOUDFLARE_ACCOUNT_ID not found in .env")
        sys.exit(1)

    # Check required files exist
    missing = [f for f in DEPLOY_FILES if not (src / f).exists()]
    if missing:
        print(f"ERROR: Missing required deploy files: {missing}")
        sys.exit(1)

    # Create temp deploy dir with only dashboard files
    tmp = Path(tempfile.mkdtemp(prefix="cf_deploy_"))
    try:
        copied = 0
        for f in DEPLOY_FILES:
            src_file = src / f
            if src_file.exists():
                dst = tmp / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst)
                copied += 1

        if copied == 0:
            print("ERROR: No files to deploy")
            sys.exit(1)

        total_size = sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file())
        print(f"Deploying {copied} files ({total_size/1024/1024:.1f}MB) → {args.project}")

        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = token
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
            timeout=120,
        )

        output = r.stderr + "\n" + r.stdout
        print(output)

        if r.returncode != 0:
            print(f"\nFAIL (rc={r.returncode})")
            sys.exit(r.returncode)

        print("\n✅ Deployed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
