"""Alert engine: 偵測異常 + 經 Telegram 通知。

Throttle 規則（FATAL-001）：
- 每條 ≥ 3 秒
- 單次 batch ≤ 20 條
- 超過 50 條淨係 send summary
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from src.db import get_conn
from src.logger import setup_logger

load_dotenv()
logger = setup_logger("alerts")

# ── Dopamine integration ────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DOPAMINE_PATH = _DATA_DIR / "dopamine.json"

DEFAULT_SPIKE_THRESHOLD = 5.0
DEFAULT_CONSECUTIVE_DAYS = 3


def load_dopamine_thresholds() -> tuple[float, int]:
    """Read dopamine.json and return (spike_threshold_pct, consecutive_days).
    Falls back to defaults if file missing or stale (>24h).
    """
    try:
        if not _DOPAMINE_PATH.exists():
            return DEFAULT_SPIKE_THRESHOLD, DEFAULT_CONSECUTIVE_DAYS
        with open(_DOPAMINE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Check freshness (within 24h)
        ts = data.get("date", "")
        try:
            dt = datetime.fromisoformat(ts)
            age_h = (datetime.now() - dt).total_seconds() / 3600
            if age_h > 24:
                logger.info("Dopamine data stale (%.1fh old), using defaults", age_h)
                return DEFAULT_SPIKE_THRESHOLD, DEFAULT_CONSECUTIVE_DAYS
        except (ValueError, TypeError):
            pass
        spike = float(data.get("spike_threshold_pct", DEFAULT_SPIKE_THRESHOLD))
        cons = int(data.get("consecutive_days", DEFAULT_CONSECUTIVE_DAYS))
        logger.info(
            "Dopamine: %s (score=%.1f) → spike≥%.1f%%, cons≥%dd",
            data.get("level", "normal"),
            data.get("dopamine", 50),
            spike,
            cons,
        )
        return spike, cons
    except Exception as e:
        logger.warning("Failed to load dopamine: %s, using defaults", e)
        return DEFAULT_SPIKE_THRESHOLD, DEFAULT_CONSECUTIVE_DAYS

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_CCASS_TOKEN_ENV = (
    "CCASS_TELEGRAM_TOKEN",
    "CCASS_TELEGRAM_BOT_TOKEN",
    "CCASS_TG_BOT_TOKEN",
    "ALERT_TELEGRAM_TOKEN",
    "ALERT_TG_BOT_TOKEN",
)
_CCASS_CHAT_ENV = (
    "CCASS_TELEGRAM_CHAT_ID",
    "CCASS_TG_CHAT_ID",
    "ALERT_TELEGRAM_CHAT_ID",
    "ALERT_TG_CHAT_ID",
)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _first_env(*names: str) -> str:
    for name in names:
        val = os.getenv(name, "").strip()
        if val:
            return val
    return ""


def _telegram_token() -> str:
    dedicated = _first_env(*_CCASS_TOKEN_ENV)
    if dedicated or _first_env(*_CCASS_CHAT_ENV) or _truthy_env("CCASS_TELEGRAM_REQUIRE_DEDICATED"):
        return dedicated
    return _first_env("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN")


def _telegram_chat_id(default: Optional[str] = None) -> str:
    if default:
        return default
    dedicated = _first_env(*_CCASS_CHAT_ENV)
    if dedicated or _first_env(*_CCASS_TOKEN_ENV) or _truthy_env("CCASS_TELEGRAM_REQUIRE_DEDICATED"):
        return dedicated
    return _first_env("TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID", "TG_CHAT_ID")


def send_telegram(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    max_retries: int = 3,
) -> bool:
    """Send 一條 message with retry on 429. 回傳 True 如果成功。"""
    token = _telegram_token()
    if not token:
        logger.error("TELEGRAM_TOKEN missing — cannot send")
        return False
    if chat_id is None:
        chat_id = _telegram_chat_id()
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID missing")
        return False

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=token),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 30)
                logger.warning("Telegram 429, sleeping %ds (attempt %d/%d)", retry_after, attempt + 1, max_retries)
                time.sleep(retry_after + 1)
                continue
            logger.error("Telegram %d: %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as e:
            logger.error("Telegram send failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # exponential backoff
    return False


def detect_alerts(
    target_date: date,
    spike_threshold_pct: Optional[float] = None,
    consecutive_days: Optional[int] = None,
    consecutive_min_daily_pct: float = 1.0,
) -> list[dict]:
    """Trend alerts disabled.

    We keep the function as a no-op so daily refresh / Telegram wiring can stay
    intact while the trend pipeline is retired.
    """
    logger.info("Trend alerts disabled — returning no alerts for %s", target_date)
    return []


def format_alert(a: dict) -> str:
    code = a["stock_code"]
    name = a["stock_name"]
    atype = a["alert_type"]

    if atype == "spike_up":
        emoji = "🟢⬆️"
        head = f"HOLDINGS Spike UP"
    elif atype == "spike_down":
        emoji = "🔴⬇️"
        head = f"HOLDINGS Spike DOWN"
    elif atype == "consecutive_buy":
        emoji = "🟢🔥"
        head = f"Consecutive Buy ({a.get('streak_days')}日)"
    else:
        emoji = "🔴❄️"
        head = f"Consecutive Sell ({a.get('streak_days')}日)"

    delta_5d = a.get("delta_5d_pct", 0)
    delta_20d = a.get("delta_20d_pct", 0)
    total_pct = a.get("total_pct", 0)

    return (
        f"{emoji} <b>{head}</b>\n"
        f"<b>{code}</b> {name}\n"
        f"5日Δ: {delta_5d:+.2f}%  |  20日Δ: {delta_20d:+.2f}%\n"
        f"HOLDINGS 總持倉: {total_pct:.2f}%"
    )


def send_alerts(
    alerts: list[dict],
    target_date: date,
    throttle_seconds: float = 3.0,
    max_per_batch: int = 20,
    summary_only_threshold: int = 50,
) -> int:
    """
    Send alerts with throttling (FATAL-001).
    Returns: 實際 send 出嘅數量。
    """
    if not alerts:
        logger.info("No alerts to send")
        return 0

    n = len(alerts)
    logger.info("Preparing to send %d alerts", n)

    # FATAL-001: 太多就淨係 send summary
    if n > summary_only_threshold:
        logger.warning("Alert count %d > %d, sending summary only", n, summary_only_threshold)
        summary = _format_summary(alerts, target_date)
        if send_telegram(summary):
            _log_summary_sent(alerts, target_date)
            return 1
        return 0

    sent_count = 0
    to_send = alerts[:max_per_batch]
    overflow = alerts[max_per_batch:]

    for a in to_send:
        text = format_alert(a)
        if send_telegram(text):
            _log_alert_sent(a, target_date)
            sent_count += 1
        time.sleep(throttle_seconds)

    if overflow:
        logger.info("Batch cap reached, queueing %d alerts as summary", len(overflow))
        overflow_text = f"⚠️ 另外 {len(overflow)} 條 alert 未 send（batch cap）：\n" + ", ".join(
            f"{a['stock_code']}" for a in overflow[:30]
        )
        send_telegram(overflow_text)

    return sent_count


def _format_summary(alerts: list[dict], target_date: date) -> str:
    by_type = {}
    for a in alerts:
        by_type.setdefault(a["alert_type"], []).append(a)

    lines = [f"📊 <b>HOLDINGS 異動 Summary</b> ({target_date})"]
    lines.append(f"總共 <b>{len(alerts)}</b> 條 alert（超過閾值，淨係 send summary）\n")
    for atype, items in by_type.items():
        lines.append(f"<b>{atype}</b>: {len(items)} 隻")
        # Top 5 by delta
        top = sorted(items, key=lambda x: abs(x.get("delta_5d_pct", 0)), reverse=True)[:5]
        for a in top:
            d = a.get("delta_5d_pct", 0)
            lines.append(f"  • {a['stock_code']} {a['stock_name']}: {d:+.2f}%")
        lines.append("")
    return "\n".join(lines)


def _log_alert_sent(a: dict, target_date: date) -> None:
    now_iso = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO alerts_sent
                 (stock_code, trade_date, alert_type, message, sent_at, channel)
               VALUES (?, ?, ?, ?, ?, 'telegram')""",
            (
                a["stock_code"],
                target_date.strftime("%Y-%m-%d"),
                a["alert_type"],
                format_alert(a),
                now_iso,
            ),
        )


def _log_summary_sent(alerts: list[dict], target_date: date) -> None:
    now_iso = datetime.utcnow().isoformat()
    with get_conn() as conn:
        for a in alerts:
            conn.execute(
                """INSERT OR IGNORE INTO alerts_sent
                     (stock_code, trade_date, alert_type, message, sent_at, channel)
                   VALUES (?, ?, ?, ?, ?, 'telegram_summary')""",
                (
                    a["stock_code"],
                    target_date.strftime("%Y-%m-%d"),
                    a["alert_type"],
                    "(in summary)",
                    now_iso,
                ),
            )


def send_event_alerts(events: list[dict], trade_date: date) -> int:
    """Send HOLDINGS event alerts (deposit/transfer) via Telegram.
    Returns number of alerts sent. Stub — implement if Telegram push is needed.
    """
    return 0


def scan_alerts_for_date(target_date: date) -> int:
    """Detect + send alerts for a given date. Returns count sent."""
    alerts = detect_alerts(target_date)
    return send_alerts(alerts, target_date)


def send_admin_alert(message: str) -> None:
    """系統錯誤通知 admin。"""
    admin = _telegram_chat_id()
    send_telegram(f"🚨 <b>HOLDINGS Tracker</b>\n{message}", chat_id=admin)
