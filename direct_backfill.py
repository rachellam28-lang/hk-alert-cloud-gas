"""Legacy direct backfill wrapper.

Old Longbridge implementation retired. This now delegates to the standard
fill_missing workflow so holdings backfill no longer depends on Longbridge.
"""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILL_MISSING = ROOT / "ccass" / "scripts" / "fill_missing.py"


def main() -> int:
    dates = sys.argv[1:] or ["2026-06-12"]
    rc = 0
    for d in dates:
        print(f"[direct_backfill] delegating {d} -> fill_missing.py", flush=True)
        env = os.environ.copy()
        env["HOLDINGS_PROVIDER"] = "hkex"
        env.pop("LONGBRIDGE_ACCESS_TOKEN", None)
        result = subprocess.run([sys.executable, str(FILL_MISSING), d], env=env)
        if result.returncode != 0:
            rc = result.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
