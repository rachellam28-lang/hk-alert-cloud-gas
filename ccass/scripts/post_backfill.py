"""
Post-backfill script: after backfill completes for a date, rebuild all outputs.
Usage: python scripts/post_backfill.py 2026-06-05
"""
import os, sys, subprocess
from pathlib import Path

CCASS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CCASS_DIR.parent
PYTHON = sys.executable  # use same Python that launched this script

def run(cmd, cwd):
    print(f"  RUN: {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
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
    print("[1/3] Regenerate holdings.json...")
    if not run([PYTHON, "scripts/regenerate_json.py", "--date", date], cwd=CCASS_DIR):
        sys.exit(1)
    
    # 2. Detect transfers
    print("\n[2/3] Detect transfers...")
    if not run([PYTHON, "scripts/detect_transfers.py", "--date", date], cwd=CCASS_DIR):
        sys.exit(1)

    # 3. Audit gate before publishing
    print("\n[3/4] Audit gate...")
    if not run([PYTHON, "scripts/audit_gate.py", "--min-coverage", "99.0"], cwd=CCASS_DIR):
        sys.exit(1)

    # 4. Commit locally. GitHub push is blocked by default.
    print("\n[4/4] Commit local outputs...")
    subprocess.run(["git", "add", "holdings.json", "data/"], cwd=REPO_ROOT, check=True, capture_output=True)
    r = subprocess.run(
        ["git", "commit", "-m", f"post-backfill {date}: holdings.json + alerts + transfers"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        if "nothing to commit" in (r.stdout + r.stderr).lower():
            print("  commit: nothing to commit")
        else:
            print(f"  commit failed: {r.stderr.strip()[-300:]}")
            sys.exit(r.returncode)
    else:
        print(f"  commit: {r.stdout.strip()}")

    if os.environ.get("ALLOW_GITHUB_WRITE") != "1":
        print("  push skipped: GitHub writes are blocked by default. Set ALLOW_GITHUB_WRITE=1 only if explicitly requested.")
        print(f"\n=== Done: {date} ===")
        return

    push = subprocess.run(["git", "push"], cwd=REPO_ROOT, capture_output=True, text=True)
    if push.returncode != 0:
        print(f"  push failed: {push.stderr.strip()[-300:]}")
        sys.exit(push.returncode)
    print("  pushed")

    print(f"\n=== Done: {date} ===")

if __name__ == "__main__":
    main()
