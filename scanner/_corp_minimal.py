"""Minimal corp scan — only what's needed for today, with per-request timeout logging."""
import sys, os, time

scanner_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(scanner_dir)
sys.path.insert(0, scanner_dir)
sys.path.insert(0, parent_dir)
os.chdir(scanner_dir)

# Set minimal range to speed up
os.environ['ANNOUNCEMENT_RANGE_DAYS'] = '1'

# Use exec with __file__ set
script_path = os.path.join(scanner_dir, 'hk_cloud_scanner.py')
with open(script_path, 'r', encoding='utf-8') as f:
    code = f.read()

exec_globals = {
    '__name__': '__main__',
    '__file__': script_path,
    '__builtins__': __builtins__,
}

sys.argv = [script_path, 'corp']

start = time.time()
print(f"[scan] Starting at {time.strftime('%H:%M:%S')} with ANNOUNCEMENT_RANGE_DAYS=1", flush=True)
exec(code, exec_globals)
elapsed = time.time() - start
print(f"[scan] Completed in {elapsed:.1f}s", flush=True)
