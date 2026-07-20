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


def test_hkex_hsi_report_parser_maps_official_oi_columns() -> None:
    builder = load_builder()
    text = """26 年 07 月  24600 認購      602        602       602       602         1  |   529        533       310        341           -304       21       294  |       890         66       295       842          -40
26 年 07 月  24600 認沽      246        275       240       256        48  |   260        548       205        467           +213       21       482  |      2163        190       530       333          -47"""
    rows = builder.parse_hkex_hsi_report(text, "2026-07-17")

    assert len(rows) == 2
    assert rows[0]["contract_month"] == "2026-07"
    assert rows[0]["side"] == "call"
    assert rows[0]["total_volume"] == 295
    assert rows[0]["open_interest"] == 842
    assert rows[0]["open_interest_change"] == -40
    assert rows[1]["side"] == "put"
    assert rows[1]["settlement"] == 467


def test_published_snapshot_is_observed_and_never_synthetic() -> None:
    payload = json.loads((ROOT / "data" / "options_levels.json").read_text(encoding="utf-8"))

    assert payload["is_observed"] is True
    assert payload["data_kind"] == "observed_option_chain_derived_levels"
    assert payload["status"] in {"PASS", "PARTIAL"}
    assert payload["underlyings"]
    assert payload["observed_date"]
    for item in payload["underlyings"]:
        assert item["provider"] in {"HKEX Daily Market Report", "Futu OpenD", "MarketData.app"}
        for expiry in item["expiries"]:
            assert expiry["oi_coverage_pct"] >= 80
            assert expiry["call_wall"]["open_interest"] > 0
            assert expiry["put_wall"]["open_interest"] > 0
            assert expiry["max_pain"] is not None

    hsi = next(item for item in payload["underlyings"] if item["symbol"] == "HSI")
    assert hsi["chain_layout"] == "split_call_strike_put"
    assert hsi["previous_observed_at"] < hsi["observed_at"]
    first = hsi["expiries"][0]
    assert first["rows"]
    assert first["contract_multiplier"] == 50
    assert any(row["call_oi_change"] != 0 or row["put_oi_change"] != 0 for row in first["rows"])


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
    assert "CALL 認購" in page
    assert "PUT 認沽" in page
    assert "call_previous_volume" in page


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
    assert page.locator("#symbolSelect").input_value() == "HSI"
    assert page.locator("#levelsBody tr").count() == 54
    assert page.locator("#levelsBody tr").first.locator("td").count() == 17

    page.locator("th[data-sort='call_oi']").first.click()
    call_oi = page.locator("#levelsBody tr td:nth-child(7)").all_inner_texts()
    observed = [int(value.replace(",", "")) for value in call_oi if value.strip() not in {"", "—"}]
    assert observed == sorted(observed, reverse=True)
    assert not errors


def test_options_page_has_no_mobile_document_overflow(page) -> None:
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{BASE_URL}/options_levels.html", wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelector('#spot').textContent !== '—'", timeout=30_000)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1
