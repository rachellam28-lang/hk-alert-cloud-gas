"""
Post-backfill script: after backfill completes for a date, rebuild all outputs.
Usage: python scripts/post_backfill.py 2026-06-05
"""
import sys, subprocess
from pathlib import Path

CCASS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CCASS_DIR.parent
PYTHON = sys.executable  # use same Python that launched this script

def run(cmd, cwd):
    print(f"  RUN: {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"  FAIL (rc={r.returncode}): {r.stderr[-300:]}")
    else:
        print(f"  OK: {r.stdout.strip()[-200:]}" if r.stdout.strip() else "  OK")
    return r.returncode == 0

def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    if not date:
        print("Usage: python scripts/post_backfill.py YYYY-MM-DD")
        sys.exit(1)
    
    print(f"=== Post-backfill for {date} ===\n")
    
    # 1. Regenerate holdings.json
    print("[1/4] Regenerate holdings.json...")
    if not run([PYTHON, "scripts/regenerate_json.py", "--date", date], cwd=CCASS_DIR):
        sys.exit(1)
    
    # 2. Detect transfers
    print("\n[2/4] Detect transfers...")
    if not run([PYTHON, "scripts/detect_transfers.py", "--date", date], cwd=CCASS_DIR):
        sys.exit(1)
    
    # 3. Audit gate — verify data integrity BEFORE pushing
    print("\n[3/4] Audit gate...")
    gate_cmd = [PYTHON, "scripts/audit_gate.py", "--date", date, "--warn-only"]
    r = subprocess.run(gate_cmd, cwd=CCASS_DIR, capture_output=True, text=True)
    if r.returncode == 1:
        print(f"  FAIL: audit gate blocked\n{r.stdout[-500:]}")
        sys.exit(1)
    elif r.returncode == 2:
        print(f"  WARN: audit gate warnings (proceeding with --warn-only)\n{r.stdout[-300:]}")
    else:
        print("  PASS: audit gate ok")
    
    # 4. Deploy to Cloudflare Pages (wrangler, bypasses GitHub)
    print("\n[4/4] Deploy to Cloudflare Pages...")
    deploy_cmd = [PYTHON, "scripts/_deploy_cf.py"]
    if not run(deploy_cmd, cwd=CCASS_DIR):
        sys.exit(1)
    
    print(f"\n=== Done: {date} ===")

if __name__ == "__main__":
    main()
