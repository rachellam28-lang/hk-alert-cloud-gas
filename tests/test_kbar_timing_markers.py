from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def test_kbar_uses_real_vqc_timing_marker(page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(
        f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=1933",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector(".chart-svg", timeout=45_000)
    page.wait_for_function(
        """() => [...document.querySelectorAll('.chart-svg text')]
          .some(node => node.textContent.trim().split('+').includes('VQC'))""",
        timeout=20_000,
    )

    labels = page.locator(".legend-row").inner_text()
    assert "VQC 成交轉勢" in labels
    assert "節氣窗口" in labels
    assert "分佈日" in labels
    assert not page_errors
