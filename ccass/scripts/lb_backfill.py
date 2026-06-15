#!/usr/bin/env python
"""Legacy backfill wrapper.

The old Longbridge-backed entrypoint is retired.
This wrapper now delegates to the standard HKEX scraper path via
scripts/fill_missing.py so we stop depending on Longbridge for holdings
backfill.

Usage:
    python -u scripts/lb_backfill.py YYYY-MM-DD [YYYY-MM-DD ...]
"""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILL_MISSING = ROOT / "scripts" / "fill_missing.py"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -u scripts/lb_backfill.py YYYY-MM-DD [YYYY-MM-DD ...]")
        return 1

    dates = sys.argv[1:]
    rc = 0
    for d in dates:
        print(f"[lb_backfill] delegating {d} -> fill_missing.py", flush=True)
        env = os.environ.copy()
        env["HOLDINGS_PROVIDER"] = "hkex"
        env.pop("LONGBRIDGE_ACCESS_TOKEN", None)
        result = subprocess.run([sys.executable, str(FILL_MISSING), d], env=env)
        if result.returncode != 0:
            rc = result.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
