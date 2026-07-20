#!/usr/bin/env python
"""Cron launcher — loads .env, runs corp_scan_runner_v2.py."""
import os, sys

# Load .env (Python-safe, avoids git-bash source issues)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ[key] = val

print("[launcher] .env loaded", flush=True)

# Ensure holdings/ dir exists for local_alert_store
holdings_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings")
os.makedirs(holdings_dir, exist_ok=True)
db_path = os.path.join(holdings_dir, "holdings.db")
if not os.path.exists(db_path):
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ccass", "ccass.db")
    if os.path.exists(src):
        import shutil
        shutil.copy2(src, db_path)
        print(f"[launcher] copied holdings.db from ccass/ccass.db", flush=True)

# Import and run
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner"))
from corp_scan_runner_v2 import main as run_scan

print("[launcher] running corp_scan_runner_v2.main()...", flush=True)
run_scan()
print("[launcher] done", flush=True)
