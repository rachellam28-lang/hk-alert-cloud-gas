from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("HK_ALERT_BASE_URL", "https://hk-alert-cloud-gas.pages.dev").rstrip("/")


def request(path: str) -> Request:
    return Request(
        f"{BASE_URL}{path}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 hk-alert-kbar-smoke"},
    )


def test_hk_kbar_api_returns_valid_real_ohlcv():
    with urlopen(request("/api/kbar/1069?count=260"), timeout=30) as response:
        payload = json.load(response)

    entry = payload["entry"]
    bars = entry["series"]["1d"]
    assert payload["source"] == "Tencent public HK daily K-line (unadjusted)"
    assert entry["symbol"] == "1069.HK"
    assert 30 <= len(bars) <= 260
    assert bars == sorted(bars, key=lambda row: row["time"])
    assert entry["quote"]["trade_date"] == bars[-1]["time"]
    assert entry["quote"]["last"] == bars[-1]["close"]
    assert all(row["low"] <= min(row["open"], row["close"]) for row in bars)
    assert all(row["high"] >= max(row["open"], row["close"]) for row in bars)
    assert all(row["low"] > 0 and row["volume"] >= 0 for row in bars)


def test_hk_kbar_api_rejects_non_numeric_symbol():
    try:
        urlopen(request("/api/kbar/not-a-stock"), timeout=10)
    except HTTPError as error:
        assert error.code == 400
        payload = json.loads(error.read().decode("utf-8"))
        assert payload == {"error": "invalid_hk_code"}
    else:
        raise AssertionError("invalid symbol unexpectedly accepted")
