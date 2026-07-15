from types import SimpleNamespace

from scripts import health_check


def test_futu_dependency_requires_a_real_quote(monkeypatch):
    monkeypatch.setenv("USE_FUTU", "true")
    monkeypatch.setattr(health_check.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        health_check.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="probe detail: no backend connection\n",
            stderr="",
        ),
    )

    result = health_check.check_futu_dependency()

    assert result["status"] == health_check.ICON_WARN
    assert "no backend connection" in result["detail"]
    assert "Longbridge fallback" in result["detail"]


def test_futu_dependency_passes_only_after_quote_probe(monkeypatch):
    monkeypatch.setenv("USE_FUTU", "true")
    monkeypatch.setattr(health_check.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        health_check.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = health_check.check_futu_dependency()

    assert result["status"] == health_check.ICON_OK


def test_futu_dependency_can_be_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("USE_FUTU", "false")

    result = health_check.check_futu_dependency()

    assert result["status"] == health_check.ICON_SKIP
