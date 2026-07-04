"""HK Cloud Scanner - corp-actions cron launcher.

Runs from this repository only. CCASS/corp alerts use the dedicated CCASS
Telegram bot env by default, so this cron cannot silently reuse Hermes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
SCANNER_DIR = PROJECT / "scanner"
ENV_PATH = PROJECT / ".env"


def _load_env(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
    except Exception:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    print(f"[dotenv] loaded {path}", flush=True)
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
        "[telegram] CCASS bot "
        f"token={'SET' if token else 'MISSING'} chat={'SET' if chat else 'MISSING'}",
        flush=True,
    )


loaded = _load_env(ENV_PATH)
if not loaded:
    print(f"[dotenv] no .env at {ENV_PATH}", flush=True)

_wire_ccass_bot()

os.chdir(PROJECT)
for path in (PROJECT, SCANNER_DIR):
    ps = str(path)
    if ps not in sys.path:
        sys.path.insert(0, ps)

# Corp-only mode settings.
os.environ.setdefault("MAX_STOCKS", "0")
os.environ.setdefault("VOLUME_MULTIPLIER", "1.5")
os.environ.setdefault("VOLUME_AVG_DAYS", "20")
os.environ.setdefault("ANNOUNCEMENT_RANGE_DAYS", "7")

# Skip breakthrough exports for this cron path; daily_refresh exports them.
import scanner.breakthrough_detector as btd

btd.export_breakthroughs_json = lambda: print("[breakthrough] export skipped (cron)")
btd.add_prices_from_announcements = lambda anns: 0

from scanner.hk_cloud_scanner import run_corp_actions


def main() -> int:
    run_corp_actions()
    return 0


if __name__ == "__main__":
    from scripts.sentry_cron import run_monitored_callable

    raise SystemExit(run_monitored_callable("hk-alert-corp-cron", main))
