"""Compatibility wrapper for the Futu-based daily price refresh.

The old fast path is retired. This wrapper preserves the command name while
delegating to the Futu implementation.
"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("daily_lp_futu.py")), run_name="__main__")
