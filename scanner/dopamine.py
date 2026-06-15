"""
多巴胺系統 — 市場 regime 計分，自動調 signal 門檻

dopamine ∈ [0, 100]
- 高多巴胺（升市）：降低門檻，多出 signal
- 低多巴胺（跌市）：提高門檻，少出 signal

Formula: dopamine = 0.6 × regime + 0.3 × momentum + 0.1 × volatility
- regime: HSI vs MA20/MA50 (0-100)
- momentum: HSI 近5日回報率 mapped to 0-100
- volatility: HSI ATR% inverted (低波=高分)

Threshold effects:
- POC breakout: base 0% → dopamine高時 0%, 低時 +5%
- Gap/FVG min_pct: base 0.5% → dopamine高時 0.2%, 低時 2%
- Daily alert cap: base 50 → dopamine高時 100, 低時 20
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DOPAMINE_FILE = PROJECT / "data" / "dopamine.json"


def fetch_hsi_data(days: int = 120) -> pd.DataFrame | None:
    """Fetch HSI daily OHLCV from yfinance."""
    try:
        df = yf.download("^HSI", period=f"{days+10}d", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # lowercase columns
        df.columns = [c.lower() for c in df.columns]
        return df.tail(days)
    except Exception:
        return None


def compute_dopamine(df: pd.DataFrame | None = None) -> dict:
    """
    Compute dopamine score from HSI data.
    Returns dict with score and component breakdown.
    """
    if df is None:
        df = fetch_hsi_data()
    
    if df is None or len(df) < 60:
        return _default_result("no HSI data")

    try:
        close = df["close"]
        
        # ── 1. Regime (0-100): HSI vs MA20/MA50 ──
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        current = close.iloc[-1]
        
        # score: above both MAs = 100, between = 50, below both = 0
        upper = max(ma20, ma50)
        lower = min(ma20, ma50)
        if current > upper:
            regime = 100
        elif current > lower:
            regime = 50 + 50 * (current - lower) / (upper - lower) if upper > lower else 50
        else:
            regime = max(0, 50 * current / lower if lower > 0 else 0)
        regime = round(np.clip(regime, 0, 100), 1)
        
        # ── 2. Momentum (0-100): 5-day return ──
        ret5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
        # map -5% → 0, +5% → 100
        momentum = round(np.clip(50 + ret5 * 10, 0, 100), 1)
        
        # ── 3. Volatility (0-100): inverse ATR% ──
        high, low = df["high"], df["low"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().iloc[-1]
        atr_pct = (atr14 / current * 100) if current > 0 else 2
        # ATR% 1% → 80, 3% → 20
        volatility = round(np.clip(100 - atr_pct * 25, 0, 100), 1)
        
        # ── Composite ──
        dopamine = round(0.6 * regime + 0.3 * momentum + 0.1 * volatility, 1)
        
        return {
            "dopamine": dopamine,
            "regime": regime,
            "momentum": momentum,
            "volatility": volatility,
            "hsi": round(float(current), 2),
            "ma20": round(float(ma20), 2),
            "ma50": round(float(ma50), 2),
            "updated": datetime.now().isoformat(),
            "label": _dopamine_label(dopamine),
            "thresholds": _compute_thresholds(dopamine),
        }
    except Exception as e:
        return _default_result(f"error: {e}")


def _dopamine_label(score: float) -> str:
    if score >= 80:
        return "🔥🔥🔥 極度活躍"
    elif score >= 60:
        return "🔥🔥 活躍"
    elif score >= 40:
        return "🔥 正常"
    elif score >= 20:
        return "❄️ 謹慎"
    else:
        return "🧊 極度謹慎"


def _compute_thresholds(dopamine: float) -> dict:
    """
    Compute signal thresholds based on dopamine level.
    High dopamine = lower thresholds = more signals.
    """
    # POC breakout minimum %: 0% (high) → 5% (low)
    poc_min_pct = round(max(0, 5 - dopamine / 20), 1)
    
    # Gap minimum %: 0.2% (high) → 2% (low)
    gap_min_pct = round(max(0.1, 2 - dopamine / 55), 2)
    
    # FVG minimum %: 0.2% (high) → 2% (low)
    fvg_min_pct = round(max(0.1, 2 - dopamine / 55), 2)
    
    # Max alerts to export
    alert_cap = int(np.clip(20 + dopamine * 0.8, 20, 100))
    
    return {
        "poc_min_pct": poc_min_pct,
        "gap_min_pct": gap_min_pct,
        "fvg_min_pct": fvg_min_pct,
        "alert_cap": alert_cap,
    }


def _default_result(reason: str) -> dict:
    return {
        "dopamine": 50,
        "regime": 50,
        "momentum": 50,
        "volatility": 50,
        "hsi": 0,
        "ma20": 0,
        "ma50": 0,
        "updated": datetime.now().isoformat(),
        "label": "⚠️ 預設 (無數據)",
        "reason": reason,
        "thresholds": _compute_thresholds(50),
    }


def save_dopamine(result: dict):
    """Save dopamine result to JSON file."""
    DOPAMINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DOPAMINE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def load_dopamine() -> dict | None:
    """Load cached dopamine result."""
    if DOPAMINE_FILE.exists():
        with open(DOPAMINE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


if __name__ == "__main__":
    import json
    result = compute_dopamine()
    save_dopamine(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
