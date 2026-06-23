#!/usr/bin/env python3
"""Build 節氣窗口 backtest data."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
import requests
from tvDatafeed import Interval, TvDatafeed

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
CCASS_JSON = BASE / "ccass.json"
CAL_PATH = DATA_DIR / "jieqi_calendar.json"
OUT_PATH = DATA_DIR / "jieqi_backtest.json"

START_YEAR = max(int(os.getenv("JIEQI_START_YEAR", "2018")), 1900)
END_YEAR = int(os.getenv("JIEQI_END_YEAR", str(datetime.now().year)))
DEFAULT_BARS = max(int(os.getenv("JIEQI_BACKTEST_BARS", "520")), 260)
DEFAULT_BUCKET_LIMIT = max(int(os.getenv("JIEQI_BUCKET_LIMIT", "25")), 0)

TERM_NAMES = [
    "小寒", "大寒", "立春", "雨水", "驚蟄", "春分", "清明", "穀雨",
    "立夏", "小滿", "芒種", "夏至", "小暑", "大暑", "立秋", "處暑",
    "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
]
TERM_IDS = list(range(1, 25))
TERM_MAP = dict(zip(TERM_IDS, TERM_NAMES))
SHEUP_URL = "https://sheup.org/24jieqi_3.php"
SHEUP_URLS = [
    "https://sheup.org/24jieqi_3.php",
    "https://sheup.org/24jieqi.php",
]
WINDOW_OFFSETS = [-2, -1, 0, 1, 2]
WINDOW_SPAN = 2

_tv_local = threading.local()


def load_json(path: Path, default: Any) -> Any:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def atomic_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def _tv() -> TvDatafeed:
    tv = getattr(_tv_local, "tv", None)
    if tv is None:
        u = os.getenv("TV_USER")
        p = os.getenv("TV_PASS")
        tv = TvDatafeed(u, p) if u else TvDatafeed()
        _tv_local.tv = tv
    return tv


def mc_bucket(mc: float | None) -> str | None:
    if mc is None:
        return None
    if mc < 20:
        return "small"
    if mc < 100:
        return "mid"
    return "large"


def load_universe(bucket_limit: int) -> list[dict[str, Any]]:
    doc = load_json(CCASS_JSON, {})
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
        out: list[dict[str, Any]] = []
        for key in ("small", "mid", "large"):
            out.extend(bucketed[key])
        return out

    def sample_spread(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if len(items) <= limit:
            return items[:]
        if limit <= 1:
            return [items[0]]
        idxs: list[int] = []
        for i in range(limit):
            idx = round(i * (len(items) - 1) / (limit - 1))
            if idx not in idxs:
                idxs.append(idx)
        return [items[i] for i in idxs]

    out = []
    for key in ("small", "mid", "large"):
        out.extend(sample_spread(bucketed[key], bucket_limit))
    return out


def fetch_history(symbol: str, exchange: str = "HKEX", n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
    raw = str(symbol).strip()
    sym = str(int(raw.zfill(5))) if exchange.upper() == "HKEX" and raw.isdigit() else raw.upper()
    df = _tv().get_hist(symbol=sym, exchange=exchange, interval=Interval.in_daily, n_bars=n_bars)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    cols = {c.lower(): c for c in df.columns}
    want = {k: cols[k] for k in ("open", "high", "low", "close", "volume") if k in cols}
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


def fetch_term_date(year: int, term_id: int) -> str:
    payload = {"nf": str(year), "jieqi": str(term_id), "chaxun": "查詢"}
    last_err: Exception | None = None
    for url in SHEUP_URLS:
        for method in ("get", "post"):
            try:
                if method == "get":
                    r = requests.get(url, params=payload, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                else:
                    r = requests.post(url, data=payload, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                r.encoding = "utf-8"
                m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", r.text)
                if m:
                    y, mo, d = map(int, m.groups())
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            except Exception as exc:
                last_err = exc
                continue
    raise RuntimeError(f"cannot parse jieqi date for {year} term {term_id}: {last_err}")


def load_calendar() -> dict[str, Any]:
    cal = load_json(CAL_PATH, {"updated": "", "source": SHEUP_URL, "years": {}})
    years = cal.setdefault("years", {})
    changed = False
    for year in range(START_YEAR, END_YEAR + 1):
        yk = str(year)
        row = years.setdefault(yk, {})
        for term_id in TERM_IDS:
            tk = str(term_id)
            if not row.get(tk):
                row[tk] = {"name": TERM_MAP[term_id], "date": fetch_term_date(year, term_id)}
                changed = True
    if changed or not cal.get("updated"):
        cal["updated"] = datetime.now().isoformat()
        cal["source"] = SHEUP_URL
        atomic_write(CAL_PATH, cal)
    return cal


def calendar_events(cal: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for y, row in sorted((cal.get("years") or {}).items()):
        for tid, rec in sorted(row.items(), key=lambda kv: int(kv[0])):
            if not rec or not rec.get("date"):
                continue
            out.append({
                "year": int(y),
                "term_id": int(tid),
                "term_name": rec.get("name") or TERM_MAP.get(int(tid), ""),
                "date": rec["date"],
            })
    return out


def next_trade_index(hist_dates: pd.DatetimeIndex, term_date: str) -> int | None:
    idx = int(hist_dates.searchsorted(pd.Timestamp(term_date), side="left"))
    return None if idx >= len(hist_dates) else idx


def forward_return(df: pd.DataFrame, idx0: int, horizon: int, entry: float) -> float | None:
    tgt = idx0 + horizon
    if tgt >= len(df) or entry <= 0:
        return None
    px = float(df.iloc[tgt]["close"])
    return None if px <= 0 else round(px / entry - 1, 4)


def max_gain_dd(df: pd.DataFrame, idx0: int, horizon: int, entry: float) -> tuple[float | None, float | None]:
    if entry <= 0:
        return None, None
    window = df.iloc[idx0 + 1 : idx0 + 1 + horizon]
    if window.empty:
        return None, None
    closes = window["close"].astype(float)
    closes = closes[closes > 0]
    if closes.empty:
        return None, None
    return round(float(closes.max()) / entry - 1, 4), round(float(closes.min()) / entry - 1, 4)


def turn_window(df: pd.DataFrame, idx0: int) -> dict[str, Any] | None:
    if idx0 < 2 or idx0 + 1 >= len(df):
        return None
    prev_close = float(df.iloc[idx0 - 2]["close"])
    pre_close = float(df.iloc[idx0 - 1]["close"])
    entry = float(df.iloc[idx0]["close"])
    if prev_close <= 0 or pre_close <= 0 or entry <= 0:
        return None
    pre_ret = pre_close / prev_close - 1
    if pre_ret == 0:
        return None
    window = df.iloc[idx0 + 1 : idx0 + 3]
    if window.empty:
        return None
    max_high = float(window["high"].max())
    min_low = float(window["low"].min())
    max_close = float(window["close"].max())
    min_close = float(window["close"].min())
    prev_dir = "down" if pre_ret < 0 else "up"
    if prev_dir == "down":
        hit = max_high > entry
        best_move = max_high / entry - 1
        close_move = max_close / entry - 1
    else:
        hit = min_low < entry
        best_move = entry / min_low - 1 if min_low > 0 else None
        close_move = entry / min_close - 1 if min_close > 0 else None
    return {
        "prev_day_direction": prev_dir,
        "prev_day_return": round(pre_ret, 4),
        "turn_hit_2d": bool(hit),
        "turn_move_2d": round(best_move, 4) if best_move is not None else None,
        "turn_close_move_2d": round(close_move, 4) if close_move is not None else None,
    }


def build_turn_cache(hist: pd.DataFrame) -> dict[int, dict[str, Any]]:
    cache: dict[int, dict[str, Any]] = {}
    for i in range(2, len(hist) - 1):
        tw = turn_window(hist, i)
        if tw:
            cache[i] = tw
    return cache


def window_any_hit(turn_cache: dict[int, dict[str, Any]], center_idx: int) -> bool | None:
    hits: list[bool] = []
    for off in WINDOW_OFFSETS:
        tw = turn_cache.get(center_idx + off)
        if tw is not None:
            hits.append(bool(tw.get("turn_hit_2d")))
    return None if not hits else any(hits)


def analyze_asset(hist: pd.DataFrame, signal_dates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if hist.empty or len(hist) < 100:
        return None
    hist_dates = pd.to_datetime(hist["date"])
    turn_cache = build_turn_cache(hist)
    events: list[dict[str, Any]] = []
    signal_windows: list[dict[str, Any]] = []
    baseline_turns: list[dict[str, Any]] = []
    window_baseline_hits: list[bool] = []
    baseline_20d: list[float] = []

    for i in range(2, len(hist) - 1):
        tw = turn_cache.get(i) or turn_window(hist, i)
        if tw:
            baseline_turns.append(tw)
        f20 = forward_return(hist, i, 20, float(hist.iloc[i]["close"]))
        if f20 is not None:
            baseline_20d.append(f20)
        wh = window_any_hit(turn_cache, i)
        if wh is not None:
            window_baseline_hits.append(wh)

    for ev in signal_dates:
        idx0 = next_trade_index(hist_dates, ev["date"])
        if idx0 is None:
            continue
        anchor_date = hist.iloc[idx0]["date"].strftime("%Y-%m-%d")
        candidate_rows: list[dict[str, Any]] = []
        for off in WINDOW_OFFSETS:
            idx = idx0 + off
            if idx < 2 or idx >= len(hist) - 1:
                continue
            tw = turn_cache.get(idx) or turn_window(hist, idx)
            if not tw:
                continue
            entry = float(hist.iloc[idx]["close"])
            if entry <= 0:
                continue
            ev_row = {
                "term_id": ev["term_id"],
                "term_name": ev["term_name"],
                "signal_date": ev["date"],
                "anchor_date": anchor_date,
                "window_offset": off,
                "window_label": f"{off:+d}日",
                "date": hist.iloc[idx]["date"].strftime("%Y-%m-%d"),
                "entry": round(entry, 4),
                **tw,
                "fwd_2d": forward_return(hist, idx, 2, entry),
                "fwd_5d": forward_return(hist, idx, 5, entry),
                "fwd_20d": forward_return(hist, idx, 20, entry),
                "fwd_60d": forward_return(hist, idx, 60, entry),
            }
            mg20, dd20 = max_gain_dd(hist, idx, 20, entry)
            ev_row["max_gain_20d"] = mg20
            ev_row["max_drawdown_20d"] = dd20
            candidate_rows.append(ev_row)
            events.append(ev_row)
        if candidate_rows:
            best_row = max(
                candidate_rows,
                key=lambda r: (
                    1 if r.get("turn_hit_2d") else 0,
                    -abs(r.get("window_offset", 0)),
                    r.get("turn_move_2d") if r.get("turn_move_2d") is not None else -999.0,
                ),
            )
            signal_windows.append({
                "term_id": ev["term_id"],
                "term_name": ev["term_name"],
                "signal_date": ev["date"],
                "anchor_date": anchor_date,
                "window_any_hit": any(bool(r.get("turn_hit_2d")) for r in candidate_rows),
                "window_best_offset": best_row.get("window_offset"),
                "window_best_date": best_row.get("date"),
                "window_best_move_2d": best_row.get("turn_move_2d"),
                "window_best_turn_hit_2d": bool(best_row.get("turn_hit_2d")),
                "window_candidates": len(candidate_rows),
            })

    if not events:
        return None

    def rate(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        return round(100 * sum(1 for r in rows if r.get("turn_hit_2d")) / len(rows), 1)

    def neg_rate(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(100 * sum(1 for v in vals if v < 0) / len(vals), 1)

    def any_rate(vals: list[bool]) -> float | None:
        if not vals:
            return None
        return round(100 * sum(1 for v in vals if v) / len(vals), 1)

    down = [r for r in events if r.get("prev_day_direction") == "down"]
    up = [r for r in events if r.get("prev_day_direction") == "up"]
    base_down = [r for r in baseline_turns if r.get("prev_day_direction") == "down"]
    base_up = [r for r in baseline_turns if r.get("prev_day_direction") == "up"]
    all_f20 = [r["fwd_20d"] for r in events if r.get("fwd_20d") is not None]
    base_f20 = baseline_20d
    window_hits = [bool(r.get("window_any_hit")) for r in signal_windows if r.get("window_any_hit") is not None]
    baseline_window_rate = any_rate(window_baseline_hits)
    window_rate = any_rate(window_hits)

    def med(vals: list[float]) -> float | None:
        return None if not vals else round(float(median(vals)), 4)

    offset_stats: list[dict[str, Any]] = []
    for off in WINDOW_OFFSETS:
        rows = [r for r in events if r.get("window_offset") == off]
        if not rows:
            continue
        offset_stats.append({
            "window_offset": off,
            "label": f"{off:+d}D",
            "count": len(rows),
            "hit_rate_2d": rate(rows),
            "edge_turn_2d": None,
            "median_20d": med([r["fwd_20d"] for r in rows if r.get("fwd_20d") is not None]),
            "median_move_2d": med([r["turn_move_2d"] for r in rows if r.get("turn_move_2d") is not None]),
        })

    base_hit = rate(baseline_turns) or 0
    for row in offset_stats:
        if row["hit_rate_2d"] is not None:
            row["edge_turn_2d"] = round(row["hit_rate_2d"] - base_hit, 1)

    best_offset_row = None
    if offset_stats:
        best_offset_row = max(
            offset_stats,
            key=lambda r: (
                r.get("hit_rate_2d") if r.get("hit_rate_2d") is not None else -9999,
                r.get("count") or 0,
                -(abs(r.get("window_offset") or 0)),
            ),
        )

    window_best = None
    if events:
        window_best = {
            "window_rate_any": window_rate,
            "baseline_window_rate_any": baseline_window_rate,
            "edge_window_any": None if window_rate is None or baseline_window_rate is None else round(window_rate - baseline_window_rate, 1),
        }

    return {
        "events": events,
        "summary": {
            "signal_count": len(events),
            "window_span_days": WINDOW_SPAN,
            "window_rate_any": window_rate,
            "baseline_window_rate_any": baseline_window_rate,
            "edge_window_any": None if window_rate is None or baseline_window_rate is None else round(window_rate - baseline_window_rate, 1),
            "best_offset": best_offset_row.get("window_offset") if best_offset_row else None,
            "best_offset_rate_2d": best_offset_row.get("hit_rate_2d") if best_offset_row else None,
            "overall_rate_2d": rate(events),
            "down_rebound_rate_2d": rate(down),
            "up_pullback_rate_2d": rate(up),
            "baseline_overall_rate_2d": rate(baseline_turns),
            "baseline_down_rebound_rate_2d": rate(base_down),
            "baseline_up_pullback_rate_2d": rate(base_up),
            "signal_median_2d": med([r["turn_move_2d"] for r in events if r.get("turn_move_2d") is not None]),
            "signal_median_20d": med(all_f20),
            "baseline_median_20d": med(base_f20),
            "baseline_win_20d": neg_rate(base_f20),
        },
        "baseline": {
            "count": len(baseline_turns),
            "hit_rate_2d": rate(baseline_turns),
            "down_hit_rate_2d": rate(base_down),
            "up_hit_rate_2d": rate(base_up),
            "median_20d": med(base_f20),
            "win_20d": neg_rate(base_f20),
            "window_rate_any": baseline_window_rate,
        },
        "window": {**(window_best or {}), "sample_total": len(signal_windows)},
        "offset_stats": offset_stats,
        "signal_windows": signal_windows,
    }


def main() -> None:
    cal = load_calendar()
    signal_dates = calendar_events(cal)
    universe = load_universe(DEFAULT_BUCKET_LIMIT)

    # benchmark proxies
    benchmarks = []
    for spec in [
        {"key": "hk", "code": "HSI1!", "symbol": "HSI1!", "exchange": "HKEX", "name": "Hang Seng Proxy", "label": "HK proxy"},
    ]:
        hist = fetch_history(spec["symbol"], exchange=spec["exchange"])
        res = analyze_asset(hist, signal_dates)
        if not res:
            benchmarks.append({**spec, "error": "no data"})
            continue
        benchmarks.append({
            **spec,
            "bars": len(hist),
            "summary": {**res["summary"], "current_date": hist.iloc[-1]["date"].strftime("%Y-%m-%d")},
            "signals": res["events"][:400],
        })

    # sample universe
    stock_results: list[dict[str, Any]] = []
    stock_events: list[dict[str, Any]] = []
    stock_signal_windows: list[dict[str, Any]] = []
    base_turns: list[dict[str, Any]] = []
    base_20d: list[float] = []
    base_window_hits: list[bool] = []
    sample_offset_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    sampled_ok = 0
    for stock in universe:
        code = str(stock.get("c", "")).zfill(5)
        symbol = str(stock.get("symbol") or code)
        exchange = str(stock.get("exchange") or "HKEX")
        hist = fetch_history(symbol, exchange=exchange)
        res = analyze_asset(hist, signal_dates)
        if not res:
            continue
        sampled_ok += 1
        turn_cache = build_turn_cache(hist)
        stock_results.append({
            "code": code,
            "name": stock.get("n") or code,
            "exchange": exchange,
            "mc_bucket": stock.get("mc_bucket"),
            "events_total": len(res["events"]),
            **res["summary"],
        })
        for ev in res["events"]:
            stock_events.append({
                **ev,
                "code": code,
                "name": stock.get("n") or code,
                "mc_bucket": stock.get("mc_bucket"),
            })
        for sw in res.get("signal_windows", []):
            stock_signal_windows.append({
                **sw,
                "code": code,
                "name": stock.get("n") or code,
                "mc_bucket": stock.get("mc_bucket"),
            })
        for row in res.get("offset_stats", []):
            sample_offset_rows[int(row.get("window_offset", 0))].append(row)
        for i in range(2, len(hist) - 1):
            tw = turn_cache.get(i) or turn_window(hist, i)
            if tw:
                base_turns.append(tw)
            wh = window_any_hit(turn_cache, i)
            if wh is not None:
                base_window_hits.append(bool(wh))
            f20 = forward_return(hist, i, 20, float(hist.iloc[i]["close"]))
            if f20 is not None:
                base_20d.append(f20)

    def hit(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        return round(100 * sum(1 for r in rows if r.get("turn_hit_2d")) / len(rows), 1)

    def neg(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(100 * sum(1 for v in vals if v < 0) / len(vals), 1)

    def med(vals: list[float]) -> float | None:
        return None if not vals else round(float(median(vals)), 4)

    def any_rate(vals: list[bool]) -> float | None:
        if not vals:
            return None
        return round(100 * sum(1 for v in vals if v) / len(vals), 1)

    sample_down = [r for r in stock_events if r.get("prev_day_direction") == "down"]
    sample_up = [r for r in stock_events if r.get("prev_day_direction") == "up"]
    base_down = [r for r in base_turns if r.get("prev_day_direction") == "down"]
    base_up = [r for r in base_turns if r.get("prev_day_direction") == "up"]
    sample_window_hits = [bool(r.get("window_any_hit")) for r in stock_signal_windows if r.get("window_any_hit") is not None]

    sample_summary = {
        "signal_count": len(stock_events),
        "overall_rate_2d": hit(stock_events),
        "down_rebound_rate_2d": hit(sample_down),
        "up_pullback_rate_2d": hit(sample_up),
        "baseline_overall_rate_2d": hit(base_turns),
        "baseline_down_rebound_rate_2d": hit(base_down),
        "baseline_up_pullback_rate_2d": hit(base_up),
        "window_rate_any": any_rate(sample_window_hits),
        "baseline_window_rate_any": any_rate(base_window_hits),
        "signal_median_2d": round(float(median([r["turn_move_2d"] for r in stock_events if r.get("turn_move_2d") is not None])), 4) if any(r.get("turn_move_2d") is not None for r in stock_events) else None,
        "signal_median_20d": round(float(median([r["fwd_20d"] for r in stock_events if r.get("fwd_20d") is not None])), 4) if any(r.get("fwd_20d") is not None for r in stock_events) else None,
        "baseline_median_20d": round(float(median(base_20d)), 4) if base_20d else None,
        "baseline_win_20d": neg(base_20d),
    }

    term_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    window_term_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in stock_events:
        term_rows[ev["term_name"]].append(ev)
    for sw in stock_signal_windows:
        window_term_rows[sw["term_name"]].append(sw)
    term_stats = []
    for term_name in TERM_NAMES:
        rows = term_rows.get(term_name, [])
        wrows = window_term_rows.get(term_name, [])
        if not rows and not wrows:
            continue
        drows = [r for r in rows if r.get("prev_day_direction") == "down"]
        urows = [r for r in rows if r.get("prev_day_direction") == "up"]
        exact_rows = [r for r in rows if r.get("window_offset") == 0]
        term_stats.append({
            "term_name": term_name,
            "count": len(wrows) or len(rows),
            "window_count": len(wrows),
            "window_rate_any": any_rate([bool(r.get("window_any_hit")) for r in wrows]) if wrows else None,
            "exact_rate_2d": hit(exact_rows) if exact_rows else None,
            "down_rebound_rate_2d": hit(drows),
            "up_pullback_rate_2d": hit(urows),
            "median_20d": round(float(median([r["fwd_20d"] for r in exact_rows if r.get("fwd_20d") is not None])), 4) if any(r.get("fwd_20d") is not None for r in exact_rows) else None,
            "edge_turn_2d": None,
            "edge_window_any": None,
        })
    base_hit = sample_summary["baseline_overall_rate_2d"] or 0
    base_window = sample_summary["baseline_window_rate_any"] or 0
    for row in term_stats:
        if row["exact_rate_2d"] is not None:
            row["edge_turn_2d"] = round(row["exact_rate_2d"] - base_hit, 1)
        if row["window_rate_any"] is not None:
            row["edge_window_any"] = round(row["window_rate_any"] - base_window, 1)
    term_stats.sort(key=lambda r: r["edge_window_any"] if r["edge_window_any"] is not None else -9999, reverse=True)

    offset_stats: list[dict[str, Any]] = []
    for off in WINDOW_OFFSETS:
        rows = sample_offset_rows.get(off, [])
        if not rows:
            continue
        total_count = sum(int(r.get("count") or 0) for r in rows)
        if total_count <= 0:
            continue
        hit_total = sum((float(r.get("hit_rate_2d") or 0) * int(r.get("count") or 0)) for r in rows) / 100.0
        median_20d = med([float(r["median_20d"]) for r in rows if r.get("median_20d") is not None])
        median_move_2d = med([float(r["median_move_2d"]) for r in rows if r.get("median_move_2d") is not None])
        hit_rate_2d = round(100 * hit_total / total_count, 1)
        offset_stats.append({
            "window_offset": off,
            "label": f"{off:+d}D",
            "count": total_count,
            "hit_rate_2d": hit_rate_2d,
            "edge_turn_2d": round(hit_rate_2d - (sample_summary["baseline_overall_rate_2d"] or 0), 1),
            "median_20d": median_20d,
            "median_move_2d": median_move_2d,
        })

    out = {
        "schema_v": 1,
        "updated": datetime.now().isoformat(),
        "source": {"calendar": SHEUP_URL, "market": "tvDatafeed / TradingView", "universe": "ccass.json"},
        "years": len(cal.get("years", {})),
        "calendar": cal,
        "terms_total": len(signal_dates),
        "sample_total": sampled_ok,
        "universe_total": len(universe),
        "events_total": len(stock_events),
        "summary": sample_summary,
        "term_stats": term_stats,
        "top_terms": term_stats[:8],
        "bottom_terms": list(reversed(term_stats[-8:])),
        "offset_stats": offset_stats,
        "signal_windows": stock_signal_windows[:600],
        "benchmarks": benchmarks,
        "reference_examples": benchmarks,
        "events": stock_events[:600],
        "stock_results": sorted(stock_results, key=lambda x: x.get("overall_rate_2d") or 0, reverse=True)[:50],
    }
    atomic_write(OUT_PATH, out)
    print(f"Generated {OUT_PATH}")
    print(f"Generated {CAL_PATH}")


if __name__ == "__main__":
    main()
