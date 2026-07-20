"""Cron launcher: loads .env, runs hk_cloud_scanner.py corp"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    print(f"[launcher] loaded .env ({env_path})")

# Ensure yfinance allowed
os.environ["ALLOW_YFINANCE"] = "1"

# Patch: set __file__ so export functions work (exec-based execution needs this)
__file__ = os.path.abspath(__file__)

# Import and run
sys.argv = ["hk_cloud_scanner.py", "corp"]
from scanner.hk_cloud_scanner import main
main()
