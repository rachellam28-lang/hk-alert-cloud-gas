from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def load_builder():
    path = ROOT / "scripts" / "build_options_levels.py"
    spec = importlib.util.spec_from_file_location("build_options_levels", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_option_level_math_uses_observed_open_interest() -> None:
    builder = load_builder()
    rows = []
    for strike, call_oi, put_oi in ((90, 10, 100), (100, 80, 70), (110, 200, 20)):
        rows.extend(
            [
                {"expiry": "2099-01-16", "side": "call", "strike": strike, "open_interest": call_oi, "volume": 1, "iv": 0.2},
                {"expiry": "2099-01-16", "side": "put", "strike": strike, "open_interest": put_oi, "volume": 1, "iv": 0.2},
            ]
        )
    result = builder.derive_expiry(rows, "2099-01-16", 100.0)

    assert result["call_wall"] == {"strike": 110.0, "open_interest": 200}
    assert result["put_wall"] == {"strike": 90.0, "open_interest": 100}
    assert result["max_pain"] in {100.0, 110.0}
    assert result["oi_coverage_pct"] == 100.0


def test_published_snapshot_is_observed_and_never_synthetic() -> None:
    payload = json.loads((ROOT / "data" / "options_levels.json").read_text(encoding="utf-8"))

    assert payload["is_observed"] is True
    assert payload["data_kind"] == "observed_option_chain_derived_levels"
    assert payload["status"] in {"PASS", "PARTIAL"}
    assert payload["underlyings"]
    assert payload["observed_date"]
    for item in payload["underlyings"]:
        assert item["provider"] in {"Futu OpenD", "MarketData.app"}
        for expiry in item["expiries"]:
            assert expiry["oi_coverage_pct"] >= 80
            assert expiry["call_wall"]["open_interest"] > 0
            assert expiry["put_wall"]["open_interest"] > 0
            assert expiry["max_pain"] is not None


def test_options_page_is_wired_to_refresh_navigation_and_cloudflare() -> None:
    page = (ROOT / "options_levels.html").read_text(encoding="utf-8")
    nav = (ROOT / "shared-nav.js").read_text(encoding="utf-8")
    deploy = (ROOT / "ccass" / "scripts" / "_deploy_cf.py").read_text(encoding="utf-8")
    refresh = (ROOT / "ccass" / "scripts" / "daily_refresh.sh").read_text(encoding="utf-8")

    assert "data/options_levels.json" in page
    assert "options_levels.html" in nav
    assert '"options_levels.html"' in deploy
    assert 'Path("data/options_levels.json")' in deploy
    assert "build_options_levels.py" in refresh


def test_deployed_options_page_populates_without_js_errors(page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{BASE_URL}/options_levels.html", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelectorAll('#levelsBody tr').length > 1 && document.querySelector('#spot').textContent !== '—'",
        timeout=30_000,
    )
    assert page.locator("#symbolSelect option").count() >= 1
    assert page.locator("#expiryTabs button").count() >= 1
    assert page.locator("#putWall").inner_text() != "—"
    assert page.locator("#callWall").inner_text() != "—"
    assert not errors


def test_options_page_has_no_mobile_document_overflow(page) -> None:
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{BASE_URL}/options_levels.html", wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelector('#spot').textContent !== '—'", timeout=30_000)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1
