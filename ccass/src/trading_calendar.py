"""Hong Kong trading calendar helpers.

HOLDINGS 喺非交易日唔更新。如果 cron 跑出空數據，pipeline 唔好當失敗。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    HK_TZ = ZoneInfo("Asia/Hong_Kong")
except Exception:  # pragma: no cover - fallback when tzdata is unavailable
    HK_TZ = timezone(timedelta(hours=8))

try:
    import holidays
    HK_HOLIDAYS = holidays.HongKong()
except Exception:  # pragma: no cover - optional dependency missing
    _FALLBACK_HOLIDAY_ISO = {
        "2025-01-01", "2025-01-29", "2025-01-30", "2025-01-31",
        "2025-04-04", "2025-04-18", "2025-04-19", "2025-04-21",
        "2025-05-01", "2025-05-05", "2025-05-31", "2025-07-01",
        "2025-10-01", "2025-10-07", "2025-10-29", "2025-12-25",
        "2025-12-26",
        "2026-01-01", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-04-03", "2026-04-04", "2026-04-06", "2026-04-07",
        "2026-05-01", "2026-05-25", "2026-06-19", "2026-07-01",
        "2026-09-26", "2026-10-01", "2026-10-19", "2026-12-25",
        "2026-12-26",
        "2027-01-01", "2027-02-06", "2027-02-08", "2027-02-09",
        "2027-03-26", "2027-03-27", "2027-03-29", "2027-04-05",
        "2027-05-01", "2027-05-13", "2027-06-09", "2027-07-01",
        "2027-09-16", "2027-10-01", "2027-10-08", "2027-12-25",
        "2027-12-27",
    }
    HK_HOLIDAYS = {date.fromisoformat(item) for item in _FALLBACK_HOLIDAY_ISO}


def now_hk() -> datetime:
    return datetime.now(HK_TZ)


def today_hk() -> date:
    return now_hk().date()


def is_trading_day(d: date) -> bool:
    """週末 + HK 公眾假期 = 非交易日。"""
    if d.weekday() >= 5:  # Sat, Sun
        return False
    if d in HK_HOLIDAYS:
        return False
    return True


def previous_trading_day(d: date) -> date:
    """搵 d 之前最近嘅交易日（唔包 d 本身）。"""
    candidate = d - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def last_n_trading_days(end: date, n: int) -> list[date]:
    """end 起計倒數 n 個交易日（包 end 如果 end 係交易日）。"""
    days: list[date] = []
    cur = end
    while len(days) < n:
        if is_trading_day(cur):
            days.append(cur)
        cur -= timedelta(days=1)
    return list(reversed(days))


if __name__ == "__main__":
    t = today_hk()
    print(f"Today: {t}, trading day: {is_trading_day(t)}")
    print(f"Last 5 trading days: {last_n_trading_days(t, 5)}")
