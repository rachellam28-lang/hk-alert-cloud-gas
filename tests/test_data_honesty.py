import json
import ast
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publish_coverage_counts_trusted_market_pct_only():
    from ccass.scripts.audit_gate import (
        _latest_db_coverage,
        _latest_publishable_db_date,
    )

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE stock_universe (
            stock_code TEXT PRIMARY KEY,
            is_active INTEGER NOT NULL
        );
        CREATE TABLE ccass_daily (
            stock_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            total_pct REAL,
            validation_failed INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.executemany(
        "INSERT INTO stock_universe VALUES (?, 1)",
        [(f"{code:05d}",) for code in range(1, 101)],
    )
    conn.executemany(
        "INSERT INTO ccass_daily VALUES (?, '2026-07-09', 50.0, 0)",
        [(f"{code:05d}",) for code in range(1, 99)],
    )
    conn.executemany(
        "INSERT INTO ccass_daily VALUES (?, '2026-07-10', ?, 0)",
        [(f"{code:05d}", 50.0 if code == 1 else None) for code in range(1, 100)],
    )

    count, total, pct = _latest_db_coverage(conn, "2026-07-10")
    assert (count, total, pct) == (1, 100, 1.0)
    assert _latest_publishable_db_date(conn, 98.0) == ("2026-07-09", 98, 98.0)


def test_fundflow_missing_short_data_stays_missing():
    from scripts.fetch_fundflow import build_output, parse_output

    parsed = parse_output(
        "| symbol | EndDate | MainIn | MainNetFlow | MainOut | TotalNetFlow |\n"
        "| hk00700 | 2026-07-10 | 100 | 40 | 60 | 40 |\n"
    )
    row = parsed["00700"]
    assert row["short_ratio"] is None
    assert row["short_amount"] is None
    assert build_output(parsed)["top_short"] == []


def test_published_json_is_strict_and_missing_rights_terms_are_null():
    for path in (ROOT / "data").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8-sig"))

    rights = json.loads((ROOT / "data" / "rights_analysis.json").read_text(encoding="utf-8"))
    for row in rights:
        assert row.get("price_num") != 0
        assert row.get("amount_num") != 0
        assert row.get("pct_num") != 0
        assert row.get("market_price") != 0


def test_model_and_rule_outputs_are_labeled_as_derived():
    timesfm = json.loads((ROOT / "data" / "timesfm.json").read_text(encoding="utf-8"))
    assert timesfm["data_kind"] == "model_forecast"
    assert timesfm["is_observed"] is False

    tradeable = json.loads((ROOT / "data" / "tradeable.json").read_text(encoding="utf-8"))
    assert all(row.get("data_kind") == "derived_rule_score" for row in tradeable)
    assert all(row.get("is_observed") is False for row in tradeable)


def test_sector_rotation_does_not_publish_stale_snapshot_dates():
    rotation = json.loads((ROOT / "data" / "sector_rotation.json").read_text(encoding="utf-8"))
    latest = rotation["windows"]["5"]
    assert rotation["updated"] == latest["latest_date"]
    assert latest["latest_rows"] >= rotation["minimum_fresh_rows"]
    assert "same-date non-stale" in rotation["method"]


def test_dopamine_fallback_never_invents_a_neutral_score(tmp_path):
    source = (ROOT / "scripts" / "dopamine_refresh.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_fallback_dopamine"
    )
    namespace = {
        "PROJECT": tmp_path,
        "json": json,
        "sys": __import__("sys"),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "dopamine_refresh.py", "exec"), namespace)
    fallback = namespace["_load_fallback_dopamine"]("provider offline")
    assert fallback["dopamine"] is None
    assert fallback["level"] == "unavailable"
    assert fallback["is_observed"] is False

    market = json.loads((ROOT / "market.json").read_text(encoding="utf-8"))
    assert market["dopamine"]["data_kind"] == "observed_provider_snapshot"
    assert market["dopamine"]["is_observed"] is True
