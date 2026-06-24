"""
Minimal launcher for hk_cloud_scanner.py that avoids import-system hangs
and correctly sets __file__ for export functions.

Lives at PROJECT ROOT (not scanner/). Usage:
  python _run_scanner_exec.py corp|ipo|poc|year_open|all

Why exec instead of import:
- `import hk_cloud_scanner` triggers module-level initialization
  (yfinance, matplotlib, TelegramPusher, local_alert_store init)
  which can hang on Windows/git-bash.
- `exec()` loads and runs the script directly, bypassing the import system.
- Must set `__file__` in exec globals — otherwise export_breakthroughs_json()
  and _update_announcements_json() crash with NameError.
"""
import sys, os

# ── Setup ──────────────────────────────────────────────────────────────────
# This launcher lives at PROJECT ROOT. Adjust paths accordingly.
proj_dir = os.path.dirname(os.path.abspath(__file__))
scanner_dir = os.path.join(proj_dir, 'scanner')
sys.path.insert(0, scanner_dir)
sys.path.insert(0, proj_dir)
os.chdir(proj_dir)  # CWD = project root — needed by data/, ccass/ references

script_path = os.path.join(scanner_dir, 'hk_cloud_scanner.py')
mode = sys.argv[1] if len(sys.argv) > 1 else 'corp'

# ── Load .env (scanner does NOT auto-load it) ─────────────────────────────
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

# ── Execute ────────────────────────────────────────────────────────────────
with open(script_path, 'r', encoding='utf-8') as f:
    code = f.read()

exec_globals = {
    '__name__': '__main__',
    '__file__': script_path,  # ← CRITICAL: export functions need this
    '__builtins__': __builtins__,
}

sys.argv = [script_path, mode]

print(f"[exec-runner] Running hk_cloud_scanner.py {mode}...", flush=True)
exec(code, exec_globals)
print(f"[exec-runner] Complete.", flush=True)
