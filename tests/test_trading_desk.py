from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def test_trading_desk_fuses_real_candidate_sources(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{BASE_URL}/trading_desk.html", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelectorAll('#candidateBody tr').length > 0",
        timeout=45_000,
    )

    assert page.locator("#actionGrid .action-btn").count() == 4
    assert "引擎分析" in page.locator("#queueCount").inner_text()
    assert "CCASS" in page.locator("#sourceDates").inner_text()
    assert "當前資料可用" in page.locator("#healthState").inner_text()

    page.locator("#candidateBody tr").first.click()
    page.wait_for_function("() => document.querySelector('#inspector .plan-strip') !== null")
    assert page.locator("#inspector .detail-section").count() >= 5
    assert "Longbridge" in page.locator("#inspector").inner_text()
    assert "SFC" in page.locator("#inspector").inner_text()
    assert "未涵蓋 ≠ 0" in page.locator("#inspector").inner_text() or "申報淡倉" in page.locator("#inspector").inner_text()
    assert page.locator("#inspector a[href*='kbar_matrix.html']").count() == 1
    assert not errors


def test_trading_desk_mobile_queue_and_inspector_fit(page):
    page.set_viewport_size({"width": 393, "height": 873})
    page.goto(f"{BASE_URL}/trading_desk.html", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelectorAll('#candidateBody tr').length > 0",
        timeout=45_000,
    )
    page.locator("#candidateBody tr").first.click()
    page.wait_for_function("() => document.querySelector('#inspector.open .plan-strip') !== null")

    width = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1]
    assert page.locator("#inspector.open").count() == 1
    assert page.locator("#closeInspector").is_visible()
