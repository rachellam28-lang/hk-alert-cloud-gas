"""Cron-safe corp scanner launcher — loads .env + exec approach to avoid import hangs."""
import sys, os, glob

PROJ = r"C:\Users\Administrator\Desktop\automatic\ccass-debug"
os.chdir(PROJ)

# 1. Clear stale .pyc
for root, dirs, files in os.walk(PROJ):
    for f in files:
        if f.endswith('.pyc'):
            os.remove(os.path.join(root, f))
print("[cron] Cleared .pyc files", flush=True)

# 2. Load .env
env_path = os.path.join(PROJ, '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val
    print(f"[cron] Loaded .env, TELEGRAM_TOKEN={'SET' if os.environ.get('TELEGRAM_TOKEN') else 'MISSING'}", flush=True)
else:
    print("[cron] WARNING: .env not found", flush=True)

# 3. Run hk_cloud_scanner.py corp via exec
script_path = os.path.join(PROJ, 'scanner', 'hk_cloud_scanner.py')
sys.path.insert(0, os.path.join(PROJ, 'scanner'))
sys.path.insert(0, PROJ)
sys.argv = [script_path, 'corp']

with open(script_path, 'r', encoding='utf-8') as f:
    code = f.read()

exec_globals = {
    '__name__': '__main__',
    '__file__': script_path,
    '__builtins__': __builtins__,
}

print(f"[cron] Starting hk_cloud_scanner.py corp at {__import__('datetime').datetime.now()}", flush=True)
exec(code, exec_globals)
print(f"[cron] hk_cloud_scanner.py corp finished at {__import__('datetime').datetime.now()}", flush=True)
