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
    assert setup["metrics"]["aboveEma20"] is True
    assert setup["metrics"]["aboveEma50"] is True
    assert isinstance(setup["metrics"]["aboveEma200"], bool)


def test_candidate_breadth_is_labeled_selected_pool_and_detects_narrowing():
    base = {
        "aboveEma20": True,
        "aboveEma50": True,
        "aboveEma200": True,
        "aboveEma20_5dAgo": True,
        "aboveEma50_5dAgo": True,
        "aboveEma200_5dAgo": True,
    }
    weaker = {**base, "aboveEma20": False, "aboveEma50": False}
    breadth = ENGINE.build_candidate_breadth(
        {"1.HK": {"metrics": base}, "2.HK": {"metrics": weaker}, "SPY.US": {"metrics": base}},
        [{"symbol": "1.HK", "r5": 2}, {"symbol": "2.HK", "r5": 4}, {"symbol": "SPY.US", "r5": -9}],
    )

    assert breadth["scope"] == "selected_hk_candidate_pool"
    assert breadth["selection_bias"] is True
    assert breadth["is_full_market"] is False
    assert breadth["sample"] == 2
    assert breadth["ma20"]["pct"] == 50
    assert breadth["ma20"]["delta_5d_pp"] == -50
    assert breadth["median_return_5d_pct"] == 3
    assert breadth["signal"]["key"] == "narrowing_divergence"


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


def test_technical_confirmations_are_three_distinct_observed_signals():
    lanes = ENGINE.classify_signal_lanes({
        "signals": [
            {"label": "向上跳空缺口", "category": "gap", "date": "2026-07-14"},
            {"label": "向上FVG", "category": "fvg", "date": "2026-07-14"},
            {"label": "半年POC + 12個月POC", "category": "poc", "date": "2026-07-14"},
            {"label": "年開突破", "category": "year_open", "date": "2026-07-14"},
        ]
    })
    confirmations = lanes["technical"]["technical_confirmations"]
    assert [item["key"] for item in confirmations] == ["gap_up", "fvg_up", "poc_break"]
    assert all(item["is_observed"] is True for item in confirmations)


def test_finance_event_classifier_uses_announcement_title_only():
    events = ENGINE.classify_finance_events([
        {
            "date": "2026-07-14",
            "type": "placement",
            "title": "PROPOSED SHARE CONSOLIDATION AND PLACING OF CONVERTIBLE BONDS",
            "url": "https://example.test/announcement.pdf",
        }
    ])
    assert {item["key"] for item in events} == {"placement", "consolidation", "convertible"}
    assert all(item["is_observed"] is True for item in events)


def test_finance_event_chain_preserves_lifecycle_and_detects_control_then_financing():
    chain = ENGINE.build_finance_event_chain([
        {"date": "2026-06-01", "type": "acquisition", "title": "MANDATORY GENERAL OFFER"},
        {"date": "2026-06-18", "type": "placement", "title": "PROPOSED PLACING OF NEW SHARES"},
        {"date": "2026-07-01", "type": "placement", "title": "COMPLETION OF PLACING OF NEW SHARES"},
    ])
    assert chain["sequence_key"] == "control_then_financing"
    assert chain["control_then_financing"] is True
    assert chain["repeated_financing"] is True
    assert [item["stage_key"] for item in chain["timeline"]] == ["completed", "proposed", "announced"]


def test_finance_event_stage_does_not_invent_completion():
    assert ENGINE.finance_event_stage("FURTHER UPDATE ON POSSIBLE OFFER")[0] == "update"
    assert ENGINE.finance_event_stage("TERMINATION OF THE TRANSACTION")[0] == "ended"


def test_smallcap_playbook_keeps_supply_risk_ahead_of_confluence():
    playbook = ENGINE.build_smallcap_playbook(
        {"bucket": "small"},
        {"activeKey": "breakout"},
        {
            "event": {"active": True, "direction": "negative_supply", "finance_events": []},
            "technical": {"technical_confirmations": [{"key": "gap_up"}]},
            "ccass": {"tier": "strong", "consecutive_increase_days": 5},
        },
    )
    assert playbook["three_lane"] is False
    assert playbook["state_key"] == "supply_risk"
    assert playbook["ccass_supply_label"] == "合計增持"


def test_finance_event_uses_only_matching_observed_rights_terms():
    events = ENGINE.classify_finance_events(
        [{"date": "2026-07-14", "type": "placement", "title": "PLACING OF NEW SHARES UNDER GENERAL MANDATE"}],
        [{
            "date_parsed": "2026-07-14",
            "announcement_type": "placement",
            "title": "PLACING OF NEW SHARES UNDER GENERAL MANDATE",
            "pct_num": 20,
            "discount_pct": -15.4,
            "price_num": 0.11,
            "method": "配售（一般授權）",
            "purpose": "公告標題未有資金用途",
            "supply": {"label": "待確認", "cls": "supply-watch", "pending": ["未有完成錨點"]},
        }],
    )
    terms = events[0]["terms"]
    assert terms["dilution_pct"] == 20
    assert terms["discount_pct"] == -15.4
    assert terms["authorization"] == "一般授權"
    assert terms["coverage"]["observed"] == 4


def test_finance_event_does_not_attach_terms_from_another_date():
    events = ENGINE.classify_finance_events(
        [{"date": "2026-07-14", "type": "rights", "title": "RIGHTS ISSUE"}],
        [{"date_parsed": "2026-06-01", "announcement_type": "rights", "pct_num": 50}],
    )
    assert events[0]["terms"] is None
    assert events[0]["terms_status"] == "not_extracted"
