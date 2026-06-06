"""
多巴胺系統 v4 — 三層真實數據，自動調 CCASS alert 門檻。

  A. 長橋人氣榜（40%）— Longbridge MCP API — 逐隻股票散戶關注
     1. market_temperature — 市場溫度 (0-100)
     2. 關注度排名 (watchlist_heat-hk) — TOP 30
     3. 總熱度排名 (hot_all-hk) — TOP 50

  B. 恆指市場 regime（30%）— yfinance ^HSI — 技術面波動
     4. Realized volatility (20-day annualized)
     5. Trend strength + range + volume

  C. Google Trends 大市熱度（30%）— 宏觀零售搜尋情緒
     6. 「港股」「股票」「牛熊證」HK 搜尋熱度

Output: dopamine 0-100
  0-30  → 低多巴胺（凍市+散戶離場）：收緊門檻
  30-60 → 正常
  60-100 → 高多巴胺（熱市+散戶湧入）：放鬆門檻

Threshold mapping:
  spike_threshold_pct = 8.0 / 5.0 / 3.0  (低/正常/高)
  consecutive_days     = 5   / 3   / 2    (低/正常/高)
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ═══════════════════════════════════════════════════════════════════
# Token loading
# ═══════════════════════════════════════════════════════════════════

def _load_longbridge_token() -> str:
    """Read LONGBRIDGE_ACCESS_TOKEN from .env."""
    env_paths = [
        DATA_DIR.parent / ".env",
        Path.home() / "Desktop" / "automatic" / "ccass-debug" / ".env",
    ]
    for p in env_paths:
        if p.exists():
            with open(p) as f:
                for line in f:
                    if "LONGBRIDGE_ACCESS_TOKEN" in line:
                        return line.strip().split("=", 1)[1]
    return ""


# ═══════════════════════════════════════════════════════════════════
# A. 長橋人氣榜 (50%) — 真實散戶關注數據
# ═══════════════════════════════════════════════════════════════════

_LB_TOKEN = None


def _lb_token():
    global _LB_TOKEN
    if _LB_TOKEN is None:
        _LB_TOKEN = _load_longbridge_token()
    return _LB_TOKEN


def _lb_mcp(method: str, args: dict | None = None) -> dict:
    """Call Longbridge MCP tool."""
    token = _lb_token()
    if not token:
        return {}
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": method, "arguments": args or {}},
    }
    try:
        auth = "Authorization: Bearer " + token
        r = subprocess.run([
            "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
            "-H", "Content-Type: application/json",
            "-H", "Accept: application/json, text/event-stream",
            "-H", auth,
            "-d", json.dumps(body),
        ], capture_output=True, text=True, timeout=30)
        raw = r.stdout.strip()
        if raw.startswith("data: "):
            raw = raw[6:]
        res = json.loads(raw)
        if "error" in res:
            return {}
        content = res.get("result", {}).get("content", [])
        return json.loads(content[0]["text"]) if content else {}
    except Exception as e:
        print(f"[dopamine] Longbridge MCP error ({method}): {e}", file=sys.stderr)
        return {}


def fetch_longbridge_sentiment() -> dict:
    """
    Fetch Longbridge market temperature + popularity leaderboards.
    Returns dict with temperature_score and popularity stats.
    """
    result = {"temperature": 50, "hot_stocks_count": 0, "watched_stocks_count": 0,
              "discussed_stocks_count": 0, "top_watched": [], "error": None}

    try:
        # 1. Market temperature
        temp = _lb_mcp("market_temperature", {"market": "HK"})
        if temp:
            result["temperature"] = temp.get("temperature", 50)
            result["temperature_desc"] = temp.get("description", "")
            result["sentiment"] = temp.get("sentiment", 50)
            result["valuation"] = temp.get("valuation", 50)

        # 2. Watchlist heat (關注度) — most important for retail attention
        watchlist = _lb_mcp("rank_list", {"key": "ib_watchlist_heat-hk", "market": "HK", "size": 30})
        items = watchlist.get("lists", watchlist.get("items", []))
        result["watched_stocks_count"] = len(items)
        result["top_watched"] = [
            {"code": i.get("code", ""), "name": i.get("name", ""),
             "last_done": i.get("last_done", ""), "chg": i.get("chg", "")}
            for i in items[:10]
        ]

        # 3. Hot all (總熱度)
        hot = _lb_mcp("rank_list", {"key": "ib_hot_all-hk", "market": "HK", "size": 50})
        hot_items = hot.get("lists", hot.get("items", []))
        result["hot_stocks_count"] = len(hot_items)

        # 4. Discuss heat (熱議)
        discuss = _lb_mcp("rank_list", {"key": "ib_discuss_heat-hk", "market": "HK", "size": 30})
        disc_items = discuss.get("lists", discuss.get("items", []))
        result["discussed_stocks_count"] = len(disc_items)

    except Exception as e:
        result["error"] = str(e)
        print(f"[dopamine] Longbridge fetch failed: {e}", file=sys.stderr)

    return result


def compute_longbridge_score(lb: dict) -> float:
    """
    Convert Longbridge sentiment data to 0-100 attention score.

    Components:
      - market_temperature: directly 0-100, weight 50%
      - watchlist heat density: more watched stocks = higher attention, weight 30%
      - discuss heat density: more discussion = higher FOMO, weight 20%
    """
    temp = lb.get("temperature", 50)

    # Watchlist: 30 max, normalize to 0-100
    watched = lb.get("watched_stocks_count", 0)
    watch_score = min(100, watched / 30 * 100)

    # Discussion: 30 max, normalize
    discussed = lb.get("discussed_stocks_count", 0)
    discuss_score = min(100, discussed / 30 * 100)

    return temp * 0.50 + watch_score * 0.30 + discuss_score * 0.20


# ═══════════════════════════════════════════════════════════════════
# B. Google Trends 大市熱度（30%）— 宏觀零售搜尋情緒
# ═══════════════════════════════════════════════════════════════════

_GT_KEYWORDS = ["港股", "股票", "牛熊證"]
_GT_GEO = "HK"
_GT_LOOKBACK = "today 3-m"


def fetch_google_trends_score() -> float:
    """Returns retail attention score 0-100 from Google Trends HK."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
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
                normalized = max(0, min(100, (ratio - 0.5) / 1.5 * 100))
                scores.append(normalized)
            except Exception:
                continue
        if not scores:
            return 50.0
        return float(np.mean(scores))
    except Exception as e:
        print(f"[dopamine] Google Trends failed: {e}", file=sys.stderr)
        return 50.0


# ═══════════════════════════════════════════════════════════════════
# C. 恆指市場 regime（30%）— yfinance ^HSI
# ═══════════════════════════════════════════════════════════════════

def fetch_hsi_history(lookback_days: int = 60) -> Optional[dict]:
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
        print(f"[dopamine] yfinance ^HSI failed: {e}", file=sys.stderr)
        return None


def realized_volatility(closes: list[float], window: int = 20) -> float:
    if len(closes) < window + 1:
        return 0.0
    recent = closes[-(window + 1):]
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
    daily_vol = np.std(log_returns) if log_returns else 0.0
    return daily_vol * math.sqrt(252) * 100


def trend_strength(closes: list[float], ma_window: int = 20) -> float:
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
    if len(highs) < 20:
        return 1.0
    ranges = [(h - l) / c * 100 for h, l, c in zip(highs, lows, closes)]
    recent_5 = np.mean(ranges[-5:]) if ranges[-5:] else 0
    full_20 = np.mean(ranges[-20:]) if ranges[-20:] else 0
    if full_20 == 0:
        return 1.0
    return recent_5 / full_20


def volume_ratio(volumes: list[float]) -> float:
    if len(volumes) < 20:
        return 1.0
    vol5 = np.mean(volumes[-5:]) if volumes[-5:] else 0
    vol20 = np.mean(volumes[-20:]) if volumes[-20:] else 0
    if vol20 == 0:
        return 1.0
    return vol5 / vol20


def compute_hsi_regime(closes, highs, lows, volumes) -> tuple[float, dict]:
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

    regime = (vol_score * 0.35 + trend * 0.30 + range_score * 0.20 + hsi_vol_score * 0.15)

    details = {
        "realized_volatility_annualized_pct": round(rv, 2),
        "volatility_score": round(vol_score, 1),
        "trend_strength": round(trend, 1),
        "daily_range_ratio": round(range_r, 3),
        "range_score": round(range_score, 1),
        "hsi_volume_ratio": round(vol_r, 3),
        "hsi_volume_score": round(hsi_vol_score, 1),
    }
    return regime, details


# ═══════════════════════════════════════════════════════════════════
# 主計算
# ═══════════════════════════════════════════════════════════════════

def compute_dopamine() -> dict:
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": 4,
        "dopamine": 50.0,
        "level": "normal",
        "spike_threshold_pct": 5.0,
        "consecutive_days": 3,
        "components": {},
        "error": None,
    }

    # ── A. Longbridge sentiment (40%) ──
    lb = fetch_longbridge_sentiment()
    lb_score = compute_longbridge_score(lb)

    # ── B. Google Trends 大市熱度 (30%) ──
    gt_score = fetch_google_trends_score()

    # ── C. HSI regime (30%) ──
    hsi = fetch_hsi_history()
    if hsi is None:
        result["error"] = "Failed to fetch ^HSI"
        return result

    hsi_score, hsi_details = compute_hsi_regime(
        hsi["close"], hsi["high"], hsi["low"], hsi["volume"]
    )

    # ── Combined 40/30/30 ──
    dopamine = lb_score * 0.40 + gt_score * 0.30 + hsi_score * 0.30

    # Level & thresholds
    if dopamine >= 60:
        level = "high"
        spike_threshold_pct = 3.0
        consecutive_days = 2
        level_emoji = "🔥"
        desc = "熱市+散戶關注 — 門檻放鬆"
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
        desc = "凍市+散戶離場 — 門檻收緊"

    result.update({
        "dopamine": round(dopamine, 1),
        "level": level,
        "level_emoji": level_emoji,
        "level_desc": desc,
        "spike_threshold_pct": spike_threshold_pct,
        "consecutive_days": consecutive_days,
        "components": {
            # Longbridge (real per-stock attention)
            "longbridge_score": round(lb_score, 1),
            "market_temperature": lb.get("temperature", 50),
            "market_temperature_desc": lb.get("temperature_desc", ""),
            "market_sentiment": lb.get("sentiment", 50),
            "market_valuation": lb.get("valuation", 50),
            "watched_stocks_count": lb.get("watched_stocks_count", 0),
            "hot_stocks_count": lb.get("hot_stocks_count", 0),
            "discussed_stocks_count": lb.get("discussed_stocks_count", 0),
            "top_watched": lb.get("top_watched", []),
            "longbridge_error": lb.get("error"),
            # Google Trends (macro retail sentiment)
            "google_trends_score": round(gt_score, 1),
            # HSI regime
            "hsi_regime_score": round(hsi_score, 1),
            "hsi_last_close": round(hsi["close"][-1], 2) if hsi["close"] else None,
            "hsi_data_days": len(hsi["close"]),
            **hsi_details,
        },
    })

    return result


def save_dopamine(result: dict) -> Path:
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

    print(f"\n{emoji} 多巴胺 v4: {d:.1f} ({lvl})")
    print(f"   {desc}")
    print(f"   spike≥{spike:.1f}% | consecutive≥{cons}d")
    print(f"   → saved to {path}\n")

    c = result["components"]
    print(f"── 長橋人氣 (40%) — 逐隻股票散戶關注 ──")
    print(f"   longbridge_score:    {c['longbridge_score']:.1f}")
    print(f"   market_temperature:  {c['market_temperature']}/100 — {c.get('market_temperature_desc','')}")
    print(f"   sentiment:           {c['market_sentiment']}/100")
    print(f"   關注度榜:             {c['watched_stocks_count']}隻上榜")
    print(f"   總熱度榜:             {c['hot_stocks_count']}隻上榜")
    print(f"   熱議榜:               {c['discussed_stocks_count']}隻上榜")
    print(f"   散戶最關注 TOP 5:")
    for s in c.get("top_watched", [])[:5]:
        print(f"     {s['code']} {s['name']} ${s['last_done']} chg={s['chg']}")

    print(f"\n── Google Trends 大市熱度 (30%) — 宏觀零售搜尋情緒 ──")
    print(f"   google_trends_score: {c['google_trends_score']:.1f}")

    print(f"\n── 恆指 regime (30%) ──")
    print(f"   hsi_regime_score: {c['hsi_regime_score']:.1f}")
    print(f"   HSI: {c['hsi_last_close']}")
    print(f"   volatility: {c['realized_volatility_annualized_pct']}%")
    print(f"   trend: {c['trend_strength']}")
    print(f"   range_ratio: {c['daily_range_ratio']}")
    print(f"   volume_ratio: {c['hsi_volume_ratio']}")
