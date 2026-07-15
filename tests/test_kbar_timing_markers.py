from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def test_kbar_quarterly_pair_and_signal_rail(page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(
        f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=1733&view=3m",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#matrix .chart-svg", timeout=45_000)

    assert page.locator(".chart-tab").count() == 7
    assert page.locator('.quarterly-pair .pane').count() == 2
    assert page.locator('.quarterly-pair .pane-title').all_inner_texts() == ["季圖", "反向季圖"]
    assert page.locator("#matrix .chart-svg").count() == 2
    assert page.locator("#matrix iframe").count() == 0
    assert page.locator(".signal-event").count() > 0
    assert page.locator(".level-item").count() > 0

    page.locator('.chart-tab[data-view="6m_flip"]').click()
    page.wait_for_selector('.chart-tab[data-view="6m_flip"].active')
    assert page.locator("#matrix .chart-svg").count() == 1
    assert page.locator("#matrix iframe").count() == 0
    assert "view=6m_flip" in page.url
    assert not page_errors


def test_uncached_hk_uses_on_demand_daily_kbar(page):
    page.goto(
        f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=1069&view=6m",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#matrix .chart-svg", timeout=45_000)

    assert page.locator("#matrix .chart-svg").count() == 1
    assert page.locator("#matrix iframe").count() == 0
    assert "Cloudflare 按需真實日 K" in page.locator("#matrix").inner_text()
    assert "cloudflare-on-demand" in page.locator("#resolvedHint").inner_text()
    assert page.locator(".signal-event").count() > 0
    assert "undefined" not in page.locator("main").inner_text()


def test_full_hk_universe_supports_gem_code_and_exact_name(page):
    page.goto(
        f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=08131&view=3m",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#matrix .chart-svg", timeout=45_000)

    assert "全港股索引 2,823 隻" in page.locator("#resolvedHint").inner_text()
    assert "HKEX:8131" in page.locator("#resolvedHint").inner_text()
    assert page.locator("#matrix .chart-svg").count() == 2

    page.locator("#symbolInput").fill("諾亞智能")
    page.locator("#applyBtn").click()
    page.wait_for_function("() => new URL(location.href).searchParams.get('symbol') === '諾亞智能'")
    page.wait_for_selector("#matrix .chart-svg", timeout=45_000)

    assert "HKEX:8131" in page.locator("#resolvedHint").inner_text()
    assert page.locator("#matrix .chart-svg").count() == 2


def test_inverted_price_chart_preserves_candle_and_profile_geometry(page):
    page.goto(
        f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=1733&view=3m",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#matrix .candle-body", timeout=45_000)

    normal_bodies = page.locator("#matrix .pane").nth(0).locator(".candle-body").evaluate_all(
        "nodes => nodes.map(node => Number(node.getAttribute('height')))"
    )
    normal_profile = page.locator("#matrix .pane").nth(0).locator(".volume-profile-bar").evaluate_all(
        "nodes => nodes.map(node => Number(node.getAttribute('height')))"
    )
    normal_poc = float(page.locator("#matrix .pane").nth(0).locator(".poc-zone").get_attribute("height"))

    page.locator('.chart-tab[data-view="3m_pair"]').click()
    page.wait_for_selector('.chart-tab[data-view="3m_pair"].active')
    page.wait_for_function("() => document.querySelectorAll('#matrix .pane').length === 2")

    flipped_bodies = page.locator("#matrix .pane").nth(1).locator(".candle-body").evaluate_all(
        "nodes => nodes.map(node => Number(node.getAttribute('height')))"
    )
    flipped_profile = page.locator("#matrix .pane").nth(1).locator(".volume-profile-bar").evaluate_all(
        "nodes => nodes.map(node => Number(node.getAttribute('height')))"
    )
    flipped_poc = float(page.locator("#matrix .pane").nth(1).locator(".poc-zone").get_attribute("height"))

    assert flipped_bodies == normal_bodies
    assert flipped_profile == normal_profile
    assert flipped_poc == normal_poc
    assert any(height > 1.5 for height in flipped_bodies)

    page.locator('.chart-tab[data-view="1y"]').click()
    page.wait_for_selector('.chart-tab[data-view="1y"].active')
    page.wait_for_function("() => document.querySelectorAll('#matrix .candle-body').length === 260")
    assert "260 根 D 燭" in page.locator("#matrix .pane-meta").inner_text()

    page.locator('.chart-tab[data-view="1y_flip"]').click()
    page.wait_for_selector('.chart-tab[data-view="1y_flip"].active')
    page.wait_for_function("() => document.querySelectorAll('#matrix .candle-body').length === 260")
    assert "反向股價刻度" in page.locator("#matrix .pane-meta").inner_text()

    page.locator('.chart-tab[data-view="1d"]').click()
    page.wait_for_selector('.chart-tab[data-view="1d"].active')
    page.wait_for_function("() => document.querySelectorAll('#matrix .candle-body').length >= 260")
    daily_count = page.locator("#matrix .candle-body").count()
    assert f"{daily_count} 根 D 燭" in page.locator("#matrix .pane-meta").inner_text()
