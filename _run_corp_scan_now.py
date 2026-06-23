"""Wrapper: load .env then run corp_scan_runner_v2.py."""
import sys, os, subprocess

proj_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(proj_dir)
sys.path.insert(0, proj_dir)
sys.path.insert(0, os.path.join(proj_dir, 'scanner'))

# Load .env
env_path = os.path.join(proj_dir, '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val

# Run the runner script
runner = os.path.join(proj_dir, 'scanner', 'corp_scan_runner_v2.py')
print(f"[runner] Executing: {runner}", flush=True)
result = subprocess.run(
    [os.path.join(proj_dir, '.venv', 'Scripts', 'python.exe'), '-u', runner],
    capture_output=True, text=True, timeout=300, cwd=proj_dir,
    env={**os.environ}
)
print(result.stdout, flush=True)
if result.stderr:
    print(f"STDERR:\n{result.stderr}", flush=True)
print(f"EXIT CODE: {result.returncode}", flush=True)
