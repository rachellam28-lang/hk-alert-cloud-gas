#!/usr/bin/env python
"""Legacy helper wrapper for holdings backfill.

The Longbridge-specific runner is retired. Keep this entrypoint as a thin
compatibility shell that forwards to the standard fill_missing workflow.
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
        print("Usage: python -u scripts/run_lb_backfill.py YYYY-MM-DD [YYYY-MM-DD ...]")
        return 1

    rc = 0
    for d in sys.argv[1:]:
        print(f"[run_lb_backfill] delegating {d} -> fill_missing.py", flush=True)
        env = os.environ.copy()
        env["HOLDINGS_PROVIDER"] = "hkex"
        env.pop("LONGBRIDGE_ACCESS_TOKEN", None)
        result = subprocess.run([sys.executable, str(FILL_MISSING), d], env=env)
        if result.returncode != 0:
            rc = result.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
