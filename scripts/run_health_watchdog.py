"""Run the CCASS health watchdog end to end.

This wrapper preserves hard failures for real data-health problems while keeping
notification or deploy network hiccups fail-open for cron stability.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
HEALTH_CMD = [str(PYTHON), "scripts/health_check.py", "--telegram"]
DEPLOY_CMD = [
    str(PYTHON),
    "ccass/scripts/_deploy_cf.py",
    "--project",
    "hk-alert-cloud-gas",
    "--branch",
    "main",
]
NETWORK_MARKERS = (
    "WinError 10053",
    "Connection aborted",
    "ConnectionResetError",
    "timed out",
    "Temporary failure",
    "TLS",
    "ECONNRESET",
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _emit_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)


def _is_network_noise(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in NETWORK_MARKERS)


def main() -> int:
    try:
        health = _run(HEALTH_CMD)
    except OSError as exc:
        if _is_network_noise(str(exc)):
            print(f"[watchdog] health check launch hit transient network noise: {exc}")
            return 0
        raise

    _emit_output(health)
    health_text = f"{health.stdout or ''}\n{health.stderr or ''}"
    if health.returncode != 0:
        print(f"[watchdog] health check reported data issues rc={health.returncode}", file=sys.stderr)
        return health.returncode

    try:
        deploy = _run(DEPLOY_CMD)
    except OSError as exc:
        if _is_network_noise(str(exc)):
            print(f"[watchdog] health deploy skipped on transient network noise: {exc}")
            return 0
        raise

    _emit_output(deploy)
    deploy_text = f"{deploy.stdout or ''}\n{deploy.stderr or ''}"
    if deploy.returncode == 0:
        return 0

    if _is_network_noise(deploy_text):
        print("[watchdog] health deploy hit transient network noise; keeping cron green")
        return 0

    print(
        f"[watchdog] health deploy failed rc={deploy.returncode}; public health may be stale",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
