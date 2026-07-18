from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def load_builder():
    path = ROOT / "scripts" / "build_trend_matrix.py"
    spec = importlib.util.spec_from_file_location("build_trend_matrix", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_night_session_crosses_midnight_and_incomplete_close_stays_missing() -> None:
    builder = load_builder()
    bars = [
        {"time": "2026-07-17 18:15:00", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 10},
        {"time": "2026-07-18 00:15:00", "open": 102, "high": 105, "low": 101, "close": 104, "volume": 20},
        {"time": "2026-07-18 03:00:00", "open": 104, "high": 106, "low": 103, "close": 105, "volume": 30},
        {"time": "2026-07-18 18:15:00", "open": 106, "high": 107, "low": 104, "close": 105, "volume": 40},
    ]
    sessions = builder.aggregate_night_sessions(bars)

    assert sessions["2026-07-17"]["complete"] is True
    assert sessions["2026-07-17"]["close"] == 105
    assert sessions["2026-07-17"]["volume"] == 60
    assert sessions["2026-07-18"]["complete"] is False
    assert sessions["2026-07-18"]["close"] is None
    assert sessions["2026-07-18"]["last_observed"] == 105


def test_five_grid_and_stock_score_are_deterministic() -> None:
    builder = load_builder()
    daily = []
    for index in range(60):
        close = 100 + index
        daily.append(
            {
                "time": f"2026-01-{index + 1:02d}" if index < 31 else f"2026-02-{index - 30:02d}",
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    rows = builder.build_matrix(daily, {}, {})
    latest = rows[-1]
    midpoint = (latest["day"]["high"] + latest["day"]["low"]) / 2

    assert latest["five_grid"] == {
        "high": latest["day"]["high"],
        "low": latest["day"]["low"],
        "mid": round(midpoint, 2),
        "open": latest["day"]["open"],
        "close": latest["day"]["close"],
    }
    assert latest["reference_levels"]["above"] is not None
    assert latest["reference_levels"]["below"] is not None
    assert latest["reference_levels"]["above"]["date"] < latest["date"]
    assert latest["reference_levels"]["below"]["date"] < latest["date"]
    assert latest["trend"]["components"]["completed_night"] == 0
    assert latest["night"] is None
    assert latest["trend"]["state"] in {"bull", "strong_bull"}


def test_published_trend_snapshot_uses_real_futu_observations() -> None:
    payload = json.loads((ROOT / "data" / "trend_matrix.json").read_text(encoding="utf-8"))

    assert payload["observations_are_real"] is True
    assert payload["is_observed"] is False
    assert payload["data_kind"] == "derived_rule_output_from_observed_futu_kbars"
    assert set(payload["indexes"]) == {"HSI", "HSCEI", "HSTECH"}
    for item in payload["indexes"].values():
        assert len(item["rows"]) >= 50
        latest = item["rows"][-1]
        assert latest["day"]["close"] > 0
        assert latest["trend"]["state"] in {"strong_bull", "bull", "range", "bear", "strong_bear"}
        assert latest["night"]["complete"] is True
        assert latest["night"]["close"] > 0

    hsi_rows = payload["indexes"]["HSI"]["rows"]
    june_5 = next(row for row in hsi_rows if row["date"] == "2026-06-05")
    assert round(june_5["five_grid"]["high"]) == 25216
    assert round(june_5["five_grid"]["low"]) == 24928
    assert round(june_5["five_grid"]["mid"]) == 25072
    assert round(june_5["five_grid"]["open"]) == 25186
    assert round(june_5["five_grid"]["close"]) == 24962


def test_trend_page_is_wired_to_navigation_refresh_and_cloudflare() -> None:
    page = (ROOT / "trend_matrix.html").read_text(encoding="utf-8")
    nav = (ROOT / "shared-nav.js").read_text(encoding="utf-8")
    refresh = (ROOT / "ccass" / "scripts" / "daily_refresh.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "ccass" / "scripts" / "_deploy_cf.py").read_text(encoding="utf-8")

    assert "data/trend_matrix.json" in page
    assert "api/kbar/" in page
    assert "trend_matrix.html" in nav
    assert "build_trend_matrix.py" in refresh
    assert '"trend_matrix.html"' in deploy
    assert 'Path("data/trend_matrix.json")' in deploy
    assert "exportCsv" not in page


def test_deployed_trend_page_switches_index_and_any_hk_stock(page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{BASE_URL}/trend_matrix.html", wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelectorAll('#matrixBody tr').length === 20", timeout=45_000)
    assert "恒生指數" in page.locator("#status").inner_text()
    assert page.locator("#trend").inner_text() in {"強勢向上", "偏多", "區間", "偏空", "強勢向下"}

    page.locator("button[data-index='HSTECH']").click()
    assert "恒生科技指數" in page.locator("#status").inner_text()

    page.locator("#query").fill("01733")
    page.locator("#loadStock").click()
    page.wait_for_function("() => (document.querySelector('#status')?.textContent || '').includes('01733')", timeout=45_000)
    assert "Tencent public HK daily K-line" in page.locator("#sourceMeta").inner_text()
    assert page.locator("#nightClose").inner_text() == "不適用"
    assert not errors


def test_trend_page_mobile_stays_within_document(page) -> None:
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{BASE_URL}/trend_matrix.html?symbol=1733", wait_until="domcontentloaded")
    page.wait_for_function("() => (document.querySelector('#status')?.textContent || '').includes('01733')", timeout=45_000)
    widths = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert widths[0] <= widths[1] + 1
    assert page.locator("#matrixBody tr").count() == 20
