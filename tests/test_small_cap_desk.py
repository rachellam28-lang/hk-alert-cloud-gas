from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev")


def test_small_cap_desk_ranks_and_switches_lists(page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("#smallCapDesk", state="visible", timeout=30_000)
    page.wait_for_selector("#smallCapDeskList .sc-pick", timeout=45_000)

    assert page.locator('[data-desk-mode="priority"].active').count() == 1
    assert "5日基準" in page.locator("#smallCapDeskTruth").inner_text()
    assert page.locator("#smallCapDeskList .sc-pick").count() > 0
    assert page.evaluate(
        """() => getSmallCapDeskProfiles()
          .filter(profile => profile.kind === 'priority' && Number(profile.stock.chg) <= -15)
          .length"""
    ) == 0

    page.locator('[data-desk-mode="risk"]').click()
    page.wait_for_function(
        """() => document.querySelector('[data-desk-mode="risk"]')?.classList.contains('active')
          && document.querySelectorAll('#smallCapDeskList .sc-pick').length > 0""",
        timeout=30_000,
    )

    page.locator('[data-desk-mode="turn"]').click()
    page.wait_for_function(
        """() => document.querySelector('[data-desk-mode="turn"]')?.classList.contains('active')
          && (document.querySelectorAll('#smallCapDeskList .sc-pick').length > 0
            || document.querySelector('#smallCapDeskList .sc-desk-empty'))""",
        timeout=30_000,
    )

    page.locator('[data-desk-mode="priority"]').click()
    page.locator("#smallCapDeskList .sc-pick").first.click()
    page.wait_for_selector("#drawer.open", timeout=10_000)
    # Main Market intentionally hides the four CCASS trend windows; the
    # underlying values remain available to dedicated signal/detail pages.
    assert page.locator("#drawerBody .dmeta-label", has_text="CCASS").count() == 0
    assert not page_errors
