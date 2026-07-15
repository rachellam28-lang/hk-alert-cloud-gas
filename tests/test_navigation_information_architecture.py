from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_navigation_uses_workflow_order_without_retired_pages() -> None:
    nav = read("shared-nav.js")
    expected = [
        "trading_desk.html",
        "index.html",
        "signals.html",
        "smallcap_playbook.html",
        "kbar_matrix.html",
        "momentum_list.html",
        "watchlist.html",
    ]
    positions = [nav.index(page) for page in expected]

    assert positions == sorted(positions)
    assert "daily_trade_prompt.html" not in nav
    assert "gap_fvg.html" not in nav


def test_retired_routes_redirect_without_loading_data() -> None:
    daily = read("daily_trade_prompt.html")
    gap = read("gap_fvg.html")

    assert "trading_desk.html" in daily
    assert "signals.html" in gap
    assert "data/" not in daily
    assert "data/" not in gap
    assert "location.replace" in daily
    assert "location.replace" in gap


def test_generators_do_not_restore_retired_navigation() -> None:
    generators = [
        "scripts/gen_distribution_day_analysis.py",
        "scripts/gen_jieqi_analysis.py",
        "scripts/gen_rights_page.py",
        "scripts/gen_timing_analysis.py",
        "scripts/gen_vqc_analysis.py",
    ]

    for generator in generators:
        source = read(generator)
        assert 'href="gap_fvg.html"' not in source
        assert 'href="daily_trade_prompt.html"' not in source
