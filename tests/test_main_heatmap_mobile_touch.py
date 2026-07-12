from __future__ import annotations

import os

import pytest


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev")


@pytest.fixture
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "has_touch": True,
        "viewport": {"width": 393, "height": 852},
    }


def test_main_heatmap_mobile_tap_switches_active_tile(page):
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("#heatmapWrap", state="visible", timeout=30_000)
    page.wait_for_function(
        """
        () => {
          const loading = document.querySelector('#themeHeatmap .heat-loading');
          const tiles = [...document.querySelectorAll('#themeHeatmap .heat-tile[data-heat-key]')];
          return !loading && tiles.filter(tile => {
            const count = Number((tile.querySelector('.heat-count')?.textContent || '0').trim());
            return count > 0 && tile.getAttribute('aria-disabled') !== 'true';
          }).length >= 2;
        }
        """,
        timeout=45_000,
    )

    tiles = page.evaluate(
        """
        () => [...document.querySelectorAll('#themeHeatmap .heat-tile[data-heat-key]')]
          .map(el => ({
            key: el.dataset.heatKey,
            count: Number((el.querySelector('.heat-count')?.textContent || '0').trim()),
            disabled: el.getAttribute('aria-disabled') === 'true'
          }))
          .filter(el => el.count > 0 && !el.disabled)
          .slice(0, 2)
        """
    )
    assert len(tiles) == 2, "need two tappable theme tiles"

    first = tiles[0]["key"]
    second = tiles[1]["key"]

    page.locator(f'#themeHeatmap .heat-tile[data-heat-key="{first}"]').tap()
    page.wait_for_function(
        """
        key => document.querySelector(`#themeHeatmap .heat-tile[data-heat-key="${key}"]`)
          ?.getAttribute('aria-pressed') === 'true'
        """,
        arg=first,
        timeout=10_000,
    )

    page.locator(f'#themeHeatmap .heat-tile[data-heat-key="{second}"]').tap()
    page.wait_for_function(
        """
        ([firstKey, secondKey]) => {
          const first = document.querySelector(`#themeHeatmap .heat-tile[data-heat-key="${firstKey}"]`);
          const second = document.querySelector(`#themeHeatmap .heat-tile[data-heat-key="${secondKey}"]`);
          return first?.getAttribute('aria-pressed') !== 'true'
            && second?.getAttribute('aria-pressed') === 'true';
        }
        """,
        arg=[first, second],
        timeout=10_000,
    )
