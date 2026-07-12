#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
KBAR_PATH = DATA / "kbar_cache.json"
OUT_PATH = DATA / "trade_engine.json"

SETUP_META = {
    "breakout": {
        "label": "Breakout",
        "sub": "near prior high",
        "note": "Hold near highs before treating it as a valid breakout.",
        "tone": "breakout",
    },
    "base": {
        "label": "Base",
        "sub": "compression / absorption",
        "note": "Stay patient until volume expansion confirms the move.",
        "tone": "base",
    },
    "breaklow": {
        "label": "Breaklow Reclaim",
        "sub": "flush then reclaim",
        "note": "Only counts after price closes back above the prior low.",
        "tone": "breaklow",
    },
    "rebound": {
        "label": "Weak Rebound",
        "sub": "counter-trend bounce",
        "note": "Treat as a bounce until key levels are recovered.",
        "tone": "rebound",
    },
}


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def num(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def aggregate_bars(bars: list[dict], group: int) -> list[dict]:
    if not isinstance(bars, list) or group <= 1:
        return bars or []
    aligned = list(bars)
    remainder = len(aligned) % group
    if remainder:
        aligned = aligned[remainder:]
    out: list[dict] = []
    for idx in range(0, len(aligned), group):
        chunk = aligned[idx : idx + group]
        if len(chunk) < group:
            continue
        out.append(
            {
                "time": chunk[-1].get("time"),
                "open": chunk[0].get("open"),
                "high": max(num(item.get("high")) or num(item.get("open")) or 0 for item in chunk),
                "low": min(num(item.get("low")) or num(item.get("open")) or 0 for item in chunk),
                "close": chunk[-1].get("close"),
                "volume": sum(num(item.get("volume")) or 0 for item in chunk),
                "turnover": sum(num(item.get("turnover")) or 0 for item in chunk),
            }
        )
    return out


def series_for_interval(entry: dict, interval: str) -> list[dict]:
    series = entry.get("series") or {}
    direct = series.get(interval)
    if isinstance(direct, list) and direct:
        return direct
    base5 = series.get("5m") if isinstance(series.get("5m"), list) else []
    base1 = series.get("1h") if isinstance(series.get("1h"), list) else []
    if base5:
        if interval == "15m":
            return aggregate_bars(base5, 3)
        if interval == "30m":
            return aggregate_bars(base5, 6)
    if not base1:
        return []
    if interval == "2h":
        return aggregate_bars(base1, 2)
    if interval == "4h":
        return aggregate_bars(base1, 4)
    return []


def ema(bars: list[dict], period: int) -> float | None:
    closes = [num(item.get("close")) for item in bars if num(item.get("close")) is not None]
    if len(closes) < period:
        return None
    current = sum(closes[:period]) / period
    alpha = 2 / (period + 1)
    for close in closes[period:]:
        current = close * alpha + current * (1 - alpha)
    return current


def signed(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}{suffix}"


def trend_guard(metrics: dict | None) -> dict:
    if not metrics:
        return {"key": "neutral", "label": "Trend Pending", "note": "Not enough Kbar depth yet."}
    trend1 = metrics.get("trend1")
    trend4 = metrics.get("trend4")
    close1 = num(metrics.get("close1"))
    ema21 = num(metrics.get("ema21_1"))
    above_guard = close1 is not None and ema21 is not None and close1 >= ema21
    below_guard = close1 is not None and ema21 is not None and close1 < ema21
    if trend1 == "up" and trend4 == "up" and above_guard:
        return {"key": "bull", "label": "Bull Guard", "note": "1H / 4H aligned up; hold 1H EMA21."}
    if trend1 == "down" and trend4 == "down" and below_guard:
        return {"key": "bear", "label": "Bear Guard", "note": "1H / 4H aligned down; recover 1H EMA21 first."}
    if trend4 == "up" and above_guard:
        return {"key": "watch", "label": "Bull Watch", "note": "4H still up, 1H not fully synced."}
    if trend4 == "down" and below_guard:
        return {"key": "watch", "label": "Bear Watch", "note": "4H still down, 1H not fully synced."}
    return {"key": "neutral", "label": "Trend Pending", "note": "No aligned rhythm yet."}


def analyze_setups(entry: dict) -> dict | None:
    bars5 = series_for_interval(entry, "5m")
    bars1 = series_for_interval(entry, "1h")
    bars4 = series_for_interval(entry, "4h")
    if len(bars1) < 30 or len(bars4) < 24:
        return None

    last1 = bars1[-1]
    close1 = num(last1.get("close"))
    ema8_1 = ema(bars1, 8)
    ema21_1 = ema(bars1, 21)
    ema8_4 = ema(bars4, 8)
    ema21_4 = ema(bars4, 21)
    if not all(value is not None for value in (close1, ema8_1, ema21_1, ema8_4, ema21_4)):
        return None

    window1 = bars1[-20:]
    highs20 = [num(bar.get("high")) for bar in window1 if num(bar.get("high")) is not None]
    lows20 = [num(bar.get("low")) for bar in window1 if num(bar.get("low")) is not None]
    if not highs20 or not lows20:
        return None
    high20 = max(highs20)
    low20 = min(lows20)
    prior20 = window1[:-1]
    prior_high20 = max([num(bar.get("high")) for bar in prior20 if num(bar.get("high")) is not None], default=None)
    prior_low20 = min([num(bar.get("low")) for bar in prior20 if num(bar.get("low")) is not None], default=None)
    last_high = num(last1.get("high"))
    last_low = num(last1.get("low"))
    new_high = prior_high20 is not None and last_high is not None and last_high > prior_high20
    new_low = prior_low20 is not None and last_low is not None and last_low < prior_low20
    range_pct = ((high20 - low20) / close1) * 100 if high20 > low20 else 0
    gap_high20 = ((close1 - high20) / high20) * 100 if high20 else None
    bounce_low20 = ((close1 - low20) / low20) * 100 if low20 else None
    pos_in_range = (close1 - low20) / (high20 - low20) if high20 > low20 else 0.5
    prior_low = min([num(bar.get("low")) for bar in window1[:-5] if num(bar.get("low")) is not None], default=low20)
    recent_low = min([num(bar.get("low")) for bar in window1[-5:] if num(bar.get("low")) is not None], default=low20)
    reclaim_prev_low = ((close1 - prior_low) / prior_low) * 100 if prior_low else None
    broke_prior_low = bool(prior_low and recent_low and recent_low < prior_low * 0.9975)
    thrust5 = 0.0
    if len(bars5) >= 12:
        last5 = num(bars5[-1].get("close"))
        base5 = num(bars5[-12].get("close"))
        if last5 is not None and base5 and base5 > 0:
            thrust5 = ((last5 - base5) / base5) * 100
    ema_spread1 = ((ema8_1 - ema21_1) / ema21_1) * 100 if ema21_1 else 0
    ema_spread4 = ((ema8_4 - ema21_4) / ema21_4) * 100 if ema21_4 else 0
    trend1 = "up" if ema8_1 > ema21_1 else ("down" if ema8_1 < ema21_1 else "flat")
    trend4 = "up" if ema8_4 > ema21_4 else ("down" if ema8_4 < ema21_4 else "flat")

    breakout_score = 0
    if trend1 == "up":
        breakout_score += 3
    if trend4 == "up":
        breakout_score += 2
    elif trend4 == "flat":
        breakout_score += 1
    if close1 > ema8_1:
        breakout_score += 2
    elif close1 > ema21_1:
        breakout_score += 1
    if gap_high20 is not None and gap_high20 >= -2.5:
        breakout_score += 3
    elif gap_high20 is not None and gap_high20 >= -5:
        breakout_score += 1
    if thrust5 > 1:
        breakout_score += 1
    if pos_in_range > 0.75:
        breakout_score += 1

    base_score = 0
    if range_pct <= 12:
        base_score += 3
    elif range_pct <= 16:
        base_score += 1
    if abs(ema_spread1) <= 1.5:
        base_score += 2
    if abs(ema_spread4) <= 1.5:
        base_score += 2
    if 0.25 <= pos_in_range <= 0.75:
        base_score += 2
    if abs(thrust5) <= 1.5:
        base_score += 1
    if gap_high20 is not None and -8 <= gap_high20 <= -2:
        base_score += 1

    rebound_score = 0
    if trend1 == "down":
        rebound_score += 2
    if trend4 == "down":
        rebound_score += 2
    if close1 > ema8_1:
        rebound_score += 2
    if close1 < ema21_1:
        rebound_score += 2
    if bounce_low20 is not None and bounce_low20 >= 3:
        rebound_score += 2
    elif bounce_low20 is not None and bounce_low20 >= 1:
        rebound_score += 1
    if gap_high20 is not None and gap_high20 <= -5:
        rebound_score += 1
    if thrust5 > 1:
        rebound_score += 1

    breaklow_score = 0
    if trend1 == "down":
        breaklow_score += 1
    if trend4 == "down":
        breaklow_score += 2
    elif trend4 == "flat":
        breaklow_score += 1
    if broke_prior_low:
        breaklow_score += 3
    if reclaim_prev_low is not None and reclaim_prev_low >= 0.5:
        breaklow_score += 2
    elif reclaim_prev_low is not None and reclaim_prev_low >= 0:
        breaklow_score += 1
    if close1 > ema8_1:
        breaklow_score += 1
    if close1 < ema21_1:
        breaklow_score += 1
    if bounce_low20 is not None and bounce_low20 >= 3:
        breaklow_score += 1
    if thrust5 > 0.8:
        breaklow_score += 1
    if 0.3 <= pos_in_range <= 0.65:
        breaklow_score += 1
    if not broke_prior_low:
        breaklow_score = min(breaklow_score, 4)
    if reclaim_prev_low is None or reclaim_prev_low < 0:
        breaklow_score = min(breaklow_score, 5)

    scores = {
        "breakout": int(clamp(breakout_score, 0, 10)),
        "base": int(clamp(base_score, 0, 10)),
        "breaklow": int(clamp(breaklow_score, 0, 10)),
        "rebound": int(clamp(rebound_score, 0, 10)),
    }

    active_key = "base"
    if scores["breakout"] >= scores["base"] and scores["breakout"] >= scores["breaklow"] and scores["breakout"] >= scores["rebound"]:
        active_key = "breakout"
    elif scores["breaklow"] >= scores["base"] and scores["breaklow"] >= scores["breakout"] and scores["breaklow"] >= scores["rebound"]:
        active_key = "breaklow"
    elif scores["rebound"] >= scores["base"] and scores["rebound"] >= scores["breakout"] and scores["rebound"] >= scores["breaklow"]:
        active_key = "rebound"

    metrics = {
        "close1": close1,
        "trend1": trend1,
        "trend4": trend4,
        "gapHigh20": gap_high20,
        "bounceLow20": bounce_low20,
        "rangePct": range_pct,
        "thrust5": thrust5,
        "emaSpread1": ema_spread1,
        "emaSpread4": ema_spread4,
        "posInRange": pos_in_range,
        "priorLow": prior_low,
        "recentLow": recent_low,
        "reclaimPrevLow": reclaim_prev_low,
        "brokePriorLow": broke_prior_low,
        "high20": high20,
        "low20": low20,
        "priorHigh20": prior_high20,
        "priorLow20": prior_low20,
        "newHigh": new_high,
        "newLow": new_low,
        "ema8_1": ema8_1,
        "ema21_1": ema21_1,
    }
    meta = SETUP_META[active_key]
    return {
        "symbol": entry.get("symbol"),
        "label": entry.get("label") or entry.get("symbol"),
        "market": entry.get("market"),
        "activeKey": active_key,
        "scores": scores,
        "metrics": metrics,
        "cards": [
            {
                "key": key,
                "tone": item["tone"],
                "name": item["label"],
                "kicker": item["sub"],
                "tag": "active" if active_key == key else "watch",
                "score": scores[key],
                "active": active_key == key,
                "stats": (
                    [
                        {"label": "1H / 4H", "value": f"{trend1} / {trend4}"},
                        {"label": "Gap to high20", "value": signed(gap_high20, "%")},
                        {"label": "5m thrust", "value": signed(thrust5, "%")},
                        {"label": "Range pos", "value": f"{round(pos_in_range * 100)}%"},
                    ]
                    if key == "breakout"
                    else [
                        {"label": "Range size", "value": signed(range_pct, "%")},
                        {"label": "EMA spread 1H", "value": signed(ema_spread1, "%")},
                        {"label": "EMA spread 4H", "value": signed(ema_spread4, "%")},
                        {"label": "Range pos", "value": f"{round(pos_in_range * 100)}%"},
                    ]
                    if key == "base"
                    else [
                        {"label": "Prior low", "value": signed(prior_low)},
                        {"label": "Recent low", "value": signed(recent_low)},
                        {"label": "Reclaim", "value": signed(reclaim_prev_low, "%")},
                        {"label": "5m thrust", "value": signed(thrust5, "%")},
                    ]
                    if key == "breaklow"
                    else [
                        {"label": "1H / 4H", "value": f"{trend1} / {trend4}"},
                        {"label": "Off low20", "value": signed(bounce_low20, "%")},
                        {"label": "Gap to high20", "value": signed(gap_high20, "%")},
                        {"label": "5m thrust", "value": signed(thrust5, "%")},
                    ]
                ),
                "note": item["note"],
            }
            for key, item in SETUP_META.items()
        ],
        "trendGuard": trend_guard(metrics),
    }


def momentum_return(bars: list[dict], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    now = num(bars[-1].get("close"))
    old = num(bars[-1 - lookback].get("close"))
    if now is None or old is None or old <= 0:
        return None
    return (now / old - 1) * 100


def momentum_trend_label(setup: dict | None) -> str:
    if not setup:
        return "neutral"
    trend1 = setup.get("metrics", {}).get("trend1")
    trend4 = setup.get("metrics", {}).get("trend4")
    if trend1 == "up" and trend4 == "up":
        return "bull"
    if trend1 == "down" and trend4 == "down":
        return "bear"
    if trend4 == "up":
        return "bullish"
    if trend4 == "down":
        return "bearish"
    return "neutral"


def build_momentum_row(entry: dict, setup: dict | None) -> dict | None:
    bars = series_for_interval(entry, "1d")
    if len(bars) < 21:
        return None
    close = num(bars[-1].get("close"))
    if close is None or close <= 0:
        return None
    r5 = momentum_return(bars, 5)
    r20 = momentum_return(bars, 20)
    r60 = momentum_return(bars, 60)
    ema20 = ema(bars, 20)
    ema50 = ema(bars, 50)
    trend_up = ema20 is not None and ema50 is not None and close > ema20 and ema20 > ema50
    trend_down = ema20 is not None and ema50 is not None and close < ema20 and ema20 < ema50
    high20 = max([num(item.get("high")) for item in bars[-21:-1] if num(item.get("high")) is not None], default=None)
    breakout = bool(high20 is not None and close >= high20)
    volumes = [num(item.get("volume")) for item in bars[-21:-1] if num(item.get("volume")) is not None]
    avg_vol = (sum(volumes) / len(volumes)) if volumes else None
    latest_vol = num(bars[-1].get("volume"))
    vr = (latest_vol / avg_vol) if avg_vol and latest_vol is not None else None

    score = 0.0
    if r5 is not None:
        score += r5 * 1.5
    if r20 is not None:
        score += r20 * 0.8
    if r60 is not None:
        score += r60 * 0.35
    if vr is not None:
        score += clamp((vr - 1) * 5, -2, 10)
    if trend_up:
        score += 12
    if trend_down:
        score -= 10
    if breakout:
        score += 10

    active_key = "base"
    if setup:
        active_key = setup.get("activeKey") or "base"
        score += (setup.get("scores", {}) or {}).get(active_key, 0) * 2
        if active_key == "breakout":
            score += 6
        elif active_key == "base":
            score += 2
        elif active_key == "breaklow":
            score += 3

    meta = SETUP_META.get(active_key, SETUP_META["base"])
    return {
        "symbol": entry.get("symbol"),
        "label": entry.get("label") or entry.get("symbol"),
        "market": entry.get("market"),
        "price": close,
        "r5": r5,
        "r20": r20,
        "r60": r60,
        "vr": vr,
        "trend": momentum_trend_label(setup),
        "setupKey": active_key,
        "setupLabel": meta["label"],
        "setupClass": meta["tone"],
        "score": round(score, 2),
    }


def build_engine() -> dict:
    cache = load_json(KBAR_PATH, {})
    symbols = (cache or {}).get("symbols") or {}
    built_at = datetime.now().isoformat(timespec="seconds")
    source_updated_at = cache.get("updated_at")
    by_symbol: dict[str, dict] = {}
    groups = {key: [] for key in SETUP_META}
    momentum_rows: list[dict] = []

    for symbol, entry in symbols.items():
        if not isinstance(entry, dict):
            continue
        setup = analyze_setups(entry)
        if setup:
            by_symbol[symbol] = setup
            active_key = setup["activeKey"]
            groups[active_key].append(
                {
                    "symbol": symbol,
                    "label": setup["label"],
                    "market": setup["market"],
                    "score": setup["scores"][active_key],
                    "setupKey": active_key,
                }
            )
        row = build_momentum_row(entry, setup)
        if row:
            momentum_rows.append(row)

    for rows in groups.values():
        rows.sort(key=lambda item: (-item.get("score", 0), str(item.get("symbol", ""))))
    momentum_rows.sort(key=lambda item: (-item.get("score", 0), str(item.get("symbol", ""))))

    return {
        "updated_at": built_at,
        "built_at": built_at,
        "source_updated_at": source_updated_at,
        "source": "kbar_cache derived trading engine",
        "scope_count": len(by_symbol),
        "momentum_count": len(momentum_rows),
        "summary": {
            "setup_counts": {key: len(value) for key, value in groups.items()},
            "top_momentum_symbol": momentum_rows[0]["symbol"] if momentum_rows else None,
        },
        "by_symbol": by_symbol,
        "groups": groups,
        "momentum_rank": momentum_rows[:200],
    }


def main() -> int:
    engine = build_engine()
    OUT_PATH.write_text(json.dumps(engine, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH} with {engine['scope_count']} setups and {engine['momentum_count']} momentum rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
