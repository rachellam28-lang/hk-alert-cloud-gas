#!/usr/bin/env python
"""Compatibility wrapper for Longbridge latest-day holdings backfill."""
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
        print(f"[run_lb_backfill] delegating {d} -> fill_missing.py (longbridge latest-day mode)", flush=True)
        env = os.environ.copy()
        env["HOLDINGS_PROVIDER"] = "longbridge"
        env["LONGBRIDGE_USE_CLI"] = env.get("LONGBRIDGE_USE_CLI", "1")
        env["LONGBRIDGE_ENABLE_MCP_FALLBACK"] = env.get("LONGBRIDGE_ENABLE_MCP_FALLBACK", "0")
        result = subprocess.run([sys.executable, str(FILL_MISSING), d], env=env)
        if result.returncode != 0:
            rc = result.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
