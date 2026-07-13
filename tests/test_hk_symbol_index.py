from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_hk_symbol_index_matches_active_canonical_universe():
    payload = json.loads((ROOT / "data" / "hk_symbols.json").read_text(encoding="utf-8"))
    with sqlite3.connect(ROOT / "ccass" / "holdings.db") as connection:
        active_count = connection.execute(
            "SELECT COUNT(*) FROM stock_universe WHERE is_active = 1"
        ).fetchone()[0]

    symbols = payload["symbols"]
    codes = [row["code"] for row in symbols]
    assert payload["data_kind"] == "observed_listing_index"
    assert payload["is_observed"] is True
    assert payload["count"] == active_count == len(symbols)
    assert len(codes) == len(set(codes))
    assert all(len(code) == 5 and code.isdigit() for code in codes)
    assert "08131" in codes
    assert "89988" in codes
