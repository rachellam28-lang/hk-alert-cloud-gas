"""Load .env, then export all alerts via local_alert_store."""
import os, sys

proj_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(proj_dir, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

sys.path.insert(0, os.path.join(proj_dir, "scanner"))
os.chdir(proj_dir)

from local_alert_store import export_all
export_all()
