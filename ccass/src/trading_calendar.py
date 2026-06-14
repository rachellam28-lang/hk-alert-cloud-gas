"""Hong Kong trading calendar helpers.

HOLDINGS 喺非交易日唔更新。如果 cron 跑出空數據，pipeline 唔好當失敗。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    HK_TZ = ZoneInfo("Asia/Hong_Kong")
except Exception:  # pragma: no cover - fallback for older runtimes
    import pytz
    HK_TZ = pytz.timezone("Asia/Hong_Kong")

try:
    import holidays
    HK_HOLIDAYS = holidays.HongKong()
except Exception:  # pragma: no cover - optional dependency missing
    HK_HOLIDAYS = set()


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
