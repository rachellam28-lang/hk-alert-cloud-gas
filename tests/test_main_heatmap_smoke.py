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
