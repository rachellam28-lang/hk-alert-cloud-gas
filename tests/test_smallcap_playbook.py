from __future__ import annotations

import os
import re


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
    health = page.locator("#health").inner_text()
    assert health == "觀測資料已載入" or re.fullmatch(r"部分完成 · [1-9]\d* 錯誤", health)
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


def test_shared_theme_keeps_data_pages_light_and_chart_tool_dark(page):
    for path in ("smallcap_playbook.html", "trading_desk.html", "rights_analysis.html", "timing_analysis.html"):
        page.goto(f"{BASE_URL}/{path}", wait_until="domcontentloaded")
        page.wait_for_function("() => document.documentElement.classList.contains('suite-light')")
        background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        assert background == "rgb(237, 241, 242)"

    page.goto(f"{BASE_URL}/kbar_matrix.html", wait_until="domcontentloaded")
    assert not page.evaluate("() => document.documentElement.classList.contains('suite-light')")
    assert page.evaluate("() => getComputedStyle(document.body).backgroundColor") == "rgb(12, 18, 22)"
