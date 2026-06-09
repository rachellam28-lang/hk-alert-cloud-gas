"""
Post-backfill script: after backfill completes for a date, rebuild all outputs.
Usage: python scripts/post_backfill.py 2026-06-05
"""
import sys, subprocess, os
from pathlib import Path

PROJECT = Path(__file__).parent.parent
HOLDINGS_DIR = PROJECT / "holdings"
REPO = PROJECT
PYTHON = sys.executable  # use same Python that launched this script

def run(cmd, cwd=None):
    print(f"  RUN: {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd or HOLDINGS_DIR, capture_output=True, text=True)
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
    run([PYTHON, "scripts/regenerate_json.py", "--date", date])
    
    # 2. Detect transfers
    print("\n[2/4] Detect transfers...")
    run([PYTHON, "scripts/detect_transfers.py", "--date", date])
    
    # 3. Run gap/FVG scanner
    print("\n[3/4] Run gap/FVG scanner...")
    run([PYTHON, "scanner/gap_fvg_alert.py"], cwd=PROJECT)
    
    # 4. Git push all
    print("\n[4/4] Push to GitHub...")
    os.chdir(REPO)
    subprocess.run(["git", "add", "holdings.json", "data/"], capture_output=True)
    r = subprocess.run(["git", "commit", "-m", f"post-backfill {date}: holdings.json + alerts + transfers"], capture_output=True, text=True)
    print(f"  commit: {r.stdout.strip()}")
    subprocess.run(["git", "push"], capture_output=True)
    print("  pushed")
    
    print(f"\n=== Done: {date} ===")

if __name__ == "__main__":
    main()
