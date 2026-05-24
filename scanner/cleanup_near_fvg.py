#!/usr/bin/env python3
"""Trigger near-FVG cleanup on the GAS backend.

Usage:
  # Preview (dry run) — shows how many near-FVG rows exist without deleting:
  python cleanup_near_fvg.py --dry-run

  # Actually delete near-FVG rows:
  python cleanup_near_fvg.py

Requires GAS_WEBHOOK_URL and GAS_SECRET in environment.
These are set in GitHub Actions workflow (fvg.yml).
"""

import os, sys, json, requests

WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
SECRET = os.getenv("GAS_SECRET", "")

if not WEBHOOK_URL:
    print("ERROR: GAS_WEBHOOK_URL not set")
    sys.exit(1)

dry_run = "--dry-run" in sys.argv

params = {
    "mode": "cleanup-near-fvg",
    "secret": SECRET,
    "dry_run": "1" if dry_run else "0",
}

print(f"[cleanup] Calling GAS cleanup endpoint (dry_run={dry_run})...")
r = requests.get(WEBHOOK_URL, params=params, timeout=120)

try:
    data = r.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception:
    print(f"Response ({r.status_code}): {r.text[:500]}")

if not data.get("ok"):
    sys.exit(1)
