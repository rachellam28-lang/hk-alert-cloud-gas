#!/usr/bin/env python
"""
Start the local futu-opend-rs gateway found on this machine.

Usage:
    python scripts/start_futu_opend_rs.py
    python scripts/start_futu_opend_rs.py --verify-code 123456
    python scripts/start_futu_opend_rs.py --background --verify-code 123456
    python scripts/start_futu_opend_rs.py --stop-existing
    python scripts/start_futu_opend_rs.py --stop-only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from futu_env import get_local_futu_opend_rs_info, load_repo_env, probe_futu_socket


ROOT = Path(__file__).resolve().parent.parent


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _tail_text(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def list_running_futu_opend() -> list[dict]:
    ps = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process | Where-Object { $_.ProcessName -eq 'futu-opend' } | "
            "Select-Object Id, ProcessName, Path | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    raw = (ps.stdout or "").strip()
    if not raw:
        return []
    try:
        import json

        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return []


def stop_running_futu_opend() -> int:
    procs = list_running_futu_opend()
    for proc in procs:
        pid = proc.get("Id")
        if pid:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {int(pid)} -Force"],
                capture_output=True,
                text=True,
            )
    return len(procs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-code", help="SMS/device verification code for non-interactive start")
    parser.add_argument("--background", action="store_true", help="start detached in background")
    parser.add_argument("--stop-existing", action="store_true", help="stop existing futu-opend processes first")
    parser.add_argument("--stop-only", action="store_true", help="stop existing futu-opend processes and exit")
    args = parser.parse_args()
    load_repo_env(ROOT)

    info = get_local_futu_opend_rs_info()
    if not info:
        print("No local futu-opend-rs install found under %USERPROFILE%\\futu-opend", file=sys.stderr)
        return 2

    if args.stop_existing:
        count = stop_running_futu_opend()
        if count:
            print(f"Stopped {count} existing futu-opend process(es)")
        time.sleep(1)
    if args.stop_only:
        if not args.stop_existing:
            count = stop_running_futu_opend()
            if count:
                print(f"Stopped {count} existing futu-opend process(es)")
            else:
                print("No running futu-opend process found")
        return 0

    exe = Path(info["exe"])
    cwd = Path(info["root"])
    stdout_log = Path(info["stdout_log"])
    stderr_log = Path(info["stderr_log"])

    cmd = [str(exe)]
    login_account = str(os.environ.get("FUTU_ACCOUNT", "")).strip()
    if login_account:
        cmd.extend(["--login-account", login_account])
    if args.verify_code:
        cmd.extend(["--verify-code", args.verify_code])

    print(f"Using gateway: {exe}")
    print(f"Working dir: {cwd}")
    if login_account:
        print(f"Login account override: {login_account}")
    if args.verify_code:
        print("Verification code supplied on command line")

    if args.background:
        if not args.verify_code:
            print("Background mode without --verify-code only works if the gateway can already log in non-interactively.")
        arg_list = ", ".join([_ps_quote(part) for part in cmd[1:]])
        ps_cmd = (
            f"$exe = {_ps_quote(str(exe))}; "
            f"$wd = {_ps_quote(str(cwd))}; "
            f"$out = {_ps_quote(str(stdout_log))}; "
            f"$err = {_ps_quote(str(stderr_log))}; "
            f"$args = @({arg_list}); "
            "Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $wd "
            "-WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        time.sleep(6)
        ok, detail = probe_futu_socket("127.0.0.1", 11111, 2.0)
        print(f"Background start socket: {'OK' if ok else 'FAIL'} - {detail}")
        print(f"stderr log: {stderr_log}")
        if not ok:
            tail = _tail_text(stderr_log, lines=12)
            if tail:
                print("\nRecent stderr:")
                print(tail)
        return 0 if ok else 1

    print("Starting in foreground. If SMS/device verification is required, enter it in this terminal.")
    completed = subprocess.run(cmd, cwd=str(cwd))
    return int(completed.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
