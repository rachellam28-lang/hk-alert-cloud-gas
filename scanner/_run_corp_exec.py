"""Minimal corp scan runner — avoids import hang, fixes __file__."""
import sys, os, time

scanner_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(scanner_dir)
sys.path.insert(0, scanner_dir)
sys.path.insert(0, parent_dir)
os.chdir(scanner_dir)

# Read the script
script_path = os.path.join(scanner_dir, 'hk_cloud_scanner.py')
with open(script_path, 'r', encoding='utf-8') as f:
    code = f.read()

# Set up the execution environment
exec_globals = {
    '__name__': '__main__',
    '__file__': script_path,
    '__builtins__': __builtins__,
}

# Set sys.argv for corp mode
sys.argv = [script_path, 'corp']

print("[runner] Starting corp scan via exec...", flush=True)
exec(code, exec_globals)
print("[runner] Corp scan complete.", flush=True)
