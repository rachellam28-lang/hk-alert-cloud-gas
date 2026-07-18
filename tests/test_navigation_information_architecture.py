import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_navigation_uses_workflow_order_without_retired_pages() -> None:
    nav = read("shared-nav.js")
    expected = [
        "trading_desk.html",
        "index.html",
        "rotation_matrix.html",
        "trend_matrix.html",
        "signals.html",
        "smallcap_playbook.html",
        "kbar_matrix.html",
        "momentum_list.html",
        "rights_analysis.html",
        "watchlist.html",
    ]
    positions = [nav.index(page) for page in expected]

    assert positions == sorted(positions)
    assert "daily_trade_prompt.html" not in nav
    assert "gap_fvg.html" not in nav
    assert "['\\u4e8b\\u4ef6', [" not in nav


def test_retired_routes_redirect_without_loading_data() -> None:
    daily = read("daily_trade_prompt.html")
    gap = read("gap_fvg.html")

    assert "trading_desk.html" in daily
    assert "signals.html" in gap
    assert "data/" not in daily
    assert "data/" not in gap
    assert "location.replace" in daily
    assert "location.replace" in gap


def test_generators_do_not_restore_retired_navigation() -> None:
    generators = [
        "scripts/gen_distribution_day_analysis.py",
        "scripts/gen_jieqi_analysis.py",
        "scripts/gen_rights_page.py",
        "scripts/gen_timing_analysis.py",
        "scripts/gen_vqc_analysis.py",
    ]

    for generator in generators:
        source = read(generator)
        assert 'href="gap_fvg.html"' not in source
        assert 'href="daily_trade_prompt.html"' not in source


def test_system_guide_matches_current_data_contract() -> None:
    guide = read("guide.html")

    for text in (
        "每日使用次序",
        "PASS",
        "PARTIAL",
        "並非全港市場廣度",
        "小暑/姤",
        "週圖",
        "T+2",
        "Wrangler",
    ):
        assert text in guide

    assert "約 7am" not in guide
    assert "Futu 實時 + daily refresh" not in guide


def test_guide_is_fixed_to_the_right_of_more(page) -> None:
    page.goto(f"{BASE_URL}/guide.html", wait_until="domcontentloaded")
    page.wait_for_selector("#sharedSiteNav .suite-nav-guide a")

    order = page.locator("#sharedSiteNav > *").evaluate_all(
        "nodes => nodes.map(node => node.className)"
    )
    assert order[-2:] == ["suite-nav-more", "suite-nav-guide"]
    assert page.locator(
        ".suite-nav-more .suite-nav-panel a[href$='guide.html']"
    ).count() == 0

    guide = page.locator(".suite-nav-guide a")
    assert guide.inner_text() == "說明"
    assert "active" in (guide.get_attribute("class") or "")
