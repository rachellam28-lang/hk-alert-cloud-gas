"""
多巴胺系統 — 用恆指市場狀態自動調 CCASS alert 門檻。

Inputs (all from yfinance ^HSI):
  1. Realized volatility (20-day annualized) — 恐慌指標
  2. Trend strength (MA20 slope + distance) — 趨勢力
  3. Daily range ratio (avg last 5 vs last 20) — 日內波動
  4. Volume ratio (5-day MA vs 20-day MA) — 資金活躍度

Output: dopamine 0-100
  0-30  → 低多巴胺（悶市）：收緊門檻，少啲 noise
  30-60 → 正常
  60-100 → 高多巴胺（大波動市）：放鬆門檻，多啲 signal

Threshold mapping:
  spike_threshold_pct = 8.0 / 5.0 / 3.0  (低/正常/高)
  consecutive_days     = 5   / 3   / 2    (低/正常/高)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_hsi_history(lookback_days: int = 60) -> Optional[dict]:
    """Fetch ^HSI OHLCV for dopamine calculation."""
    try:
        ticker = yf.Ticker("^HSI")
        end = datetime.now()
        start = end - timedelta(days=lookback_days + 10)  # buffer for weekends
        df = ticker.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if df.empty or len(df) < 20:
            return None
        # Return as dict for JSON serialization
        closes = df["Close"].values.tolist()
        highs = df["High"].values.tolist()
        lows = df["Low"].values.tolist()
        volumes = df["Volume"].values.tolist()
        return {
            "dates": [str(d.date()) for d in df.index],
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes,
        }
    except Exception as e:
        print(f"[dopamine] yfinance ^HSI fetch failed: {e}", file=sys.stderr)
        return None


def realized_volatility(closes: list[float], window: int = 20) -> float:
    """Annualized realized volatility from daily log returns."""
    if len(closes) < window + 1:
        return 0.0
    recent = closes[-(window + 1):]
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
    daily_vol = np.std(log_returns) if log_returns else 0.0
    return daily_vol * math.sqrt(252) * 100  # annualized %, e.g. 15.3 = 15.3%


def trend_strength(closes: list[float], ma_window: int = 20) -> float:
    """Returns trend strength 0-100 based on slope + distance from MA20."""
    if len(closes) < ma_window + 5:
        return 50.0
    ma20 = np.mean(closes[-ma_window:])
    current = closes[-1]
    # Distance from MA in %
    distance_pct = abs(current - ma20) / ma20 * 100

    # Slope: compare 5-day sub-MA vs full MA
    ma5_recent = np.mean(closes[-5:])
    slope_pct = (ma5_recent - ma20) / ma20 * 100

    # Combine: distance gives magnitude, slope gives direction
    # Max distance ~10% → cap at 10
    capped_dist = min(distance_pct, 10.0)
    # Score: 0-100 where 50 is flat/neutral
    score = 50 + slope_pct * 5 + capped_dist * 2
    return max(0.0, min(100.0, score))


def daily_range_ratio(highs: list[float], lows: list[float], closes: list[float]) -> float:
    """Ratio of recent 5-day avg range vs 20-day avg range. >1 = expanding range."""
    if len(highs) < 20:
        return 1.0
    ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes)]
    recent_5 = np.mean(ranges[-5:]) if ranges[-5:] else 0
    full_20 = np.mean(ranges[-20:]) if ranges[-20:] else 0
    if full_20 == 0:
        return 1.0
    return recent_5 / full_20


def volume_ratio(volumes: list[float]) -> float:
    """5-day MA volume / 20-day MA volume. >1 = above-average activity."""
    if len(volumes) < 20:
        return 1.0
    vol5 = np.mean(volumes[-5:]) if volumes[-5:] else 0
    vol20 = np.mean(volumes[-20:]) if volumes[-20:] else 0
    if vol20 == 0:
        return 1.0
    return vol5 / vol20


def compute_dopamine() -> dict:
    """
    Compute dopamine score and threshold settings.
    Returns dict with score, level, and threshold multipliers.
    """
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dopamine": 50.0,
        "level": "normal",
        "spike_threshold_pct": 5.0,
        "consecutive_days": 3,
        "components": {},
        "error": None,
    }

    hsi = fetch_hsi_history()
    if hsi is None:
        result["error"] = "Failed to fetch ^HSI data"
        return result

    closes = hsi["close"]
    highs = hsi["high"]
    lows = hsi["low"]
    volumes = hsi["volume"]

    # 1. Realized volatility (weight: 35%)
    rv = realized_volatility(closes, window=20)
    # Normalize: 5-10% is normal HK, 15%+ is stressed, 25%+ is panic
    if rv <= 10:
        vol_score = rv / 10 * 40  # 0-40
    elif rv <= 20:
        vol_score = 40 + (rv - 10) / 10 * 30  # 40-70
    elif rv <= 35:
        vol_score = 70 + (rv - 20) / 15 * 20  # 70-90
    else:
        vol_score = 90 + min((rv - 35) / 15 * 10, 10)  # 90-100

    # 2. Trend strength (weight: 30%)
    trend = trend_strength(closes)

    # 3. Daily range ratio (weight: 20%)
    range_r = daily_range_ratio(highs, lows, closes)
    # Normalize: 0.5-1.5 range → 0-100 score
    range_score = max(0, min(100, (range_r - 0.5) * 100))

    # 4. Volume ratio (weight: 15%)
    vol_r = volume_ratio(volumes)
    vol_score = max(0, min(100, (vol_r - 0.5) * 100))

    # Weighted dopamine score
    dopamine = vol_score * 0.35 + trend * 0.30 + range_score * 0.20 + vol_score * 0.15

    # Determine level & thresholds
    if dopamine >= 60:
        level = "high"
        spike_threshold_pct = 3.0
        consecutive_days = 2
        level_emoji = "🔥"
        desc = "高波動市 — 門檻放鬆，捕捉更多 signal"
    elif dopamine >= 30:
        level = "normal"
        spike_threshold_pct = 5.0
        consecutive_days = 3
        level_emoji = "⚖️"
        desc = "正常市況 — 標準門檻"
    else:
        level = "low"
        spike_threshold_pct = 8.0
        consecutive_days = 5
        level_emoji = "😴"
        desc = "悶市 — 門檻收緊，減少 noise"

    result.update({
        "dopamine": round(dopamine, 1),
        "level": level,
        "level_emoji": level_emoji,
        "level_desc": desc,
        "spike_threshold_pct": spike_threshold_pct,
        "consecutive_days": consecutive_days,
        "components": {
            "realized_volatility_annualized_pct": round(rv, 2),
            "volatility_score": round(vol_score, 1),
            "trend_strength": round(trend, 1),
            "daily_range_ratio": round(range_r, 3),
            "range_score": round(range_score, 1),
            "volume_ratio": round(vol_r, 3),
            "volume_score": round(vol_score, 1),
            "hsi_last_close": round(closes[-1], 2) if closes else None,
            "hsi_data_days": len(closes),
        },
    })

    return result


def save_dopamine(result: dict) -> Path:
    """Save dopamine result to data/dopamine.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "dopamine.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return out


if __name__ == "__main__":
    result = compute_dopamine()
    path = save_dopamine(result)

    d = result["dopamine"]
    lvl = result["level"]
    emoji = result.get("level_emoji", "")
    desc = result.get("level_desc", "")
    spike = result["spike_threshold_pct"]
    cons = result["consecutive_days"]

    print(f"{emoji} 多巴胺: {d:.1f} ({lvl})")
    print(f"   {desc}")
    print(f"   spike_threshold: {spike:.1f}% | consecutive_days: {cons}")
    print(f"   → saved to {path}")

    for k, v in result["components"].items():
        if v is not None:
            print(f"   {k}: {v}")
