"""Cron launcher v2: loads .env, runs corp_scan_runner_v2.py (fast, 10-20s)"""
import os, sys

# Load .env manually (Windows/git-bash doesn't auto-source)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                os.environ[key] = val
    print(f"[launcher] loaded .env")

# Ensure yfinance allowed + holdings/ exists
os.environ["ALLOW_YFINANCE"] = "1"
holdings_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings")
os.makedirs(holdings_dir, exist_ok=True)

# Run the cron-safe fast scanner
from scanner.corp_scan_runner_v2 import main
main()
