#!/usr/bin/env python3
"""Build VQC turn-date backtest data from TradingView historical OHLCV.

The strategy uses daily bars to resample monthly candles, then triggers when the
current month close crosses above the open of the highest-volume completed month
within the recent lookback window.

Output:
  data/vqc_backtest.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
from tvDatafeed import Interval, TvDatafeed

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
CCASS_JSON = BASE / "ccass.json"
OUT_PATH = DATA_DIR / "vqc_backtest.json"

LOOKBACK_MONTHS = max(int(os.getenv("VQC_LOOKBACK_MONTHS", "24")), 3)
HORIZONS = [5, 20, 60]
DEFAULT_BARS = max(int(os.getenv("VQC_BACKTEST_BARS", "520")), 260)
DEFAULT_WORKERS = min(max(int(os.getenv("VQC_BACKTEST_WORKERS", "6")), 1), 8)
DEFAULT_BUCKET_LIMIT = max(int(os.getenv("VQC_BACKTEST_BUCKET_LIMIT", "150")), 0)

_tv_local = threading.local()


def mc_bucket(mc: float | None) -> str | None:
    if mc is None:
        return None
    if mc < 20:
        return "small"
    if mc < 100:
        return "mid"
    return "large"


def strength_bucket(volume_ratio: float | None) -> str | None:
    if volume_ratio is None:
        return None
    if volume_ratio >= 1.8:
        return "high"
    if volume_ratio >= 1.2:
        return "mid"
    return "low"


def load_universe(bucket_limit: int) -> list[dict[str, Any]]:
    if not CCASS_JSON.exists():
        raise FileNotFoundError(f"missing {CCASS_JSON}")
    doc = json.load(open(CCASS_JSON, encoding="utf-8"))
    stocks = [s for s in doc.get("stocks", []) if s.get("c") and s.get("n")]
    for s in stocks:
        try:
            s["mc"] = float(s.get("mc") or 0)
        except Exception:
            s["mc"] = 0.0
        s["mc_bucket"] = mc_bucket(s["mc"])

    bucketed: dict[str, list[dict[str, Any]]] = {"small": [], "mid": [], "large": []}
    for s in stocks:
        if s["mc_bucket"]:
            bucketed[s["mc_bucket"]].append(s)
    for key in bucketed:
        bucketed[key].sort(key=lambda x: x["mc"], reverse=True)

    if bucket_limit <= 0:
        out = []
        for key in ("small", "mid", "large"):
            out.extend(bucketed[key])
        return out

    def sample_spread(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if len(items) <= limit:
            return items[:]
        if limit <= 1:
            return [items[0]]
        idxs = []
        for i in range(limit):
            idx = round(i * (len(items) - 1) / (limit - 1))
            if idx not in idxs:
                idxs.append(idx)
        return [items[i] for i in idxs]

    out = []
    for key in ("small", "mid", "large"):
        out.extend(sample_spread(bucketed[key], bucket_limit))
    return out


def _tv() -> TvDatafeed:
    tv = getattr(_tv_local, "tv", None)
    if tv is None:
        u = os.getenv("TV_USER")
        p = os.getenv("TV_PASS")
        tv = TvDatafeed(u, p) if u else TvDatafeed()
        _tv_local.tv = tv
    return tv


def fetch_history(code: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
    sym = str(int(str(code).strip().zfill(5)))
    df = _tv().get_hist(symbol=sym, exchange="HKEX", interval=Interval.in_daily, n_bars=n_bars)
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


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame()
    tmp = df.copy()
    tmp["date"] = pd.to_datetime(tmp["date"])
    tmp = tmp.sort_values("date")
    tmp["month"] = tmp["date"].dt.to_period("M")
    grouped = tmp.groupby("month", sort=True)
    monthly = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    monthly["signal_date"] = grouped["date"].max().values
    monthly["month_start"] = grouped["date"].min().values
    return monthly


def _forward_return(df: pd.DataFrame, idx0: int, horizon: int, entry: float) -> float | None:
    tgt = idx0 + horizon
    if tgt >= len(df):
        return None
    px = float(df.iloc[tgt]["close"])
    if px <= 0 or entry <= 0:
        return None
    return round(px / entry - 1, 4)


def _max_gain_dd(df: pd.DataFrame, idx0: int, horizon: int, entry: float) -> tuple[float | None, float | None]:
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


def backtest_stock(stock: dict[str, Any], n_bars: int = DEFAULT_BARS) -> dict[str, Any] | None:
    code = str(stock.get("c", "")).zfill(5)
    name = stock.get("n") or code
    mc = float(stock.get("mc") or 0)
    bucket = stock.get("mc_bucket") or mc_bucket(mc)

    hist = fetch_history(code, n_bars=n_bars)
    if hist.empty or len(hist) < 100:
        return None
    monthly = resample_monthly(hist)
    if monthly.empty or len(monthly) < 3:
        return None

    hist_dates = pd.to_datetime(hist["date"])
    events: list[dict[str, Any]] = []
    baseline_20d: list[float] = []
    baseline_5d: list[float] = []
    baseline_60d: list[float] = []

    for i in range(1, len(monthly)):
        sig = monthly.iloc[i]
        sig_date = pd.to_datetime(sig["signal_date"]).normalize()
        idxs = hist_dates[hist_dates <= sig_date]
        if idxs.empty:
            continue
        idx0 = int(idxs.index[-1])
        entry = float(hist.iloc[idx0]["close"])
        if entry <= 0:
            continue
        baseline_5d.append(_forward_return(hist, idx0, 5, entry)) if idx0 + 5 < len(hist) else None
        if idx0 + 20 < len(hist):
            f20 = _forward_return(hist, idx0, 20, entry)
            if f20 is not None:
                baseline_20d.append(f20)
        if idx0 + 60 < len(hist):
            f60 = _forward_return(hist, idx0, 60, entry)
            if f60 is not None:
                baseline_60d.append(f60)

    for i in range(2, len(monthly)):
        current = monthly.iloc[i]
        prev = monthly.iloc[i - 1]
        lookback = monthly.iloc[:i].tail(LOOKBACK_MONTHS)
        if lookback.empty:
            continue
        ref_idx = lookback["volume"].astype(float).idxmax()
        if pd.isna(ref_idx):
            continue
        ref = lookback.loc[ref_idx]
        ref_open = float(ref["open"])
        if ref_open <= 0:
            continue
        current_close = float(current["close"])
        prev_close = float(prev["close"])
        if not (current_close > ref_open and prev_close <= ref_open):
            continue

        sig_date = pd.to_datetime(current["signal_date"]).normalize()
        idxs = hist_dates[hist_dates <= sig_date]
        if idxs.empty:
            continue
        idx0 = int(idxs.index[-1])
        entry = float(hist.iloc[idx0]["close"])
        if entry <= 0:
            continue
        avg_vol = float(lookback["volume"].astype(float).mean()) if not lookback.empty else None
        ref_vol = float(ref["volume"])
        vol_ratio = round(ref_vol / avg_vol, 2) if avg_vol and avg_vol > 0 else None
        event = {
            "code": code,
            "name": name,
            "mc": round(mc, 2),
            "mc_bucket": bucket,
            "signal_date": sig_date.strftime("%Y-%m-%d"),
            "data_month": pd.to_datetime(current["month"].to_timestamp()).strftime("%Y-%m"),
            "ref_month": pd.to_datetime(ref["month"].to_timestamp()).strftime("%Y-%m"),
            "ref_open": round(ref_open, 3),
            "ref_volume": int(ref_vol),
            "avg_volume": int(avg_vol) if avg_vol else None,
            "volume_ratio": vol_ratio,
            "strength_bucket": strength_bucket(vol_ratio),
            "entry_price": round(entry, 3),
            "break_value": round(current_close, 3),
            "break_pct": round((current_close / ref_open - 1) * 100, 2),
            "fwd_5d": _forward_return(hist, idx0, 5, entry),
            "fwd_20d": _forward_return(hist, idx0, 20, entry),
            "fwd_60d": _forward_return(hist, idx0, 60, entry),
            "max_gain_20d": None,
            "max_drawdown_20d": None,
        }
        mg, dd = _max_gain_dd(hist, idx0, 20, entry)
        event["max_gain_20d"] = mg
        event["max_drawdown_20d"] = dd
        events.append(event)

    return {
        "code": code,
        "name": name,
        "mc": round(mc, 2),
        "mc_bucket": bucket,
        "bars": len(hist),
        "months": len(monthly),
        "events": events,
        "baseline_5d": [v for v in baseline_5d if v is not None],
        "baseline_20d": [v for v in baseline_20d if v is not None],
        "baseline_60d": [v for v in baseline_60d if v is not None],
    }


def _bucket_stats(events: list[dict[str, Any]], key: str, values: list[str]) -> dict[str, Any]:
    out = {}
    for val in values:
        rows = [e for e in events if e.get(key) == val]
        f20 = [e["fwd_20d"] for e in rows if e.get("fwd_20d") is not None]
        f5 = [e["fwd_5d"] for e in rows if e.get("fwd_5d") is not None]
        out[val] = {
            "count": len(rows),
            "fwd5_win_rate": round(100 * sum(1 for x in f5 if x > 0) / len(f5), 1) if f5 else None,
            "fwd20_win_rate": round(100 * sum(1 for x in f20 if x > 0) / len(f20), 1) if f20 else None,
            "median_fwd20": round(100 * median(f20), 2) if f20 else None,
            "avg_fwd20": round(100 * (sum(f20) / len(f20)), 2) if f20 else None,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket-limit", type=int, default=DEFAULT_BUCKET_LIMIT,
                    help="Per market-cap bucket sample size. 0 = all stocks.")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help="Thread workers for TradingView fetches.")
    ap.add_argument("--bars", type=int, default=DEFAULT_BARS,
                    help="Daily bars to request per stock.")
    args = ap.parse_args()

    universe = load_universe(args.bucket_limit)
    total_universe = len(json.load(open(CCASS_JSON, encoding="utf-8")).get("stocks", []))
    print(f"[vqc] universe sample: {len(universe)} / {total_universe} stocks")

    per_code: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    errors = 0
    fetched = 0
    started = datetime.now()

    def work(stock: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return backtest_stock(stock, n_bars=args.bars)
        except Exception as exc:
            return {"error": str(exc), "code": stock.get("c"), "name": stock.get("n"), "mc_bucket": stock.get("mc_bucket")}

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut_map = {pool.submit(work, s): s for s in universe}
        for idx, fut in enumerate(cf.as_completed(fut_map), start=1):
            res = fut.result()
            if not res:
                continue
            if "error" in res:
                errors += 1
                if errors <= 10:
                    print(f"[vqc] error {res.get('code')}: {res['error']}")
                continue
            per_code.append(res)
            events.extend(res["events"])
            fetched += 1
            if fetched % 20 == 0:
                print(f"[vqc] fetched {fetched}/{len(universe)} stocks, events={len(events)}")

    # Aggregate.
    all_f5 = [e["fwd_5d"] for e in events if e.get("fwd_5d") is not None]
    all_f20 = [e["fwd_20d"] for e in events if e.get("fwd_20d") is not None]
    all_f60 = [e["fwd_60d"] for e in events if e.get("fwd_60d") is not None]
    base20 = [x for r in per_code for x in r.get("baseline_20d", []) if x is not None]
    base5 = [x for r in per_code for x in r.get("baseline_5d", []) if x is not None]
    base60 = [x for r in per_code for x in r.get("baseline_60d", []) if x is not None]

    strength_stats = _bucket_stats(events, "strength_bucket", ["high", "mid", "low"])
    mc_stats = _bucket_stats(events, "mc_bucket", ["small", "mid", "large"])

    top_winners = sorted([e for e in events if e.get("fwd_20d") is not None], key=lambda x: x["fwd_20d"], reverse=True)[:20]
    top_losers = sorted([e for e in events if e.get("fwd_20d") is not None], key=lambda x: x["fwd_20d"])[:20]

    out = {
        "schema_v": 1,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "lookback_months": LOOKBACK_MONTHS,
        "bars": args.bars,
        "bucket_limit": args.bucket_limit,
        "workers": args.workers,
        "universe_total": total_universe,
        "sample_total": len(universe),
        "stocks_with_data": len(per_code),
        "events_total": len(events),
        "events_with_f5": len(all_f5),
        "events_with_f20": len(all_f20),
        "events_with_f60": len(all_f60),
        "summary": {
            "signal_count": len(events),
            "signal_win_5d": round(100 * sum(1 for x in all_f5 if x > 0) / len(all_f5), 1) if all_f5 else None,
            "signal_win_20d": round(100 * sum(1 for x in all_f20 if x > 0) / len(all_f20), 1) if all_f20 else None,
            "signal_win_60d": round(100 * sum(1 for x in all_f60 if x > 0) / len(all_f60), 1) if all_f60 else None,
            "signal_median_5d": round(100 * median(all_f5), 2) if all_f5 else None,
            "signal_median_20d": round(100 * median(all_f20), 2) if all_f20 else None,
            "signal_median_60d": round(100 * median(all_f60), 2) if all_f60 else None,
            "baseline_median_20d": round(100 * median(base20), 2) if base20 else None,
            "baseline_win_20d": round(100 * sum(1 for x in base20 if x > 0) / len(base20), 1) if base20 else None,
            "baseline_median_5d": round(100 * median(base5), 2) if base5 else None,
            "baseline_median_60d": round(100 * median(base60), 2) if base60 else None,
        },
        "edge": {
            "edge_20d": None,
            "edge_win_20d": None,
        },
        "strength_stats": strength_stats,
        "mc_stats": mc_stats,
        "top_winners": top_winners,
        "top_losers": top_losers,
        "events": sorted(events, key=lambda x: (x.get("signal_date", ""), x.get("fwd_20d") if x.get("fwd_20d") is not None else -9999), reverse=True),
        "per_code": per_code,
    }
    if out["summary"]["signal_median_20d"] is not None and out["summary"]["baseline_median_20d"] is not None:
        out["edge"]["edge_20d"] = round(out["summary"]["signal_median_20d"] - out["summary"]["baseline_median_20d"], 2)
    if out["summary"]["signal_win_20d"] is not None and out["summary"]["baseline_win_20d"] is not None:
        out["edge"]["edge_win_20d"] = round(out["summary"]["signal_win_20d"] - out["summary"]["baseline_win_20d"], 1)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT_PATH)
    elapsed = (datetime.now() - started).total_seconds()
    print(f"[vqc] written {OUT_PATH} in {elapsed:.0f}s | events={len(events)} | codes={len(per_code)} | errors={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
