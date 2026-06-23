#!/usr/bin/env python3
"""Build Distribution Day backtest data from TradingView historical OHLCV.

Mark Minervini's Distribution Day concept is a market pressure gauge:
an index or benchmark proxy closes lower on higher volume than the prior day.

This module backtests the concept on liquid benchmark proxies:
  - HK: HSI1! on HKEX

Output:
  data/distribution_day_backtest.json
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
from tvDatafeed import Interval, TvDatafeed

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
OUT_PATH = DATA_DIR / "distribution_day_backtest.json"

WINDOW_DAYS = max(int(os.getenv("DD_WINDOW_DAYS", "25")), 5)
DROP_PCT = max(float(os.getenv("DD_DROP_PCT", "0.2")), 0.0)
DEFAULT_BARS = max(int(os.getenv("DD_BACKTEST_BARS", "520")), 260)

BENCHMARKS = [
    {
        "key": "hk",
        "code": "HSI1!",
        "symbol": "HSI1!",
        "exchange": "HKEX",
        "name": "Hang Seng Proxy",
        "label": "HK proxy",
    },
]

_tv_local = threading.local()


def _tv() -> TvDatafeed:
    tv = getattr(_tv_local, "tv", None)
    if tv is None:
        u = os.getenv("TV_USER")
        p = os.getenv("TV_PASS")
        tv = TvDatafeed(u, p) if u else TvDatafeed()
        _tv_local.tv = tv
    return tv


def fetch_history(symbol: str, exchange: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
    df = _tv().get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=n_bars)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    cols = {c.lower(): c for c in df.columns}
    want = {}
    for k in ("open", "high", "low", "close", "volume"):
        if k in cols:
            want[k] = cols[k]
    if len(want) < 5:
        return pd.DataFrame()
    df = df.rename(columns={v: k for k, v in want.items()})
    df = df[["open", "high", "low", "close", "volume"]].copy()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[df["close"] > 0]
    df["volume"] = df["volume"].fillna(0)
    df = df.sort_index().reset_index()
    if "index" in df.columns:
        df = df.rename(columns={"index": "date"})
    elif "datetime" in df.columns:
        df = df.rename(columns={"datetime": "date"})
    else:
        df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    return df


def forward_return(df: pd.DataFrame, idx0: int, horizon: int, entry: float) -> float | None:
    tgt = idx0 + horizon
    if tgt >= len(df):
        return None
    px = float(df.iloc[tgt]["close"])
    if px <= 0 or entry <= 0:
        return None
    return round(px / entry - 1, 4)


def max_gain_dd(df: pd.DataFrame, idx0: int, horizon: int, entry: float) -> tuple[float | None, float | None]:
    if entry <= 0:
        return None, None
    window = df.iloc[idx0 + 1: idx0 + 1 + horizon]
    if window.empty:
        return None, None
    closes = window["close"].astype(float)
    closes = closes[closes > 0]
    if closes.empty:
        return None, None
    return round(float(closes.max()) / entry - 1, 4), round(float(closes.min()) / entry - 1, 4)


def state_for_count(count: int) -> str:
    if count >= 6:
        return "correction"
    if count >= 4:
        return "under_pressure"
    if count >= 3:
        return "caution"
    return "healthy"


def benchmark_backtest(spec: dict[str, Any]) -> dict[str, Any] | None:
    hist = fetch_history(spec["symbol"], spec["exchange"], DEFAULT_BARS)
    if hist.empty or len(hist) < 80:
        return None

    rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    counts: list[int] = []
    state_counts = {"healthy": 0, "caution": 0, "under_pressure": 0, "correction": 0}

    for i in range(1, len(hist)):
        prev = hist.iloc[i - 1]
        cur = hist.iloc[i]
        prev_close = float(prev["close"])
        cur_close = float(cur["close"])
        prev_vol = float(prev["volume"])
        cur_vol = float(cur["volume"])
        if prev_close <= 0 or cur_close <= 0:
            continue

        pct_change = round((cur_close / prev_close - 1) * 100, 2)
        vol_ratio = round(cur_vol / prev_vol, 2) if prev_vol > 0 else None
        is_distribution = pct_change <= -DROP_PCT and vol_ratio is not None and vol_ratio > 1.0

        start = max(0, i - WINDOW_DAYS + 1)
        window_slice = rows[start:i]
        rolling_count = sum(1 for r in window_slice if r.get("is_distribution"))
        if is_distribution:
            rolling_count += 1
        state = state_for_count(rolling_count)
        counts.append(rolling_count)
        state_counts[state] += 1

        row = {
            "date": pd.to_datetime(cur["date"]).strftime("%Y-%m-%d"),
            "close": round(cur_close, 3),
            "volume": int(cur_vol),
            "prev_close": round(prev_close, 3),
            "prev_volume": int(prev_vol),
            "pct_change": pct_change,
            "volume_ratio": vol_ratio,
            "is_distribution": bool(is_distribution),
            "dd_count_25d": rolling_count,
            "market_state": state,
        }
        rows.append(row)

        if is_distribution:
            entry = cur_close
            f5 = forward_return(hist, i, 5, entry)
            f20 = forward_return(hist, i, 20, entry)
            f60 = forward_return(hist, i, 60, entry)
            mg20, dd20 = max_gain_dd(hist, i, 20, entry)
            signal = {
                "date": row["date"],
                "close": row["close"],
                "volume": row["volume"],
                "prev_close": row["prev_close"],
                "pct_change": pct_change,
                "volume_ratio": vol_ratio,
                "dd_count_25d": rolling_count,
                "market_state": state,
                "fwd_5d": f5,
                "fwd_20d": f20,
                "fwd_60d": f60,
                "max_gain_20d": mg20,
                "max_drawdown_20d": dd20,
            }
            signal_rows.append(signal)

    all_f20 = [r["fwd_20d"] for r in signal_rows if r.get("fwd_20d") is not None]
    all_f5 = [r["fwd_5d"] for r in signal_rows if r.get("fwd_5d") is not None]
    all_f60 = [r["fwd_60d"] for r in signal_rows if r.get("fwd_60d") is not None]
    base_f20 = []
    base_f5 = []
    base_f60 = []
    base_rows = []
    for i in range(1, len(hist)):
        entry = float(hist.iloc[i]["close"])
        if entry <= 0:
            continue
        f5 = forward_return(hist, i, 5, entry)
        f20 = forward_return(hist, i, 20, entry)
        f60 = forward_return(hist, i, 60, entry)
        if f5 is not None:
            base_f5.append(f5)
        if f20 is not None:
            base_f20.append(f20)
        if f60 is not None:
            base_f60.append(f60)
        base_rows.append({
            "pct_change": round((float(hist.iloc[i]["close"]) / float(hist.iloc[i - 1]["close"]) - 1) * 100, 2)
            if float(hist.iloc[i - 1]["close"]) > 0 else None,
            "fwd_20d": f20,
        })

    current = rows[-1] if rows else {}
    current_count = int(current.get("dd_count_25d") or 0)
    current_state = current.get("market_state") or state_for_count(current_count)

    def rate(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(100 * sum(1 for v in vals if v < 0) / len(vals), 1)

    signal_negative_20d = rate(all_f20)
    signal_negative_5d = rate(all_f5)
    signal_negative_60d = rate(all_f60)
    base_negative_20d = rate(base_f20)
    base_negative_5d = rate(base_f5)
    base_negative_60d = rate(base_f60)

    pressure_rows = [r for r in rows if r.get("dd_count_25d", 0) >= 4]
    pressure_f20 = [r["fwd_20d"] for r in signal_rows if r.get("dd_count_25d", 0) >= 4 and r.get("fwd_20d") is not None]

    return {
        "key": spec["key"],
        "code": spec["code"],
        "symbol": spec["symbol"],
        "exchange": spec["exchange"],
        "name": spec["name"],
        "label": spec["label"],
        "bars": len(hist),
        "signals": signal_rows,
        "summary": {
            "signal_count": len(signal_rows),
            "signal_negative_5d": signal_negative_5d,
            "signal_negative_20d": signal_negative_20d,
            "signal_negative_60d": signal_negative_60d,
            "baseline_negative_5d": base_negative_5d,
            "baseline_negative_20d": base_negative_20d,
            "baseline_negative_60d": base_negative_60d,
            "signal_median_20d": round(100 * median(all_f20), 2) if all_f20 else None,
            "baseline_median_20d": round(100 * median(base_f20), 2) if base_f20 else None,
            "current_dd_count_25d": current_count,
            "current_market_state": current_state,
            "current_date": current.get("date"),
            "avg_dd_count_25d": round(sum(counts) / len(counts), 2) if counts else None,
            "max_dd_count_25d": max(counts) if counts else 0,
            "state_counts": state_counts,
            "pressure_days": len(pressure_rows),
            "pressure_negative_20d": round(100 * sum(1 for v in pressure_f20 if v < 0) / len(pressure_f20), 1) if pressure_f20 else None,
        },
    }


def benchmark_error(spec: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "key": spec["key"],
        "code": spec["code"],
        "symbol": spec["symbol"],
        "exchange": spec["exchange"],
        "name": spec["name"],
        "label": spec["label"],
        "error": error,
        "signals": [],
        "summary": {},
    }


def main() -> int:
    out = {
        "schema_v": 1,
        "signal_label": "Distribution Day",
        "updated": datetime.now().isoformat(timespec="seconds"),
        "window_days": WINDOW_DAYS,
        "drop_pct": DROP_PCT,
        "benchmarks": [],
    }

    for spec in BENCHMARKS:
        try:
            res = benchmark_backtest(spec)
            if res is None:
                res = benchmark_error(spec, "no data")
        except Exception as exc:
            res = benchmark_error(spec, str(exc))
        out["benchmarks"].append(res)

    all_signals = [s for b in out["benchmarks"] for s in b.get("signals", [])]
    out["signals_total"] = len(all_signals)
    out["benchmarks_with_data"] = sum(1 for b in out["benchmarks"] if not b.get("error"))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT_PATH)
    print(f"[distribution] written {OUT_PATH} | signals={out['signals_total']} | benchmarks={out['benchmarks_with_data']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
