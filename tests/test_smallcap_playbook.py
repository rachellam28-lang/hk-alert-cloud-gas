from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def test_smallcap_playbook_keeps_three_evidence_lanes_separate(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{BASE_URL}/smallcap_playbook.html", wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelectorAll('#body tr').length > 0", timeout=45_000)

    headers = page.locator("thead th").all_inner_texts()
    assert headers.index("CCASS 20日") == headers.index("CCASS 5日") + 1
    assert "財技階段" in headers
    assert {"Gap 跳升", "向上 FVG", "中長期 POC"}.issubset(set(headers))
    assert page.locator("#tabs .tab").count() == 15
    assert "技術確認" in page.locator(".funnel").inner_text()
    assert "盤路確認" not in page.locator("body").inner_text()
    assert "觀測資料已載入" in page.locator("#health").inner_text()
    assert not errors


def test_smallcap_playbook_mobile_has_no_horizontal_overflow(page):
    page.set_viewport_size({"width": 393, "height": 873})
    page.goto(f"{BASE_URL}/smallcap_playbook.html", wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelectorAll('#body tr').length > 0", timeout=45_000)
    page.locator("#body tr").first.click()
    page.wait_for_function("() => document.querySelector('#detail.open') !== null")

    widths = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    assert widths[0] <= widths[1]
    assert page.locator("#detail .detail-section").count() == 3
