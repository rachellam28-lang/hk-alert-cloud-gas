from __future__ import annotations

import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")
TABLE_PAGES = (
    "distribution_day.html",
    "fundflow.html",
    "guide.html",
    "history.html",
    "index.html",
    "jieqi_analysis.html",
    "momentum_list.html",
    "options_levels.html",
    "rights_analysis.html",
    "rotation_matrix.html",
    "signals.html",
    "smallcap_playbook.html",
    "timing_analysis.html",
    "timing_stack.html",
    "trading_desk.html",
    "vqc_analysis.html",
    "watchlist.html",
)


def stock_codes(values: list[str]) -> list[int]:
    result = []
    for value in values:
        match = re.search(r"\b(\d{5})\b", value)
        if match:
            result.append(int(match.group(1)))
    return result


def test_table_sorter_is_shipped_and_loaded_by_shared_navigation() -> None:
    nav = (ROOT / "shared-nav.js").read_text(encoding="utf-8")
    deploy = (ROOT / "ccass/scripts/_deploy_cf.py").read_text(encoding="utf-8")

    assert "shared-table-sort.js" in nav
    assert '"shared-table-sort.js"' in deploy
    for path in TABLE_PAGES:
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "shared-nav.js" in source, path


def test_every_labelled_table_header_is_sortable_across_all_pages(page) -> None:
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    for path in TABLE_PAGES:
        page.goto(f"{BASE_URL}/{path}", wait_until="domcontentloaded")
        page.wait_for_function(
            """() => window.__suiteTableSortInstalled === true &&
              [...document.querySelectorAll('table thead th')]
                .filter(th => th.colSpan === 1 && th.innerText.trim())
                .every(th => th.classList.contains('suite-sortable'))""",
            timeout=20_000,
        )
        bad = page.evaluate(
            """() => [...document.querySelectorAll('table thead th')]
              .filter(th => th.colSpan === 1 && th.innerText.trim() &&
                !th.classList.contains('suite-sortable'))
              .map(th => th.innerText.trim())"""
        )
        assert not bad, f"{path}: {bad}"

    assert not page_errors


def test_trading_desk_and_smallcap_sort_full_lists_before_paging(page) -> None:
    for path, tbody in (
        ("trading_desk.html", "#candidateBody"),
        ("smallcap_playbook.html", "#body"),
    ):
        page.goto(f"{BASE_URL}/{path}", wait_until="domcontentloaded")
        page.wait_for_function(
            "selector => document.querySelectorAll(selector + ' tr').length > 1",
            arg=tbody,
            timeout=45_000,
        )
        header = page.locator('th[data-sort="stock"]')

        header.click()
        ascending = stock_codes(page.locator(f"{tbody} tr td:first-child").all_inner_texts())
        assert len(ascending) > 1
        assert ascending == sorted(ascending)
        assert header.get_attribute("aria-sort") == "ascending"

        header.click()
        descending = stock_codes(page.locator(f"{tbody} tr td:first-child").all_inner_texts())
        assert descending == sorted(descending, reverse=True)
        assert header.get_attribute("aria-sort") == "descending"


def test_generic_sorter_orders_static_numeric_columns(page) -> None:
    page.goto(f"{BASE_URL}/timing_analysis.html", wait_until="domcontentloaded")
    page.wait_for_function("() => window.__suiteTableSortInstalled === true")
    header = page.locator("table thead th").nth(2)

    for _ in range(2):
        header.click()
        direction = header.get_attribute("aria-sort")
        values = []
        for text in page.locator("table tbody tr td:nth-child(3)").all_inner_texts():
            match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
            if match:
                values.append(float(match.group()))
        assert len(values) > 1
        assert values == sorted(values, reverse=direction == "descending")
