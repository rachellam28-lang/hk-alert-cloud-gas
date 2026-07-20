#!/usr/bin/env python
"""Print Longbridge's latest observed HK CCASS date using one liquid stock."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date, datetime


PROBE_SYMBOLS = ("00005.HK", "00700.HK", "00941.HK")


def parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def main() -> int:
    exe = shutil.which("longbridge")
    if not exe:
        print("Longbridge CLI not found", file=sys.stderr)
        return 2

    errors: list[str] = []
    for symbol in PROBE_SYMBOLS:
        try:
            proc = subprocess.run(
                [exe, "broker-holding", "detail", symbol, "--format", "json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{symbol}: timeout")
            continue
        if proc.returncode != 0:
            errors.append(f"{symbol}: rc={proc.returncode}")
            continue
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            errors.append(f"{symbol}: invalid JSON")
            continue
        observed = parse_date(payload.get("updated_at"))
        if observed and observed <= date.today() and payload.get("list"):
            print(observed.isoformat())
            return 0
        errors.append(f"{symbol}: missing/invalid observed date")

    print("Unable to resolve Longbridge CCASS date: " + "; ".join(errors), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
