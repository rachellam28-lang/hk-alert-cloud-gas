#!/usr/bin/env python3
"""Build an auditable day/night trend matrix for Hong Kong indices.

Observed index and main-contract futures K-lines come from the local Futu
OpenD session. The five-grid fields are observed high, low, midpoint, open,
and close; trend labels are derived rules, not forecasts.
Missing or incomplete night sessions never receive a synthetic close.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "trend_matrix.json"
JIEQI_PATH = ROOT / "data" / "jieqi_calendar.json"
INDEXES = {
    "HSI": {"label": "恒生指數", "index_code": "HK.800000", "future_code": "HK.HSImain"},
    "HSCEI": {"label": "國企指數", "index_code": "HK.800100", "future_code": "HK.HHImain"},
    "HSTECH": {"label": "恒生科技指數", "index_code": "HK.800700", "future_code": "HK.HTImain"},
}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def round_value(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def load_jieqi() -> dict[str, str]:
    payload = read_json(JIEQI_PATH, {})
    result: dict[str, str] = {}
    for year in (payload.get("years") or {}).values():
        if not isinstance(year, dict):
            continue
        for item in year.values():
            if isinstance(item, dict) and item.get("date") and item.get("name"):
                result[str(item["date"])] = str(item["name"])
    return result


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def validate_bar(row: dict, *, intraday: bool) -> dict | None:
    stamp = str(row.get("time_key") or row.get("time") or "")
    parsed = parse_time(stamp)
    open_ = finite(row.get("open"))
    high = finite(row.get("high"))
    low = finite(row.get("low"))
    close = finite(row.get("close"))
    if parsed is None or any(value is None or value <= 0 for value in (open_, high, low, close)):
        return None
    if high < max(open_, close, low) or low > min(open_, close, high):
        return None
    return {
        "time": parsed.isoformat(sep=" ", timespec="seconds") if intraday else parsed.date().isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": max(0.0, finite(row.get("volume")) or 0.0),
    }


def fetch_history(context, code: str, ktype, start: date, end: date, *, intraday: bool) -> list[dict]:
    from futu import AuType, RET_OK

    rows: list[dict] = []
    page_req_key = None
    while True:
        ret, frame, page_req_key = context.request_history_kline(
            code,
            start=start.isoformat(),
            end=end.isoformat(),
            ktype=ktype,
            autype=AuType.NONE,
            max_count=1000,
            page_req_key=page_req_key,
        )
        if ret != RET_OK or frame is None or frame.empty:
            raise RuntimeError(str(frame) if frame is not None else f"ret={ret}")
        for _, source in frame.iterrows():
            item = validate_bar(source.to_dict(), intraday=intraday)
            if item:
                rows.append(item)
        if not page_req_key:
            break
    deduped = {row["time"]: row for row in rows}
    return [deduped[key] for key in sorted(deduped)]


def aggregate_night_sessions(bars: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in bars:
        stamp = parse_time(row.get("time"))
        if stamp is None:
            continue
        current = stamp.time()
        if current >= time(17, 0):
            session_date = stamp.date()
        elif current <= time(3, 15):
            session_date = stamp.date() - timedelta(days=1)
        else:
            continue
        grouped[session_date.isoformat()].append(row)

    result: dict[str, dict] = {}
    for session_date, items in grouped.items():
        items.sort(key=lambda item: item["time"])
        last_stamp = parse_time(items[-1]["time"])
        session_day = date.fromisoformat(session_date)
        complete = bool(last_stamp and last_stamp.date() > session_day and last_stamp.time() <= time(3, 15))
        result[session_date] = {
            "session_date": session_date,
            "open": items[0]["open"],
            "high": max(item["high"] for item in items),
            "low": min(item["low"] for item in items),
            "mid": round_value((max(item["high"] for item in items) + min(item["low"] for item in items)) / 2),
            "close": items[-1]["close"] if complete else None,
            "last_observed": items[-1]["close"],
            "volume": sum(item["volume"] for item in items),
            "bars": len(items),
            "complete": complete,
            "observed_at": items[-1]["time"],
        }
    return result


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1)
    output: list[float] = []
    current = values[0]
    for value in values:
        current = value if not output else alpha * value + (1 - alpha) * current
        output.append(current)
    return output


def trend_label(score: int) -> tuple[str, str]:
    if score >= 4:
        return "strong_bull", "強勢向上"
    if score >= 2:
        return "bull", "偏多"
    if score <= -4:
        return "strong_bear", "強勢向下"
    if score <= -2:
        return "bear", "偏空"
    return "range", "區間"


def nearest_observed_levels(previous: list[dict], price: float) -> dict[str, dict | None]:
    candidates: list[dict] = []
    for bar in previous:
        for field in ("high", "low"):
            value = finite(bar.get(field))
            if value is not None and value > 0:
                candidates.append({"value": value, "date": bar["time"], "field": field})
    above = min((item for item in candidates if item["value"] > price), key=lambda item: item["value"] - price, default=None)
    below = min((item for item in candidates if item["value"] < price), key=lambda item: price - item["value"], default=None)
    return {
        "above": {**above, "value": round_value(above["value"])} if above else None,
        "below": {**below, "value": round_value(below["value"])} if below else None,
    }


def build_matrix(daily: list[dict], nights: dict[str, dict], jieqi: dict[str, str]) -> list[dict]:
    daily = sorted(daily, key=lambda item: item["time"])
    closes = [float(item["close"]) for item in daily]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rows: list[dict] = []
    previous_state = None
    cycle_days = 0

    for index, bar in enumerate(daily):
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        midpoint = (high + low) / 2
        previous20 = daily[max(0, index - 20):index]
        previous_high = max((float(item["high"]) for item in previous20), default=None)
        previous_low = min((float(item["low"]) for item in previous20), default=None)
        average_volume = (
            sum(float(item["volume"]) for item in previous20) / len(previous20)
            if previous20 else None
        )
        volume_ratio = float(bar["volume"]) / average_volume if average_volume else None
        momentum5 = (close / closes[index - 5] - 1) * 100 if index >= 5 and closes[index - 5] else None
        night = nights.get(bar["time"])
        night_close = finite(night.get("close")) if night and night.get("complete") else None
        night_change = night_close - close if night_close is not None else None
        night_change_pct = night_change / close * 100 if night_change is not None and close else None
        references = nearest_observed_levels(daily[max(0, index - 60):index], night_close if night_close is not None else close)

        components = {
            "close_vs_ema20": 1 if close >= ema20[index] else -1,
            "ema20_vs_ema50": 1 if ema20[index] >= ema50[index] else -1,
            "momentum_5d": 1 if momentum5 is not None and momentum5 >= 0 else (-1 if momentum5 is not None else 0),
            "close_vs_day_mid": 1 if close >= midpoint else -1,
            "channel_20d": 2 if previous_high is not None and close > previous_high else (-2 if previous_low is not None and close < previous_low else 0),
            "volume_confirmation": 0,
            "completed_night": 1 if night_change is not None and night_change >= 0 else (-1 if night_change is not None else 0),
        }
        day_return = (close / float(daily[index - 1]["close"]) - 1) if index else 0
        if volume_ratio is not None and volume_ratio >= 1.2 and day_return:
            components["volume_confirmation"] = 1 if day_return > 0 else -1
        score = sum(components.values())
        state, label = trend_label(score)
        regime = "bull" if score >= 2 else ("bear" if score <= -2 else "range")
        cycle_days = cycle_days + 1 if regime == previous_state else 1
        previous_state = regime
        confirmed = (
            "向上突破確認" if components["channel_20d"] == 2 and (volume_ratio or 0) >= 1.2
            else "向下突破確認" if components["channel_20d"] == -2 and (volume_ratio or 0) >= 1.2
            else "未有量價突破確認"
        )
        rows.append({
            "date": bar["time"],
            "day": {key: round_value(finite(bar.get(key))) for key in ("open", "high", "low", "close", "volume")},
            "night": night,
            "night_change": round_value(night_change),
            "night_change_pct": round_value(night_change_pct),
            "five_grid": {
                "high": round_value(high),
                "low": round_value(low),
                "mid": round_value(midpoint),
                "open": round_value(finite(bar.get("open"))),
                "close": round_value(close),
            },
            "reference_levels": references,
            "indicators": {
                "ema20": round_value(ema20[index]),
                "ema50": round_value(ema50[index]),
                "momentum_5d_pct": round_value(momentum5),
                "volume_ratio_20d": round_value(volume_ratio),
                "prior_high_20d": round_value(previous_high),
                "prior_low_20d": round_value(previous_low),
            },
            "trend": {
                "score": score,
                "state": state,
                "label": label,
                "cycle_days": cycle_days,
                "confirmation": confirmed,
                "components": components,
            },
            "calendar": {"jieqi": jieqi.get(bar["time"])},
        })
    return rows


def build_payload(days: int) -> dict:
    try:
        from futu import KLType, OpenQuoteContext, RET_OK
        try:
            from scripts.futu_env import get_futu_host, get_futu_port, load_repo_env
        except ModuleNotFoundError:
            from futu_env import get_futu_host, get_futu_port, load_repo_env
    except Exception as exc:
        raise RuntimeError(f"Futu SDK unavailable: {exc}") from exc

    load_repo_env(ROOT)
    jieqi = load_jieqi()
    end = date.today()
    start = end - timedelta(days=max(420, days * 2))
    intraday_start = end - timedelta(days=max(120, days))
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    indexes: dict[str, dict] = {}
    errors: list[str] = []
    context = OpenQuoteContext(host=get_futu_host(), port=get_futu_port())
    try:
        ret, state = context.get_global_state()
        if ret != RET_OK or not isinstance(state, dict) or not state.get("qot_logined"):
            raise RuntimeError("Futu quote backend not logged in")
        for key, config in INDEXES.items():
            try:
                daily = fetch_history(context, config["index_code"], KLType.K_DAY, start, end, intraday=False)[-days:]
                future_bars = fetch_history(
                    context,
                    config["future_code"],
                    KLType.K_60M,
                    intraday_start,
                    end,
                    intraday=True,
                )
                nights = aggregate_night_sessions(future_bars)
                matrix = build_matrix(daily, nights, jieqi)
                if len(matrix) < 50:
                    raise RuntimeError(f"only {len(matrix)} valid daily bars")
                last_night = max(nights.values(), key=lambda item: item["observed_at"], default=None)
                indexes[key] = {
                    **config,
                    "label": config["label"],
                    "day_source": "Futu OpenD observed index daily K-line (unadjusted)",
                    "night_source": "Futu OpenD observed main-contract 60-minute K-line",
                    "daily_observed_through": matrix[-1]["date"],
                    "night_observed_through": last_night.get("observed_at") if last_night else None,
                    "rows": matrix[-120:],
                }
            except Exception as exc:
                errors.append(f"{key}: {exc}")
    finally:
        context.close()

    if not indexes:
        raise RuntimeError("; ".join(errors) or "no index data")
    return {
        "schema_v": 2,
        "generated_at": generated_at,
        "status": "PASS" if len(indexes) == len(INDEXES) else "PARTIAL",
        "stale": False,
        "data_kind": "derived_rule_output_from_observed_futu_kbars",
        "is_observed": False,
        "observations_are_real": True,
        "scope": "HK indices with completed night sessions; all HK stocks are calculated on demand without a night factor",
        "formula": {
            "five_grid": "observed High, observed Low, (High+Low)/2, observed Open, observed Close",
            "reference_levels": "nearest prior observed High/Low within 60 sessions; current and future bars excluded",
            "trend_score": "close/EMA20 + EMA20/EMA50 + 5D momentum + close/day midpoint + 20D channel + volume confirmation + completed night direction",
        },
        "disclaimer": "Five-grid OHLC fields are observations. Trend and historical reference levels are deterministic derived rules, not a price forecast. Incomplete night sessions are excluded from the score.",
        "indexes": indexes,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build observed day/night trend matrix")
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--best-effort", action="store_true")
    args = parser.parse_args()
    try:
        payload = build_payload(max(80, min(args.days, 520)))
        write_json(payload)
        print(f"Wrote {OUT}: indexes={len(payload['indexes'])} status={payload['status']}")
        return 0
    except Exception as exc:
        previous = read_json(OUT, {})
        if args.best_effort and previous.get("indexes"):
            previous["stale"] = True
            previous["refresh_attempted_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            previous["refresh_errors"] = [str(exc)]
            write_json(previous)
            print(f"WARN: trend sources unavailable; preserved prior snapshot: {exc}")
            return 0
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
