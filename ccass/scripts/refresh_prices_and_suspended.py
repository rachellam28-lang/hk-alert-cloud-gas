"""Compatibility wrapper for the Futu-based daily price refresh.

This entrypoint is kept so old cron/config references keep working, but it
now delegates to the Futu-based refresh.
"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("daily_lp_futu.py")), run_name="__main__")
