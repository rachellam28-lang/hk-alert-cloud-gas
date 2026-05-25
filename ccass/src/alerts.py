"""Alert engine: 偵測異常 + 經 Telegram 通知。

Throttle 規則（FATAL-001）：
- 每條 ≥ 3 秒
- 單次 batch ≤ 20 條
- 超過 50 條淨係 send summary
"""
from __future__ import annotations

import os
import time
from datetime import datetime, date
from typing import Optional

import requests
from dotenv import load_dotenv

from src.db import get_conn
from src.logger import setup_logger

load_dotenv()
logger = setup_logger("alerts")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
) -> bool:
    """Send 一條 message。回傳 True 如果成功。"""
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.error("TELEGRAM_TOKEN missing — cannot send")
        return False
    if chat_id is None:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID missing")
        return False

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
            logger.warning("Telegram 429, sleeping %ds", retry_after)
            time.sleep(retry_after + 1)
            return False
        logger.error("Telegram %d: %s", resp.status_code, resp.text[:200])
        return False
    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)
        return False


def detect_alerts(
    target_date: date,
    spike_threshold_pct: float = 5.0,
    consecutive_days: int = 3,
    consecutive_min_daily_pct: float = 1.0,
) -> list[dict]:
    """偵測異常並回傳 alert list（未 send）。"""
    date_str = target_date.strftime("%Y-%m-%d")

    with get_conn() as conn:
        # Spike detection
        spikes = conn.execute(
            """SELECT t.stock_code, t.delta_5d_pct, t.delta_20d_pct,
                      u.stock_name, d.total_pct
               FROM ccass_trends t
               LEFT JOIN stock_universe u ON u.stock_code = t.stock_code
               LEFT JOIN ccass_daily d ON d.stock_code = t.stock_code AND d.trade_date = t.trade_date
               WHERE t.trade_date = ?
                 AND ABS(t.delta_5d_pct) >= ?""",
            (date_str, spike_threshold_pct),
        ).fetchall()

        consecutive = conn.execute(
            """SELECT t.stock_code, t.consecutive_increase_days, t.consecutive_decrease_days,
                      t.delta_5d_pct, u.stock_name, d.total_pct
               FROM ccass_trends t
               LEFT JOIN stock_universe u ON u.stock_code = t.stock_code
               LEFT JOIN ccass_daily d ON d.stock_code = t.stock_code AND d.trade_date = t.trade_date
               WHERE t.trade_date = ?
                 AND (t.consecutive_increase_days >= ? OR t.consecutive_decrease_days >= ?)""",
            (date_str, consecutive_days, consecutive_days),
        ).fetchall()

        # Dedup: 已 send 過今日嘅就 skip
        already_sent = {
            (r["stock_code"], r["alert_type"])
            for r in conn.execute(
                "SELECT stock_code, alert_type FROM alerts_sent WHERE trade_date = ?",
                (date_str,),
            ).fetchall()
        }

    alerts = []
    for s in spikes:
        atype = "spike_up" if s["delta_5d_pct"] > 0 else "spike_down"
        if (s["stock_code"], atype) in already_sent:
            continue
        alerts.append(
            {
                "stock_code": s["stock_code"],
                "stock_name": s["stock_name"] or "",
                "alert_type": atype,
                "delta_5d_pct": s["delta_5d_pct"],
                "delta_20d_pct": s["delta_20d_pct"],
                "total_pct": s["total_pct"],
            }
        )

    for c in consecutive:
        if c["consecutive_increase_days"] >= consecutive_days:
            atype = "consecutive_buy"
            streak = c["consecutive_increase_days"]
        else:
            atype = "consecutive_sell"
            streak = c["consecutive_decrease_days"]
        if (c["stock_code"], atype) in already_sent:
            continue
        alerts.append(
            {
                "stock_code": c["stock_code"],
                "stock_name": c["stock_name"] or "",
                "alert_type": atype,
                "streak_days": streak,
                "delta_5d_pct": c["delta_5d_pct"],
                "total_pct": c["total_pct"],
            }
        )

    return alerts


def format_alert(a: dict) -> str:
    code = a["stock_code"]
    name = a["stock_name"]
    atype = a["alert_type"]

    if atype == "spike_up":
        emoji = "🟢⬆️"
        head = f"CCASS Spike UP"
    elif atype == "spike_down":
        emoji = "🔴⬇️"
        head = f"CCASS Spike DOWN"
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
        f"CCASS 總持倉: {total_pct:.2f}%"
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

    lines = [f"📊 <b>CCASS 異動 Summary</b> ({target_date})"]
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
    """Send CCASS event alerts (deposit/transfer) via Telegram.
    Returns number of alerts sent. Stub — implement if Telegram push is needed.
    """
    return 0


def scan_alerts_for_date(target_date: date) -> int:
    """Detect + send alerts for a given date. Returns count sent."""
    alerts = detect_alerts(target_date)
    return send_alerts(alerts, target_date)


def send_admin_alert(message: str) -> None:
    """系統錯誤通知 admin。"""
    admin = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    send_telegram(f"🚨 <b>CCASS Tracker</b>\n{message}", chat_id=admin)

