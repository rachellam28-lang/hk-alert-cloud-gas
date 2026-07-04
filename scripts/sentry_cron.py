"""Optional Sentry Cron Monitoring helpers.

The helpers are fail-open: if SENTRY_DSN is absent, disabled, or Sentry itself
has a transient problem, the wrapped job still runs and keeps its own exit code.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIGS: dict[str, dict[str, object]] = {
    "hk-alert-daily-refresh": {
        "schedule": {"type": "interval", "value": 1, "unit": "day"},
        "checkin_margin": 180,
        "max_runtime": 240,
        "timezone": "Asia/Hong_Kong",
    },
    "hk-alert-resume-incomplete": {
        "schedule": {"type": "interval", "value": 6, "unit": "hour"},
        "checkin_margin": 120,
        "max_runtime": 360,
        "timezone": "Asia/Hong_Kong",
    },
    "hk-alert-resume-backfill-range": {
        "schedule": {"type": "interval", "value": 6, "unit": "hour"},
        "checkin_margin": 120,
        "max_runtime": 360,
        "timezone": "Asia/Hong_Kong",
    },
    "hk-alert-corp-cron": {
        "schedule": {"type": "interval", "value": 1, "unit": "day"},
        "checkin_margin": 120,
        "max_runtime": 60,
        "timezone": "Asia/Hong_Kong",
    },
    "hk-alert-health-check": {
        "schedule": {"type": "interval", "value": 1, "unit": "day"},
        "checkin_margin": 120,
        "max_runtime": 15,
        "timezone": "Asia/Hong_Kong",
    },
}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except Exception:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _slug_env_name(slug: str, suffix: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in slug.upper())
    return f"SENTRY_CRON_{safe}_{suffix}"


def _int_env(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def monitor_config_for_slug(slug: str) -> dict[str, object] | None:
    if _truthy(os.getenv("SENTRY_CRON_DISABLE_CONFIG")):
        return None

    cfg = dict(DEFAULT_CONFIGS.get(slug, {}))
    schedule_type = os.getenv(_slug_env_name(slug, "SCHEDULE_TYPE"), "").strip()
    schedule_value = os.getenv(_slug_env_name(slug, "SCHEDULE_VALUE"), "").strip()
    schedule_unit = os.getenv(_slug_env_name(slug, "SCHEDULE_UNIT"), "").strip()
    if schedule_type and schedule_value:
        if schedule_type == "interval":
            cfg["schedule"] = {
                "type": "interval",
                "value": int(schedule_value),
                "unit": schedule_unit or "minute",
            }
        elif schedule_type == "crontab":
            cfg["schedule"] = {"type": "crontab", "value": schedule_value}

    checkin_margin = _int_env(_slug_env_name(slug, "CHECKIN_MARGIN"))
    max_runtime = _int_env(_slug_env_name(slug, "MAX_RUNTIME"))
    if checkin_margin is not None:
        cfg["checkin_margin"] = checkin_margin
    if max_runtime is not None:
        cfg["max_runtime"] = max_runtime

    timezone = (
        os.getenv(_slug_env_name(slug, "TIMEZONE"), "").strip()
        or os.getenv("SENTRY_CRON_TIMEZONE", "").strip()
    )
    if timezone:
        cfg["timezone"] = timezone

    return cfg or None


def init_sentry() -> bool:
    if _truthy(os.getenv("SENTRY_DISABLED")) or _truthy(os.getenv("SENTRY_CRON_DISABLED")):
        return False
    _load_env()
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "local"),
            release=os.getenv("SENTRY_RELEASE") or None,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or 0),
            send_default_pii=False,
        )
        sentry_sdk.set_tag("project", "hk-alert-cloud-gas")
        return True
    except Exception as exc:
        print(f"[sentry] init failed; continuing without Sentry: {exc}", flush=True)
        return False


def run_monitored_callable(slug: str, fn: Callable[[], int | None]) -> int:
    if not init_sentry():
        return int(fn() or 0)

    import sentry_sdk
    from sentry_sdk.crons import capture_checkin
    from sentry_sdk.crons.consts import MonitorStatus

    started = time.monotonic()
    check_in_id = None
    try:
        try:
            check_in_id = capture_checkin(
                monitor_slug=slug,
                status=MonitorStatus.IN_PROGRESS,
                monitor_config=monitor_config_for_slug(slug),
            )
        except Exception as exc:
            print(f"[sentry] start check-in failed; job will continue: {exc}", flush=True)
        rc = int(fn() or 0)
        try:
            capture_checkin(
                monitor_slug=slug,
                check_in_id=check_in_id,
                status=MonitorStatus.OK if rc == 0 else MonitorStatus.ERROR,
                duration=time.monotonic() - started,
            )
        except Exception as exc:
            print(f"[sentry] finish check-in failed; preserving job rc={rc}: {exc}", flush=True)
        return rc
    except BaseException as exc:
        try:
            sentry_sdk.capture_exception(exc)
            try:
                capture_checkin(
                    monitor_slug=slug,
                    check_in_id=check_in_id,
                    status=MonitorStatus.ERROR,
                    duration=time.monotonic() - started,
                )
            except Exception as checkin_exc:
                print(f"[sentry] error check-in failed: {checkin_exc}", flush=True)
            sentry_sdk.flush(timeout=5)
        except Exception as sentry_exc:
            print(f"[sentry] exception reporting failed: {sentry_exc}", flush=True)
        raise
    finally:
        sentry_sdk.flush(timeout=5)


def run_monitored_command(slug: str, command: Sequence[str]) -> int:
    return run_monitored_callable(slug, lambda: subprocess.run(command).returncode)
