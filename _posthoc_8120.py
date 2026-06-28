"""Post-hoc 8120 compatibility wrapper.

The maintained implementation reads raw/prices_*.json snapshots so it stays
aligned with the dashboard price cache.
"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scanner" / "_tplus_verify_v2.py"), run_name="__main__")
