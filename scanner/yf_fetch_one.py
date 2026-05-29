"""Subprocess-based yfinance fetcher — used by hk_cloud_scanner.py to prevent hangs.

Called via subprocess.run(timeout=N) so OS-level SIGKILL can terminate any C-level I/O hang
that yfinance's internal timeout cannot handle.

Usage:
    python yf_fetch_one.py <ticker> <interval> <period> [timeout_secs]
    python yf_fetch_one.py 0700.HK 1d 1y

Outputs JSON with columns + data on success, empty JSON on failure.
"""
from __future__ import annotations

import json
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf


def main() -> None:
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: yf_fetch_one.py <ticker> <interval> <period> [timeout_secs]"}))
        sys.exit(1)

    ticker = sys.argv[1]
    interval = sys.argv[2]
    period = sys.argv[3]
    timeout = float(sys.argv[4]) if len(sys.argv) > 4 else 15.0

    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=timeout,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    if raw is None or raw.empty:
        print(json.dumps({"columns": [], "data": []}))
        return

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = ["_".join(str(c) for c in col).strip("_") for col in raw.columns]

    # Reset index to get Date as a column
    df = raw.reset_index()
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str)

    result = {
        "columns": list(df.columns),
        "data": df.to_dict(orient="records"),
    }
    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
