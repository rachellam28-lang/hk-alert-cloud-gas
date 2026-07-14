import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_trade_engine", ROOT / "scripts" / "build_trade_engine.py")
ENGINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ENGINE)


def observed_bars(count=260):
    rows = []
    for index in range(count):
        close = 1 + index * 0.004
        rows.append({
            "time": f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}",
            "open": close - 0.002,
            "high": close + 0.01,
            "low": close - 0.01,
            "close": close,
            "volume": 100_000 + index * 100,
        })
    return rows


def test_validate_daily_bars_rejects_invalid_and_does_not_pad():
    rows = [
        ["2026-07-10", "1.00", "1.02", "1.03", "0.99", "1000"],
        ["2026-07-11", "1.02", "1.01", "1.00", "0.99", "900"],
    ]
    bars = ENGINE.validate_daily_bars(rows)
    assert len(bars) == 1
    assert bars[0]["time"] == "2026-07-10"


def test_daily_setup_is_derived_from_observed_bars_with_trade_plan():
    setup = ENGINE.analyze_daily_setups({
        "symbol": "700.HK",
        "label": "Tencent",
        "market": "hk",
        "series": {"1d": observed_bars()},
    })
    assert setup is not None
    assert setup["data_kind"] == "derived_rule_output"
    assert setup["is_observed"] is False
    assert setup["analysis_timeframes"]["short"] == "1D"
    assert setup["trade_plan"]["entry"] is not None
    assert setup["trade_plan"]["invalidation"] is not None
    assert setup["trade_plan"]["target"] is not None


def test_signal_lanes_do_not_double_count_corporate_or_ccass_signals():
    lanes = ENGINE.classify_signal_lanes({
        "signals": [
            {"label": "配股公告", "category": "corp", "date": "2026-07-14"},
            {"label": "年開線突破", "category": "year_open", "date": "2026-07-14"},
            {"label": "CCASS合計持股增持", "category": "tech", "date": "2026-07-13"},
        ],
        "corpTypes": {"placement": True, "rights": False, "increase": False},
        "supply": {"cls": "supply-cash", "label": "圈錢"},
    })
    assert [item["label"] for item in lanes["event"]["labels"]] == ["配股公告"]
    assert [item["label"] for item in lanes["technical"]["labels"]] == ["年開線突破"]
    assert [item["label"] for item in lanes["ccass_signals"]["labels"]] == ["CCASS合計持股增持"]
    assert lanes["event"]["direction"] == "negative_supply"


def test_stage1_covers_real_universe_and_balances_buckets():
    candidates, meta = ENGINE.stage1_candidates(60)
    assert meta["universe_count"] > 2_000
    assert len(candidates) == 60
    assert all(item["symbol"].endswith(".HK") for item in candidates)
    assert all(item["snapshot"]["price"] > 0 for item in candidates)
    assert all(set(item["evidence_lanes"]) >= {"event", "technical", "ccass"} for item in candidates)
    assert set(meta["selected_by_bucket"]) == {"small", "mid", "large"}
    assert all(count > 0 for count in meta["selected_by_bucket"].values())
