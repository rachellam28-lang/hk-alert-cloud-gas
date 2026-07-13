from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def test_kbar_single_chart_and_signal_rail(page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(
        f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=1733&view=3m",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#matrix .chart-svg", timeout=45_000)

    assert page.locator(".chart-tab").count() == 6
    assert page.locator("#matrix .chart-svg").count() == 1
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
