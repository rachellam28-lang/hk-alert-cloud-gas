#!/usr/bin/env python3
"""
Codex 全自動審查流水線 — 一句 trigger，A review → auto-apply → B verify → commit
用法: python codex_pipeline.py "檢查 ccass.html 有冇 mobile bug" C:/path/to/project [--auto-commit]
"""

import subprocess, sys, os, datetime, tempfile, re, shutil

PROJECT = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
PROMPT = sys.argv[1] if len(sys.argv) > 1 else "Review this project for bugs"
AUTO_COMMIT = "--auto-commit" in sys.argv

os.chdir(PROJECT)

def run(cmd, timeout=600):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=PROJECT)
    return (result.stdout + result.stderr), result.returncode

def step(label):
    print(f"\n{'═'*60}\n  {label}\n{'═'*60}\n")

# ═══════════════════════════════════════════════════════════
# Step 0: Prep
# ═══════════════════════════════════════════════════════════
step("STEP 0: 準備 git branch")
run("git rev-parse --is-inside-work-tree 2>&1")
BRANCH = f"fix/codex-auto-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
run(f"git checkout -b {BRANCH} 2>&1 || git checkout {BRANCH} 2>&1 || true")
print(f"✅ Branch: {BRANCH}\n   Project: {PROJECT}")

# ═══════════════════════════════════════════════════════════
# Step 1: Codex PASS 1 — Review + 出 fix
# ═══════════════════════════════════════════════════════════
step("STEP 1: 👷 Codex PASS 1 (A LLM — 搵 bugs + 出 fix)")

pf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
pf.write(f"""TASK: {PROMPT}

OUTPUT FORMAT — for each issue, output EXACTLY this block:

<<<FIX>>>
FILE: relative/path/to/file
FIND: <<<the exact lines to replace>>>
REPLACE: <<<the corrected lines>>>
REASON: <<<why this fixes the bug>>>
<<<END>>>

IMPORTANT RULES:
- FIND must be the EXACT text from the file (copy-paste precision)
- REPLACE must be the corrected version
- Output ALL fixes you find — don't stop after finding 1-2
- If sandbox is read-only, that's fine — I'll apply the patches
""")
pf.close()

out, rc = run(f'cat "{pf.name}" | codex exec --sandbox read-only', timeout=600)
os.unlink(pf.name)

# Save raw output
with open(os.path.join(PROJECT, ".codex-pass1.log"), 'w', encoding='utf-8') as f:
    f.write(out)

# Extract FIX blocks
fixes = re.findall(r'<<<FIX>>>\s*FILE:\s*(.+?)\s*FIND:\s*<<<(.+?)>>>\s*REPLACE:\s*<<<(.+?)>>>\s*REASON:\s*(.+?)\s*<<<END>>>', out, re.DOTALL)
print(f"\n📋 Codex 搵到 {len(fixes)} 個 fix")
if len(fixes) == 0:
    print("⚠️ No FIX blocks found. Check .codex-pass1.log for raw output.")
    print("\nCodex raw output (first 2000 chars):")
    print(out[:2000])

# ═══════════════════════════════════════════════════════════
# Step 2: Auto-apply fixes
# ═══════════════════════════════════════════════════════════
step(f"STEP 2: 🔧 Auto-apply {len(fixes)} fixes")

applied = 0
for i, (fpath, find_str, replace_str, reason) in enumerate(fixes):
    fpath = fpath.strip()
    find_str = find_str.strip()
    replace_str = replace_str.strip()
    reason = reason.strip()
    
    full_path = os.path.join(PROJECT, fpath)
    if not os.path.exists(full_path):
        print(f"  [{i+1}] ⚠️ SKIP: File not found: {fpath}")
        continue
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if find_str not in content:
        # Try fuzzy match
        lines = find_str.split('\n')
        if len(lines) > 1:
            # Try matching first+last lines
            first = lines[0].strip()
            last = lines[-1].strip()
            if first in content and last in content:
                start = content.index(first)
                end = content.index(last, start) + len(last)
                find_str = content[start:end]
                print(f"  [{i+1}] 🔍 Fuzzy matched: {fpath}")
            else:
                print(f"  [{i+1}] ⚠️ SKIP: FIND block not matched in {fpath}")
                print(f"       Reason: {reason[:80]}")
                continue
        else:
            print(f"  [{i+1}] ⚠️ SKIP: FIND block not found in {fpath}")
            continue
    
    content = content.replace(find_str, replace_str, 1)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    applied += 1
    print(f"  [{i+1}] ✅ APPLIED: {fpath} — {reason[:60]}")

print(f"\n✅ Applied: {applied}/{len(fixes)}")

# ═══════════════════════════════════════════════════════════
# Step 3: Codex PASS 2 — Verify
# ═══════════════════════════════════════════════════════════
step("STEP 3: 🔍 Codex PASS 2 (B LLM — verify fixes)")

pf2 = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
pf2.write(f"""We just applied {applied} fixes to this project. 

ORIGINAL TASK: {PROMPT}

Verify that:
1. Each fix was applied correctly (check the actual files)
2. No new bugs were introduced
3. The original issues are resolved

Output: PASS/FAIL for each fix. If any FAIL, explain what's still wrong.
""")
pf2.close()

out2, rc2 = run(f'cat "{pf2.name}" | codex exec --sandbox read-only', timeout=600)
os.unlink(pf2.name)

with open(os.path.join(PROJECT, ".codex-pass2.log"), 'w', encoding='utf-8') as f:
    f.write(out2)

print(out2[:3000])

# ═══════════════════════════════════════════════════════════
# Step 4: Git commit + push
# ═══════════════════════════════════════════════════════════
if AUTO_COMMIT:
    step("STEP 4: 📦 Commit + Push")
    run("git add -A")
    out_diff, _ = run("git diff --cached --stat")
    print(out_diff)
    if applied > 0:
        commit_msg = f"fix: Codex auto-review — {applied} fixes\n\n{PROMPT}\n\nBranch: {BRANCH}"
        run(f'git commit -m "{commit_msg}"')
        run(f"git push origin {BRANCH}")
        print(f"✅ Pushed to {BRANCH}")
    else:
        print("⚠️ No changes to commit")
else:
    step("STEP 4: ⏸️  Skipped commit (use --auto-commit to enable)")

# ═══════════════════════════════════════════════════════════
step("✅ DONE! Pipeline complete")
print(f"""
Summary:
  PASS 1 (A LLM): {len(fixes)} issues found
  Applied:        {applied}/{len(fixes)} fixes
  PASS 2 (B LLM): Verify complete (see .codex-pass2.log)
  Commit:         {'✅ Pushed to ' + BRANCH if AUTO_COMMIT else '⏸️ Skipped'}

Logs:
  .codex-pass1.log  — Codex review output
  .codex-pass2.log  — Verification output
""")
