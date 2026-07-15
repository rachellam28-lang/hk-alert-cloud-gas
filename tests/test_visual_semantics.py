from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_theme_exposes_one_semantic_market_palette() -> None:
    nav = read("shared-nav.js")

    for token in (
        "--primary:#0b7475",
        "--up:#157a4b",
        "--down:#b43a42",
        "--amber:#986308",
        "--violet:#6c5f91",
    ):
        assert token in nav

    assert "html.suite-light .sc-desk" in nav
    assert "html.suite-light .sc-reason.good" in nav
    assert "html.suite-light .sc-reason.bad" in nav


def test_kbar_defaults_to_true_quarterly_pair_in_dark_workspace() -> None:
    page = read("kbar_matrix.html")

    assert "value: '3m_pair'" in page
    assert "data-layout=\"quarterly-pair\"" in page
    assert "buildTradingViewPane(tvSymbol, entry, '3m')" in page
    assert "buildTradingViewPane(tvSymbol, entry, '3m_flip')" in page
    assert "theme: 'dark'" in page
    assert "theme: 'light'" not in page
    assert "u.searchParams.set('theme', 'dark')" in page
