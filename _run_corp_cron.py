"""Cron-safe corp scanner launcher.

Uses this repository as PROJECT. CCASS/corp alerts require the dedicated
CCASS Telegram bot unless CCASS_TELEGRAM_REQUIRE_DEDICATED is explicitly unset.
"""
from __future__ import annotations

import os
import runpy
import sys
from datetime import datetime
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
SCANNER_DIR = PROJECT / "scanner"
ENV_PATH = PROJECT / ".env"


def _load_env(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    print(f"[cron] Loaded .env from {path}", flush=True)
    return True


def _first_env(*names: str) -> str:
    for name in names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _wire_ccass_bot() -> None:
    token = _first_env(
        "CCASS_TELEGRAM_TOKEN",
        "CCASS_TELEGRAM_BOT_TOKEN",
        "CCASS_TG_BOT_TOKEN",
        "ALERT_TELEGRAM_TOKEN",
        "ALERT_TG_BOT_TOKEN",
    )
    chat = _first_env(
        "CCASS_TELEGRAM_CHAT_ID",
        "CCASS_TG_CHAT_ID",
        "ALERT_TELEGRAM_CHAT_ID",
        "ALERT_TG_CHAT_ID",
    )
    os.environ.setdefault("CCASS_TELEGRAM_REQUIRE_DEDICATED", "1")
    if token:
        os.environ["TELEGRAM_TOKEN"] = token
    if chat:
        os.environ["TELEGRAM_CHAT_ID"] = chat
    print(
        "[cron] CCASS bot "
        f"token={'SET' if token else 'MISSING'} chat={'SET' if chat else 'MISSING'}",
        flush=True,
    )


os.chdir(PROJECT)

for root, _dirs, files in os.walk(PROJECT):
    for filename in files:
        if filename.endswith(".pyc"):
            try:
                os.remove(Path(root) / filename)
            except OSError:
                pass
print("[cron] Cleared .pyc files", flush=True)

loaded = _load_env(ENV_PATH)
if not loaded:
    print(f"[cron] WARNING: .env not found at {ENV_PATH}", flush=True)

_wire_ccass_bot()

for path in (PROJECT, SCANNER_DIR):
    ps = str(path)
    if ps not in sys.path:
        sys.path.insert(0, ps)

script_path = SCANNER_DIR / "hk_cloud_scanner.py"
sys.argv = [str(script_path), "corp"]


def main() -> int:
    print(f"[cron] Starting hk_cloud_scanner.py corp at {datetime.now()}", flush=True)
    runpy.run_path(str(script_path), run_name="__main__")
    print(f"[cron] hk_cloud_scanner.py corp finished at {datetime.now()}", flush=True)
    return 0


if __name__ == "__main__":
    from scripts.sentry_cron import run_monitored_callable

    raise SystemExit(run_monitored_callable("hk-alert-corp-cron", main))
