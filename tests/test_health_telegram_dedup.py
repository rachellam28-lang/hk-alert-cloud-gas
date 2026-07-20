from datetime import datetime, timedelta, timezone

from scripts import health_check


def test_health_telegram_dedup_ignores_header_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTH_TELEGRAM_DEDUP_TTL_SECONDS", "3600")
    state_path = tmp_path / "health_telegram_state.json"
    now = datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc)
    first = "System Health - 2026-07-05 18:00 HKT\n\nWARNINGS\nsame issue"
    second = "System Health - 2026-07-05 18:05 HKT\n\nWARNINGS\nsame issue"
    changed = "System Health - 2026-07-05 18:06 HKT\n\nWARNINGS\nnew issue"

    should_send, fingerprint, _ = health_check.should_send_health_telegram(
        first,
        now=now,
        state_path=str(state_path),
    )
    assert should_send is True
    health_check.record_health_telegram_sent(
        first,
        fingerprint=fingerprint,
        now=now,
        state_path=str(state_path),
    )

    should_send, _, reason = health_check.should_send_health_telegram(
        second,
        now=now + timedelta(minutes=5),
        state_path=str(state_path),
    )
    assert should_send is False
    assert "duplicate fingerprint" in reason

    should_send, _, _ = health_check.should_send_health_telegram(
        changed,
        now=now + timedelta(minutes=6),
        state_path=str(state_path),
    )
    assert should_send is True


def test_health_telegram_dedup_expires_after_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTH_TELEGRAM_DEDUP_TTL_SECONDS", "60")
    state_path = tmp_path / "health_telegram_state.json"
    now = datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc)
    text = "System Health - 2026-07-05 18:00 HKT\n\nALL OK"

    health_check.record_health_telegram_sent(text, now=now, state_path=str(state_path))
    should_send, _, _ = health_check.should_send_health_telegram(
        text,
        now=now + timedelta(seconds=61),
        state_path=str(state_path),
    )
    assert should_send is True
