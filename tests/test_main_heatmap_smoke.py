from __future__ import annotations

import os


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev")


def test_main_heatmap_tile_activates_matches(page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("#heatmapWrap", state="visible", timeout=30_000)
    page.wait_for_function(
        """
        () => {
          const loading = document.querySelector('#themeHeatmap .heat-loading');
          const tiles = [...document.querySelectorAll('#themeHeatmap .heat-tile[data-heat-key]')];
          return !loading && tiles.some(tile => {
            const count = Number((tile.querySelector('.heat-count')?.textContent || '0').trim());
            return count > 0 && tile.getAttribute('aria-disabled') !== 'true';
          });
        }
        """,
        timeout=45_000,
    )

    tile = page.evaluate(
        """
        () => {
          const tiles = [...document.querySelectorAll('#themeHeatmap .heat-tile[data-heat-key]')];
          const tile = tiles.find(el => {
            const count = Number((el.querySelector('.heat-count')?.textContent || '0').trim());
            return count > 0 && el.getAttribute('aria-disabled') !== 'true';
          });
          return tile ? {key: tile.dataset.heatKey, count: Number(tile.querySelector('.heat-count')?.textContent || 0)} : null;
        }
        """
    )
    assert tile, "no clickable theme heatmap tile with stocks"

    page.locator(f'#themeHeatmap .heat-tile[data-heat-key="{tile["key"]}"]').click()
    page.wait_for_function(
        """
        key => {
          const active = document.querySelector(`#themeHeatmap .heat-tile[data-heat-key="${key}"]`);
          const section = document.querySelector('#mcSectionHeat');
          const count = (document.querySelector('#mcHeatCount')?.textContent || '').trim();
          return active?.getAttribute('aria-pressed') === 'true'
            && section
            && getComputedStyle(section).display !== 'none'
            && count.length > 0;
        }
        """,
        arg=tile["key"],
        timeout=10_000,
    )

    assert not page_errors


def test_every_market_stock_column_has_a_registered_sort_key(page):
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelectorAll('#mcSmallTbody tr').length > 0",
        timeout=45_000,
    )

    audit = page.evaluate(
        """() => ['mcHeatTbody', 'mcSmallTbody', 'mcMidTbody', 'mcLargeTbody']
          .map(id => {
            const tbody = document.getElementById(id);
            const headers = [...tbody.closest('table').querySelectorAll('thead th')];
            return {
              id,
              headers: headers.map(th => ({
                label: th.innerText.trim(),
                key: th.dataset.sort || '',
                sortable: th.classList.contains('sortable'),
                registered: !!th.dataset.sort && SORT_OPTIONS.has(th.dataset.sort)
              }))
            };
          })"""
    )

    for table in audit:
        assert table["headers"], table["id"]
        for header in table["headers"]:
            assert header["sortable"], f'{table["id"]}: {header["label"]}'
            assert header["key"], f'{table["id"]}: {header["label"]}'
            assert header["registered"], f'{table["id"]}: {header["key"]}'

    page.locator('#mcSmallTbody').locator('xpath=ancestor::table').locator(
        'th[data-sort="link"]'
    ).click()
    assert page.evaluate("() => sortCol") == "link"
    assert "HKEX連結" in page.locator("#sortInfo").inner_text()

    page.locator('#mcSmallTbody').locator('xpath=ancestor::table').locator(
        'th[data-sort="streak"]'
    ).click()
    assert page.evaluate("() => sortCol") == "streak"
    assert "連續方向" in page.locator("#sortInfo").inner_text()
