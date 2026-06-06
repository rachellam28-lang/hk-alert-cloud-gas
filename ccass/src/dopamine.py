"""
多巴胺系統 v2 — 市場數據 + 真實散戶關注度，自動調 CCASS alert 門檻。

兩大維度：
  A. 市場 regime（60%）— 恆指衍生指標（yfinance ^HSI）
     1. Realized volatility (20-day annualized) — 恐慌指標
     2. Trend strength (MA20 slope + distance) — 趨勢力
     3. Daily range ratio (5d vs 20d) — 日內波動
     4. Volume ratio (5d vs 20d MA) — 資金活躍度

  B. 散戶關注度（40%）— Google Trends 真實搜尋數據（pytrends）
     5. 「港股」Google 搜尋熱度（HK 地區）— 散戶 FOMO/關注度

Output: dopamine 0-100
  0-30  → 低多巴胺（悶市+散戶唔睇）：收緊門檻，少啲 noise
  30-60 → 正常
  60-100 → 高多巴胺（波動+散戶狂睇）：放鬆門檻，多啲 signal

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


# ═══════════════════════════════════════════════════════════════════
# A. HSI 市場 regime
# ═══════════════════════════════════════════════════════════════════

def fetch_hsi_history(lookback_days: int = 60) -> Optional[dict]:
    """Fetch ^HSI OHLCV."""
    try:
        ticker = yf.Ticker("^HSI")
        end = datetime.now()
        start = end - timedelta(days=lookback_days + 10)
        df = ticker.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if df.empty or len(df) < 20:
            return None
        return {
            "dates": [str(d.date()) for d in df.index],
            "close": df["Close"].values.tolist(),
            "high": df["High"].values.tolist(),
            "low": df["Low"].values.tolist(),
            "volume": df["Volume"].values.tolist(),
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
    return daily_vol * math.sqrt(252) * 100


def trend_strength(closes: list[float], ma_window: int = 20) -> float:
    """Trend strength 0-100 (50 = flat)."""
    if len(closes) < ma_window + 5:
        return 50.0
    ma20 = np.mean(closes[-ma_window:])
    current = closes[-1]
    distance_pct = abs(current - ma20) / ma20 * 100
    ma5_recent = np.mean(closes[-5:])
    slope_pct = (ma5_recent - ma20) / ma20 * 100
    capped_dist = min(distance_pct, 10.0)
    score = 50 + slope_pct * 5 + capped_dist * 2
    return max(0.0, min(100.0, score))


def daily_range_ratio(highs: list[float], lows: list[float], closes: list[float]) -> float:
    """5d avg range / 20d avg range."""
    if len(highs) < 20:
        return 1.0
    ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes)]
    recent_5 = np.mean(ranges[-5:]) if ranges[-5:] else 0
    full_20 = np.mean(ranges[-20:]) if ranges[-20:] else 0
    if full_20 == 0:
        return 1.0
    return recent_5 / full_20


def volume_ratio(volumes: list[float]) -> float:
    """5d MA / 20d MA volume."""
    if len(volumes) < 20:
        return 1.0
    vol5 = np.mean(volumes[-5:]) if volumes[-5:] else 0
    vol20 = np.mean(volumes[-20:]) if volumes[-20:] else 0
    if vol20 == 0:
        return 1.0
    return vol5 / vol20


# ═══════════════════════════════════════════════════════════════════
# B. 散戶關注度 — Google Trends（真實搜尋數據）
# ═══════════════════════════════════════════════════════════════════

_GT_KEYWORDS = ["港股", "股票", "牛熊證"]  # 3 keywords covering different retail intents
_GT_GEO = "HK"
_GT_LOOKBACK = "today 3-m"  # pytrends timeframe


def fetch_google_trends_score() -> float:
    """
    Returns retail attention score 0-100 based on Google Trends HK search interest.

    Uses 3 keywords weighted equally:
      - 「港股」→ general market interest
      - 「股票」→ broad stock interest
      - 「牛熊證」→ leveraged product interest (high FOMO indicator)

    Method: recent 7d avg / 30d avg ratio, normalized to 0-100.
    >1.0 = rising interest (FOMO building), <1.0 = fading interest.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("[dopamine] pytrends not installed, skip retail attention", file=sys.stderr)
        return 50.0

    try:
        pytrends = TrendReq(hl="zh-HK", tz=360, timeout=10)
        scores = []
        for kw in _GT_KEYWORDS:
            try:
                pytrends.build_payload([kw], timeframe=_GT_LOOKBACK, geo=_GT_GEO)
                df = pytrends.interest_over_time()
                if df is None or df.empty or kw not in df.columns:
                    continue
                series = df[kw].values
                if len(series) < 14:
                    continue
                recent_7d = np.mean(series[-7:])
                baseline_30d = np.mean(series[-30:]) if len(series) >= 30 else np.mean(series)
                if baseline_30d > 0:
                    ratio = recent_7d / baseline_30d
                else:
                    ratio = 1.0
                # Normalize: ratio 0.5-2.0 → 0-100
                normalized = max(0, min(100, (ratio - 0.5) / 1.5 * 100))
                scores.append(normalized)
            except Exception:
                continue

        if not scores:
            print("[dopamine] No Google Trends data available", file=sys.stderr)
            return 50.0

        return float(np.mean(scores))

    except Exception as e:
        print(f"[dopamine] Google Trends fetch failed: {e}", file=sys.stderr)
        return 50.0  # neutral fallback


# ═══════════════════════════════════════════════════════════════════
# 主計算
# ═══════════════════════════════════════════════════════════════════

def compute_dopamine() -> dict:
    """
    Compute dopamine score = 60% market regime + 40% retail attention.
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

    # ── A. Market regime (60%) ──
    hsi = fetch_hsi_history()
    if hsi is None:
        result["error"] = "Failed to fetch ^HSI data"
        return result

    closes = hsi["close"]
    highs = hsi["high"]
    lows = hsi["low"]
    volumes = hsi["volume"]

    rv = realized_volatility(closes, window=20)
    if rv <= 10:
        vol_score = rv / 10 * 40
    elif rv <= 20:
        vol_score = 40 + (rv - 10) / 10 * 30
    elif rv <= 35:
        vol_score = 70 + (rv - 20) / 15 * 20
    else:
        vol_score = 90 + min((rv - 35) / 15 * 10, 10)

    trend = trend_strength(closes)
    range_r = daily_range_ratio(highs, lows, closes)
    range_score = max(0, min(100, (range_r - 0.5) * 100))
    vol_r = volume_ratio(volumes)
    hsi_vol_score = max(0, min(100, (vol_r - 0.5) * 100))

    # Market regime sub-score (0-100)
    market_regime = (
        vol_score * 0.20 / 0.60 +
        trend * 0.15 / 0.60 +
        range_score * 0.15 / 0.60 +
        hsi_vol_score * 0.10 / 0.60
    )

    # ── B. Retail attention (40%) — Google Trends ──
    retail_attention = fetch_google_trends_score()

    # ── Combined dopamine ──
    dopamine = market_regime * 0.60 + retail_attention * 0.40

    # Determine level & thresholds
    if dopamine >= 60:
        level = "high"
        spike_threshold_pct = 3.0
        consecutive_days = 2
        level_emoji = "🔥"
        desc = "高波動+散戶關注 — 門檻放鬆，捕捉更多 signal"
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
        desc = "悶市+散戶離場 — 門檻收緊，減少 noise"

    result.update({
        "dopamine": round(dopamine, 1),
        "level": level,
        "level_emoji": level_emoji,
        "level_desc": desc,
        "spike_threshold_pct": spike_threshold_pct,
        "consecutive_days": consecutive_days,
        "version": 2,
        "components": {
            # Market regime (HSI-derived)
            "market_regime_score": round(market_regime, 1),
            "realized_volatility_annualized_pct": round(rv, 2),
            "volatility_score": round(vol_score, 1),
            "trend_strength": round(trend, 1),
            "daily_range_ratio": round(range_r, 3),
            "range_score": round(range_score, 1),
            "hsi_volume_ratio": round(vol_r, 3),
            "hsi_volume_score": round(hsi_vol_score, 1),
            "hsi_last_close": round(closes[-1], 2) if closes else None,
            "hsi_data_days": len(closes),
            # Retail attention (Google Trends — real data)
            "retail_attention_score": round(retail_attention, 1),
            "retail_source": "Google Trends HK (港股+股票+牛熊證)",
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

    print(f"\n{emoji} 多巴胺 v2: {d:.1f} ({lvl})")
    print(f"   {desc}")
    print(f"   spike_threshold: {spike:.1f}% | consecutive_days: {cons}")
    print(f"   → saved to {path}\n")

    # Split display
    print("── 市場 regime (60%) ──")
    for k, v in result["components"].items():
        if k.startswith("retail"):
            break
        if v is not None:
            print(f"   {k}: {v}")

    print("── 散戶關注度 (40%) — 真實數據 ──")
    for k in ["retail_attention_score", "retail_source"]:
        v = result["components"].get(k)
        if v is not None:
            print(f"   {k}: {v}")
