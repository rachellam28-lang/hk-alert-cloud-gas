from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rotation_snapshot_is_observed_relative_market_schema() -> None:
    payload = json.loads(read("data/sector_rotation.json"))

    assert payload["schema_version"] == 2
    assert payload["is_vendor_rrg"] is False
    assert "relative to the equal-weight market" in payload["method"]
    assert payload["coverage"]["observed_named_stocks"] > 500
    assert payload["coverage"]["classified_stocks"] > 0
    assert set(payload["profiles"]) == {"20", "60", "120"}
    assert payload["profiles"]["20"]["available"] is True
    assert payload["profiles"]["20"]["long_reference_date"]

    for profile in payload["profiles"].values():
        for sector in profile["sectors"].values():
            assert sector["quadrant"] in {
                "leading",
                "weakening",
                "lagging",
                "improving",
                "unavailable",
            }


def test_rotation_page_uses_rrg_axes_and_explicit_unavailable_state() -> None:
    page = read("rotation_matrix.html")

    assert "RS-Ratio" in page
    assert "RS-Momentum" in page
    assert "此週期未有足夠真實歷史" in page
    assert "key!=='other'" in page
    assert "Math.random" not in page


def test_timing_stack_uses_observed_market_and_signal_files() -> None:
    page = read("timing_stack.html")

    assert "/api/kbar/${code}?count=520" in page
    assert "data/vqc_backtest.json" in page
    assert "data/distribution_day_backtest.json" in page
    assert "data/jieqi_calendar.json" in page
    assert "data/kbar_cache.json" in page
    assert "holdings.json" in page
    assert "上轉確認" in page
    assert "下轉確認" in page
    assert "窗口內未確認" in page
    assert "價格使用對數刻度" in page
    assert "沒有合成未來價格" in page
    assert "Math.random" not in page
    assert "synthetic" not in page.lower()


def test_timing_stack_has_fixed_cross_market_proxies_and_iching_phases() -> None:
    page = read("timing_stack.html")

    for symbol in ("2800.HK", "SPY.US", "ASHR.US", "EWJ.US", "GLD.US"):
        assert symbol in page
    for phase in ("復", "臨", "泰", "大壯", "夬", "乾", "姤", "遯", "否", "觀", "剝", "坤"):
        assert f"'{phase}'" in page
    assert "只作季節標籤" in page
    assert "唔以卦名直接推斷升跌" in page


def test_kbar_cache_limits_long_history_to_core_symbols() -> None:
    builder = read("scripts/build_kbar_cache.py")

    assert "CORE_DAILY_COUNT = 1600" in builder
    assert 'CORE_SYMBOLS = {item["symbol"] for item in PRESETS}' in builder
    assert 'period == "1d" and symbol in CORE_SYMBOLS' in builder


def test_new_page_is_in_navigation_and_direct_deploy_package() -> None:
    nav = read("shared-nav.js")
    deploy = read("ccass/scripts/_deploy_cf.py")
    guide = read("guide.html")

    assert "timing_stack.html" in nav
    assert "timing_stack.html" in deploy
    assert "timing_stack.html" in guide
