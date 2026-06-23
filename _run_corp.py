"""Wrapper to run hk_cloud_scanner.py corp with .env loaded."""
import os, sys

# Load .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val

# Run scanner
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scanner'))
sys.argv = ['hk_cloud_scanner.py', 'corp']
exec(open(os.path.join(os.path.dirname(__file__), 'scanner', 'hk_cloud_scanner.py')).read())
