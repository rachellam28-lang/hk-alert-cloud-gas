from __future__ import annotations

import json
import os
from pathlib import Path


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]


def test_main_page_loads_real_trade_engine_badges(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelectorAll('.cpill-skill').length > 0",
        timeout=45_000,
    )
    assert "候選 240" in page.locator("#summaryBar").inner_text()
    engine = json.loads((ROOT / "data" / "trade_engine.json").read_text(encoding="utf-8"))
    assert f"全市場 {engine['universe_count']}" in page.locator("#summaryBar").inner_text()
    assert not errors


def test_momentum_page_uses_expanded_engine_universe(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{BASE_URL}/momentum_list.html", wait_until="domcontentloaded")
    page.wait_for_function(
        """() => (document.querySelector('#momentumScope')?.textContent || '').includes('全市場')
          && document.querySelectorAll('#momentumRows tr').length === 50""",
        timeout=45_000,
    )
    text = page.locator("#momentumScope").inner_text()
    assert "候選 240" in text
    assert "已分析 240" in text
    assert page.locator("#momentumRows tr").count() == 50
    assert not errors


def test_kbar_scout_does_not_require_static_chart_cache(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{BASE_URL}/kbar_matrix.html?mode=hk&symbol=1733", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => (document.querySelector('#setupScoutMeta')?.textContent || '').includes('候選 240')",
        timeout=45_000,
    )
    assert page.locator("#setupScoutGrid .setup-scout-count").count() == 4
    assert page.locator("#setupScoutGrid button[data-symbol]").count() > 0
    assert not errors
