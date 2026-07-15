#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
KBAR_PATH = DATA / "kbar_cache.json"
OUT_PATH = DATA / "trade_engine.json"
HOLDINGS_PATH = BASE / "holdings.json"
PRICES_PATH = DATA / "stock_prices.json"
SIGNALS_PATH = DATA / "signals.json"
ANNOUNCEMENTS_PATH = DATA / "announcements.json"
RIGHTS_ANALYSIS_PATH = DATA / "rights_analysis.json"
FUNDFLOW_PATH = DATA / "fundflow.json"
PARTICIPANT_ANOMALIES_PATH = DATA / "participant_anomalies.json"
DAILY_CACHE_DIR = BASE / "raw" / "trading_skill_kbars"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
DEFAULT_CANDIDATES = 240
DEFAULT_WORKERS = 6

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

FINANCE_EVENT_LENS = {
    "placement": {
        "lens": "配股不等於利好；先核對比例、折讓、授權方式、公司背景與資金用途。",
        "requires": ["配售比例", "折讓", "一般/特別授權", "資金用途"],
    },
    "rights": {
        "lens": "供股目的可能是供錢、供大、供乾或供賣殼；未有條款、股權變化與價格確認前不可定性。",
        "requires": ["供股比例", "折讓", "包銷/承諾", "集資用途", "完成後股權"],
    },
    "convertible": {
        "lens": "可換股債要同時核對承配人、息率、年期及換股價，不能只看換股價。",
        "requires": ["承配人", "息率", "到期日", "換股價", "全面兌換攤薄"],
    },
    "increase": {
        "lens": "大股東增持可降低流通量；若增持後股價仍逆向下跌，視為警號而非自動利好。",
        "requires": ["增持人", "作價", "股權變化", "增持後價格反應"],
    },
    "buyback": {
        "lens": "回購可減少流通股份；若回購後持續下跌，需防暗手持貨派發。",
        "requires": ["回購量", "回購價", "註銷狀態", "回購後價格反應"],
    },
    "failed_sale": {
        "lens": "賣盤洽談終止後，觀察一個月內能否重越洽談期高位；未突破只列觀察。",
        "requires": ["洽談期高位", "終止日期", "一個月期限", "突破收市確認"],
    },
    "general_offer": {
        "lens": "全購後要分開看新主背景、貨源集中與後續配供股，不因易手本身直接看升。",
        "requires": ["新主背景", "要約價", "完成狀態", "公眾持股", "後續股本事件"],
    },
    "consolidation": {
        "lens": "合股只改變股本單位；必須連同供配股、買賣單位與後續價格行為解讀。",
        "requires": ["合股比例", "每手股數", "同期供配股", "生效後價格"],
    },
    "subdivision": {
        "lens": "拆股不增加公司價值；留意入場門檻下降後是否配合派貨。",
        "requires": ["拆股比例", "每手股數", "生效後成交", "後續股權事件"],
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


def pct(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or base <= 0:
        return None
    return (value / base - 1) * 100


def hk_code(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    return str(int(digits)).zfill(5)


def hk_symbol(code: str) -> str:
    return f"{int(code)}.HK"


def normalize_daily_bar(row) -> dict | None:
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None
    stamp = str(row[0] or "")[:10]
    values = [num(row[index]) for index in range(1, 5)]
    if len(stamp) != 10 or any(value is None or value <= 0 for value in values):
        return None
    open_value, close_value, high_value, low_value = values
    if high_value < max(open_value, close_value, low_value) or low_value > min(open_value, close_value, high_value):
        return None
    volume = num(row[5])
    return {
        "time": stamp,
        "open": open_value,
        "high": high_value,
        "low": low_value,
        "close": close_value,
        "volume": volume if volume is not None and volume >= 0 else 0,
        "turnover": None,
    }


def validate_daily_bars(rows) -> list[dict]:
    bars: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if isinstance(row, dict):
            normalized = normalize_daily_bar([
                row.get("time") or row.get("date"), row.get("open"), row.get("close"),
                row.get("high"), row.get("low"), row.get("volume"),
            ])
        else:
            normalized = normalize_daily_bar(row)
        if normalized and normalized["time"] not in seen:
            seen.add(normalized["time"])
            bars.append(normalized)
    bars.sort(key=lambda item: item["time"])
    return bars


def fetch_tencent_daily(code: str, count: int = 520, timeout: int = 15) -> list[dict]:
    upstream = f"hk{code}"
    query = urllib.parse.urlencode({"param": f"{upstream},day,,,{count}"})
    request = urllib.request.Request(
        f"{TENCENT_KLINE_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 CCASS-TradeEngine/2"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    node = ((payload or {}).get("data") or {}).get(upstream) or {}
    return validate_daily_bars(node.get("day") or [])[-count:]


def cached_daily_bars(code: str, max_age_hours: float, offline: bool) -> tuple[list[dict], dict]:
    path = DAILY_CACHE_DIR / f"{code}.json"
    cached = load_json(path, {})
    cached_bars = validate_daily_bars((cached or {}).get("bars") or [])
    fetched_at = (cached or {}).get("fetched_at")
    age_hours = None
    if path.exists():
        age_hours = max(0.0, (time.time() - path.stat().st_mtime) / 3600)
    if cached_bars and (offline or (age_hours is not None and age_hours <= max_age_hours)):
        return cached_bars, {
            "source": "local observed Tencent cache",
            "fetched_at": fetched_at,
            "trade_date": cached_bars[-1]["time"],
            "cached": True,
        }
    if offline:
        return [], {"source": "offline cache miss", "error": "no observed cached bars"}
    bars = fetch_tencent_daily(code)
    if len(bars) < 21:
        raise RuntimeError(f"{code}: observed daily Kbar depth {len(bars)} < 21")
    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps({
        "code": code,
        "fetched_at": now,
        "source": "Tencent public HK daily K-line (unadjusted)",
        "data_kind": "observed_market_data",
        "is_observed": True,
        "bars": bars,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return bars, {
        "source": "Tencent public HK daily K-line (unadjusted)",
        "fetched_at": now,
        "trade_date": bars[-1]["time"],
        "cached": False,
    }


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
    base1 = series.get("1h") if isinstance(series.get("1h"), list) else []
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
    thrust1 = 0.0
    if len(bars1) >= 8:
        last1_close = num(bars1[-1].get("close"))
        base1_close = num(bars1[-8].get("close"))
        if last1_close is not None and base1_close and base1_close > 0:
            thrust1 = ((last1_close - base1_close) / base1_close) * 100
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
    if thrust1 > 1:
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
    if abs(thrust1) <= 1.5:
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
    if thrust1 > 1:
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
    if thrust1 > 0.8:
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
        "thrust1": thrust1,
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
                        {"label": "1h thrust", "value": signed(thrust1, "%")},
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
                        {"label": "1h thrust", "value": signed(thrust1, "%")},
                    ]
                    if key == "breaklow"
                    else [
                        {"label": "1H / 4H", "value": f"{trend1} / {trend4}"},
                        {"label": "Off low20", "value": signed(bounce_low20, "%")},
                        {"label": "Gap to high20", "value": signed(gap_high20, "%")},
                        {"label": "1h thrust", "value": signed(thrust1, "%")},
                    ]
                ),
                "note": item["note"],
            }
            for key, item in SETUP_META.items()
        ],
        "trendGuard": trend_guard(metrics),
        "analysis_timeframes": {"short": "1H", "long": "4H"},
        "data_kind": "derived_rule_output",
        "is_observed": False,
    }


def analyze_daily_setups(entry: dict) -> dict | None:
    bars = series_for_interval(entry, "1d")
    if len(bars) < 50:
        return None
    close = num(bars[-1].get("close"))
    ema8 = ema(bars, 8)
    ema20 = ema(bars, 20)
    ema50 = ema(bars, 50)
    ema200 = ema(bars, 200)
    if close is None or ema8 is None or ema20 is None or ema50 is None:
        return None

    prior20 = bars[-21:-1]
    prior55 = bars[-56:-1] if len(bars) >= 56 else bars[:-1]
    high20 = max((num(bar.get("high")) for bar in prior20), default=None)
    low20 = min((num(bar.get("low")) for bar in prior20), default=None)
    high55 = max((num(bar.get("high")) for bar in prior55), default=high20)
    if high20 is None or low20 is None or high20 <= 0 or low20 <= 0:
        return None
    last_high = num(bars[-1].get("high"))
    last_low = num(bars[-1].get("low"))
    recent5 = bars[-5:]
    older = bars[-25:-5]
    recent_low = min((num(bar.get("low")) for bar in recent5), default=low20)
    prior_low = min((num(bar.get("low")) for bar in older), default=low20)
    broke_prior_low = bool(recent_low is not None and prior_low is not None and recent_low < prior_low * 0.9975)
    reclaim_prev_low = pct(close, prior_low)
    gap_high20 = pct(close, high20)
    bounce_low20 = pct(close, low20)
    range_pct = pct(high20, low20) or 0
    pos_in_range = clamp((close - low20) / (high20 - low20), 0, 1) if high20 > low20 else 0.5
    thrust = momentum_return(bars, 5) or 0
    ema_spread_short = pct(ema8, ema20) or 0
    ema_spread_long = pct(ema50, ema200) if ema200 else pct(close, ema50)
    ema_spread_long = ema_spread_long or 0
    trend_short = "up" if close > ema20 and ema8 >= ema20 else ("down" if close < ema20 and ema8 <= ema20 else "flat")
    long_guard = ema200 if ema200 is not None else ema50
    trend_long = "up" if ema50 >= long_guard and close >= ema50 else ("down" if ema50 < long_guard and close < ema50 else "flat")
    new_high = bool(last_high is not None and last_high > high20)
    new_low = bool(last_low is not None and last_low < low20)

    breakout_score = (3 if trend_short == "up" else 0) + (2 if trend_long == "up" else 0)
    breakout_score += 2 if close > ema8 else (1 if close > ema20 else 0)
    breakout_score += 3 if gap_high20 is not None and gap_high20 >= -2.5 else (1 if gap_high20 is not None and gap_high20 >= -5 else 0)
    breakout_score += 1 if thrust > 2 else 0
    breakout_score += 1 if pos_in_range > 0.75 else 0

    base_score = 3 if range_pct <= 12 else (1 if range_pct <= 18 else 0)
    base_score += 2 if abs(ema_spread_short) <= 2 else 0
    base_score += 2 if abs(ema_spread_long) <= 6 else 0
    base_score += 2 if 0.25 <= pos_in_range <= 0.75 else 0
    base_score += 1 if abs(thrust) <= 3 else 0

    breaklow_score = (1 if trend_short == "down" else 0) + (2 if trend_long == "down" else 0)
    breaklow_score += 3 if broke_prior_low else 0
    breaklow_score += 2 if reclaim_prev_low is not None and reclaim_prev_low >= 0.5 else (1 if reclaim_prev_low is not None and reclaim_prev_low >= 0 else 0)
    breaklow_score += 1 if close > ema8 else 0
    breaklow_score += 1 if bounce_low20 is not None and bounce_low20 >= 3 else 0
    breaklow_score += 1 if thrust > 1 else 0
    if not broke_prior_low:
        breaklow_score = min(breaklow_score, 4)
    if reclaim_prev_low is None or reclaim_prev_low < 0:
        breaklow_score = min(breaklow_score, 5)

    rebound_score = (2 if trend_short == "down" else 0) + (2 if trend_long == "down" else 0)
    rebound_score += 2 if close > ema8 else 0
    rebound_score += 2 if close < ema20 else 0
    rebound_score += 2 if bounce_low20 is not None and bounce_low20 >= 4 else (1 if bounce_low20 is not None and bounce_low20 >= 1 else 0)
    rebound_score += 1 if gap_high20 is not None and gap_high20 <= -5 else 0
    rebound_score += 1 if thrust > 2 else 0

    scores = {
        "breakout": int(clamp(breakout_score, 0, 10)),
        "base": int(clamp(base_score, 0, 10)),
        "breaklow": int(clamp(breaklow_score, 0, 10)),
        "rebound": int(clamp(rebound_score, 0, 10)),
    }
    active_key = max(("breakout", "breaklow", "rebound", "base"), key=lambda key: (scores[key], -list(SETUP_META).index(key)))
    invalidation = {
        "breakout": max(low20, ema20),
        "base": low20,
        "breaklow": recent_low,
        "rebound": recent_low,
    }[active_key]
    entry_level = {
        "breakout": high20,
        "base": high20,
        "breaklow": prior_low,
        "rebound": ema20,
    }[active_key]
    risk = entry_level - invalidation if entry_level and invalidation else None
    target = max(high55 or entry_level, entry_level + risk * 2) if risk is not None and risk > 0 else high55
    metrics = {
        "close1": close,
        "trend1": trend_short,
        "trend4": trend_long,
        "gapHigh20": gap_high20,
        "bounceLow20": bounce_low20,
        "rangePct": range_pct,
        "thrust1": thrust,
        "emaSpread1": ema_spread_short,
        "emaSpread4": ema_spread_long,
        "posInRange": pos_in_range,
        "priorLow": prior_low,
        "recentLow": recent_low,
        "reclaimPrevLow": reclaim_prev_low,
        "brokePriorLow": broke_prior_low,
        "high20": high20,
        "high55": high55,
        "low20": low20,
        "priorHigh20": high20,
        "priorLow20": low20,
        "newHigh": new_high,
        "newLow": new_low,
        "ema8_1": ema8,
        "ema21_1": ema20,
        "ema50": ema50,
        "ema200": ema200,
    }
    meta = SETUP_META[active_key]
    cards = []
    for key, item in SETUP_META.items():
        cards.append({
            "key": key,
            "tone": item["tone"],
            "name": item["label"],
            "kicker": item["sub"],
            "tag": "active" if active_key == key else "watch",
            "score": scores[key],
            "active": active_key == key,
            "stats": [
                {"label": "Daily / regime", "value": f"{trend_short} / {trend_long}"},
                {"label": "Gap to high20", "value": signed(gap_high20, "%")},
                {"label": "5D thrust", "value": signed(thrust, "%")},
                {"label": "Range pos", "value": f"{round(pos_in_range * 100)}%"},
            ],
            "note": item["note"],
        })
    guard = trend_guard(metrics)
    guard["note"] = guard["note"].replace("1H / 4H", "Daily / regime").replace("1H EMA21", "daily EMA20").replace("4H", "regime").replace("1H", "daily")
    return {
        "symbol": entry.get("symbol"),
        "label": entry.get("label") or entry.get("symbol"),
        "market": entry.get("market"),
        "activeKey": active_key,
        "scores": scores,
        "metrics": metrics,
        "cards": cards,
        "trendGuard": guard,
        "analysis_timeframes": {"short": "1D", "long": "EMA50/200 regime"},
        "trade_plan": {
            "entry": entry_level,
            "invalidation": invalidation,
            "target": target,
            "basis": "observed unadjusted daily bars; derived levels, not a price forecast",
        },
        "data_kind": "derived_rule_output",
        "is_observed": False,
    }


def signal_map() -> dict[str, dict]:
    payload = load_json(SIGNALS_PATH, {})
    groups = payload.get("groups") if isinstance(payload, dict) else []
    return {hk_code(item.get("code")): item for item in (groups or []) if isinstance(item, dict) and hk_code(item.get("code"))}


def signal_label(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    return str(item.get("label") or item.get("type") or item.get("name") or item.get("signal") or "").strip()


def classify_technical_confirmations(technical: list[dict]) -> list[dict]:
    """Map published signals to the three selected technical confirmations."""
    found: dict[str, dict] = {}
    for item in technical:
        label = str(item.get("label") or "")
        category = str(item.get("category") or "").lower()
        key = display = None
        if category == "gap" and ("向上" in label or "跳空" in label):
            key, display = "gap_up", "Gap 跳升"
        elif category == "fvg" and ("向上" in label or "bullish" in label.lower()):
            key, display = "fvg_up", "向上 FVG"
        elif category == "poc" and any(token in label for token in ("半年", "12個月", "3年", "12M")):
            key, display = "poc_break", "突破中長期 POC"
        if key and key not in found:
            found[key] = {
                "key": key,
                "label": display,
                "source_label": label,
                "date": item.get("date"),
                "is_observed": True,
            }
    return [found[key] for key in ("gap_up", "fvg_up", "poc_break") if key in found]


def _clean_term(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"--", "—", "n/a", "na", "none", "null"}:
        return None
    return text


def _authorization_label(row: dict) -> str | None:
    blob = " ".join(str(row.get(key) or "") for key in ("method", "purpose", "title")).upper()
    if "SPECIAL MANDATE" in blob or "特別授權" in blob:
        return "特別授權"
    if "GENERAL MANDATE" in blob or "一般授權" in blob:
        return "一般授權"
    return None


def capital_action_terms(row: dict | None) -> dict | None:
    """Expose only terms already extracted by the canonical rights pipeline."""
    if not isinstance(row, dict):
        return None
    dilution = num(row.get("pct_num"))
    if dilution is None:
        dilution = num(row.get("pct_shares"))
    discount = num(row.get("discount_pct"))
    ratio = _clean_term(row.get("ratio"))
    authorization = _authorization_label(row)
    purpose = _clean_term(row.get("purpose"))
    title = _clean_term(row.get("title"))
    if purpose and (purpose == title or purpose.startswith("公司公告：")):
        purpose = None
    supply = row.get("supply") if isinstance(row.get("supply"), dict) else {}

    ratio_value = ratio or (f"{dilution:.3f}%" if dilution is not None else None)
    if discount is None:
        discount_value = None
    elif discount < 0:
        discount_value = f"折讓 {abs(discount):.1f}%"
    elif discount > 0:
        discount_value = f"溢價 {discount:.1f}%"
    else:
        discount_value = "無折溢價"
    checks = [
        {"key": "ratio", "label": "比例 / 攤薄", "value": ratio_value, "status": "observed" if ratio_value else "missing"},
        {"key": "discount", "label": "折讓 / 溢價", "value": discount_value, "status": "observed" if discount_value else "missing"},
        {"key": "authorization", "label": "授權方式", "value": authorization, "status": "observed" if authorization else "missing"},
        {"key": "purpose", "label": "資金用途", "value": purpose, "status": "observed" if purpose else "missing"},
    ]
    observed_count = sum(item["status"] == "observed" for item in checks)
    missing = [item["label"] for item in checks if item["status"] == "missing"]
    pending = [str(item) for item in (supply.get("pending") or []) if str(item).strip()]
    for label in missing:
        note = f"未抽到{label}"
        if note not in pending:
            pending.append(note)
    dilution_tier = None
    if dilution is not None:
        dilution_tier = "極高" if dilution >= 50 else "高" if dilution >= 20 else "中" if dilution >= 10 else "低"
    discount_abs = abs(discount) if discount is not None else None
    discount_tier = None
    if discount_abs is not None:
        discount_tier = "極深" if discount_abs >= 30 else "深" if discount_abs >= 15 else "中" if discount_abs >= 5 else "低"
    return {
        "source_date": row.get("date_parsed") or row.get("date"),
        "source_url": row.get("pdf_url"),
        "stage": row.get("announcement_stage"),
        "category": row.get("category_display") or row.get("category"),
        "ratio": ratio,
        "dilution_pct": dilution,
        "dilution_tier": dilution_tier,
        "discount_pct": discount,
        "discount_tier": discount_tier,
        "issue_price": num(row.get("price_num")),
        "amount": _clean_term(row.get("amount")),
        "authorization": authorization,
        "purpose": purpose,
        "placing_agent": _clean_term(row.get("placing_agent")),
        "supply_label": supply.get("label"),
        "supply_class": supply.get("cls"),
        "supply_basis": supply.get("basis"),
        "positive": supply.get("positive") or [],
        "negative": supply.get("negative") or [],
        "pending": pending,
        "checks": checks,
        "coverage": {"observed": observed_count, "total": len(checks), "complete": observed_count == len(checks)},
        "data_kind": "observed_extracted_terms",
        "is_observed": True,
    }


def rights_analysis_map() -> dict[str, list[dict]]:
    payload = load_json(RIGHTS_ANALYSIS_PATH, [])
    rows = payload if isinstance(payload, list) else []
    by_code: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = hk_code(row.get("code"))
        if code:
            by_code.setdefault(code, []).append(row)
    for code in by_code:
        by_code[code].sort(key=lambda item: str(item.get("date_parsed") or item.get("date") or ""), reverse=True)
    return by_code


def _terms_for_event(event_row: dict, event_key: str, rights_rows: list[dict] | None) -> dict | None:
    event_date = str(event_row.get("date") or event_row.get("release_date") or "")[:10]
    for row in rights_rows or []:
        source_date = str(row.get("date_parsed") or row.get("date") or "")[:10]
        event_type = str(row.get("announcement_type") or "").lower()
        title = str(row.get("title") or "").upper()
        compatible = (
            (event_key == "placement" and event_type == "placement")
            or (event_key == "rights" and event_type == "rights")
            or (event_key == "consolidation" and "CONSOLIDATION" in title)
            or (event_key == "capital_reduction" and "CAPITAL REDUCTION" in title)
        )
        if compatible and source_date == event_date:
            return capital_action_terms(row)
    return None


def classify_finance_events(rows: list[dict] | None, rights_rows: list[dict] | None = None) -> list[dict]:
    """Classify observed announcement titles without inferring an unreported event."""
    type_labels = {
        "placement": ("placement", "配股 / 配售", "risk"),
        "rights": ("rights", "供股", "risk"),
        "increase": ("increase", "股東增持", "support"),
        "buyback": ("buyback", "股份回購", "support"),
        "acquisition": ("acquisition", "收購 / 要約", "watch"),
        "resume": ("resume", "復牌", "watch"),
        "block_trade": ("block_trade", "大手交易", "watch"),
    }
    results: list[dict] = []
    seen: set[str] = set()
    ordered_rows = sorted(rows or [], key=lambda row: str(row.get("date") or row.get("release_date") or ""), reverse=True)
    for row in ordered_rows:
        title = str(row.get("title") or "")
        upper = title.upper()
        event_type = str(row.get("type") or "").lower()
        matches: list[tuple[str, str, str]] = []
        if event_type in type_labels:
            matches.append(type_labels[event_type])
        if "CONVERTIBLE BOND" in upper or "CONVERTIBLE NOTE" in upper:
            matches.append(("convertible", "可換股債", "risk"))
        if "SHARE CONSOLIDATION" in upper:
            matches.append(("consolidation", "合股", "risk"))
        if "SHARE SUBDIVISION" in upper:
            matches.append(("subdivision", "拆股", "watch"))
        if "CAPITAL REDUCTION" in upper:
            matches.append(("capital_reduction", "股本削減", "watch"))
        termination = any(token in upper for token in ("TERMINATION", "TERMINATED", "LAPSE", "LAPSED"))
        transaction = any(token in upper for token in ("SALE", "DISPOSAL", "ACQUISITION", "OFFER"))
        if termination and transaction:
            matches.append(("failed_sale", "賣盤 / 交易終止", "watch"))
        if "GENERAL OFFER" in upper or "TAKEOVERS CODE" in upper:
            matches.append(("general_offer", "全購 / 要約", "watch"))
        for key, label, tone in matches:
            if key in seen:
                continue
            seen.add(key)
            method = FINANCE_EVENT_LENS.get(key) or {}
            terms = _terms_for_event(row, key, rights_rows)
            coverage = (terms or {}).get("coverage") or {}
            if not terms or not coverage.get("observed"):
                terms_status = "not_extracted"
            elif coverage.get("complete"):
                terms_status = "complete"
            else:
                terms_status = "partial"
            results.append({
                "key": key,
                "label": label,
                "tone": tone,
                "date": row.get("date") or row.get("release_date"),
                "title": title,
                "url": row.get("url"),
                "method_lens": method.get("lens"),
                "requires": method.get("requires") or [],
                "terms": terms,
                "terms_status": terms_status,
                "is_observed": True,
            })
    results.sort(key=lambda item: (str(item.get("date") or ""), item["key"]), reverse=True)
    return results[:8]


def announcement_map() -> dict[str, list[dict]]:
    payload = load_json(ANNOUNCEMENTS_PATH, [])
    rows = payload if isinstance(payload, list) else []
    by_code: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = hk_code(row.get("code"))
        if code:
            by_code.setdefault(code, []).append(row)
    return by_code


def participant_anomaly_map() -> dict[str, list[dict]]:
    """Return only observed stock-level CCASS patterns; participant rows stay in the source file."""
    payload = load_json(PARTICIPANT_ANOMALIES_PATH, {})
    rows = payload.get("anomalies") if isinstance(payload, dict) else []
    allowed = {"accumulation_cluster", "distribution_cluster", "suspected_transfer"}
    by_code: dict[str, list[dict]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("scope") != "stock" or row.get("type") not in allowed:
            continue
        code = hk_code(row.get("code"))
        if not code:
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        by_code.setdefault(code, []).append({
            "key": row.get("type"),
            "date": row.get("date"),
            "previous_date": row.get("previous_date"),
            "severity": row.get("severity"),
            "shares_delta": num(row.get("shares_delta")),
            "pct_delta": num(row.get("pct_delta")),
            "top5_delta": num(details.get("top5_delta")),
            "top10_delta": num(details.get("top10_delta")),
            "participants_delta": num(details.get("participants_delta")),
            "matched_turnover_pct": num(details.get("matched_turnover_pct")),
            "is_observed": True,
        })
    priority = {"suspected_transfer": 3, "distribution_cluster": 2, "accumulation_cluster": 1}
    for code in by_code:
        by_code[code].sort(
            key=lambda item: (str(item.get("date") or ""), priority.get(str(item.get("key")), 0)),
            reverse=True,
        )
    return by_code


def ccass_concentration_proxy(market_pct, top5_pct) -> dict:
    """Book-method proxy: non-CCASS plus top-five share of the in-CCASS balance."""
    market = num(market_pct)
    top5 = num(top5_pct)
    if market is None or top5 is None or not (0 <= market <= 100 and 0 <= top5 <= 100):
        return {
            "available": False,
            "top5_plus_non_ccass_pct": None,
            "tier": "unavailable",
            "is_observed": False,
        }
    value = (100 - market) + market * top5 / 100
    tier = "concentrated" if value >= 90 else "watch" if value >= 80 else "broad"
    return {
        "available": True,
        "market_pct": round(market, 4),
        "top5_share_of_ccass_pct": round(top5, 4),
        "non_ccass_pct": round(100 - market, 4),
        "top5_plus_non_ccass_pct": round(value, 4),
        "tier": tier,
        "threshold_pct": 90,
        "basis": "(100 - Market%) + Market% x Top5%; derived from observed broker-level CCASS distribution",
        "is_observed": False,
    }


def classify_signal_lanes(
    group: dict,
    announcements: list[dict] | None = None,
    rights_rows: list[dict] | None = None,
) -> dict:
    """Partition every published signal into exactly one evidence lane."""
    technical: list[dict] = []
    events: list[dict] = []
    ccass: list[dict] = []
    for raw in group.get("signals") or []:
        item = raw if isinstance(raw, dict) else {"label": str(raw), "category": "unknown"}
        label = signal_label(item)
        category = str(item.get("category") or "unknown").lower()
        normalized = {"label": label, "category": category, "date": item.get("date")}
        if label.upper().startswith("CCASS"):
            ccass.append(normalized)
        elif category in {"corp", "unknown"}:
            events.append(normalized)
        else:
            technical.append(normalized)

    corp_types = group.get("corpTypes") if isinstance(group.get("corpTypes"), dict) else {}
    supply = group.get("supply") if isinstance(group.get("supply"), dict) else {}
    supply_class = str(supply.get("cls") or "")
    finance_events = classify_finance_events(announcements, rights_rows)
    event_active = bool(events or finance_events or any(bool(value) for value in corp_types.values()) or supply_class)
    if supply_class == "supply-stock":
        event_direction = "positive_supply"
    elif supply_class == "supply-cash":
        event_direction = "negative_supply"
    elif corp_types.get("increase"):
        event_direction = "shareholder_increase"
    elif supply_class in {"supply-watch", "supply-ended"}:
        event_direction = "watch"
    else:
        event_direction = "neutral"
    technical_confirmations = classify_technical_confirmations(technical)
    return {
        "event": {
            "active": event_active,
            "direction": event_direction,
            "supply_class": supply_class or None,
            "labels": events,
            "finance_events": finance_events,
            "is_observed": True,
        },
        "technical": {
            "active": bool(technical),
            "count": len(technical),
            "labels": technical,
            "technical_confirmations": technical_confirmations,
            "technical_confirmation_count": len(technical_confirmations),
            "is_observed": True,
        },
        "ccass_signals": {
            "active": bool(ccass),
            "labels": ccass,
            "is_observed": True,
        },
    }


def fundflow_map() -> dict[str, dict]:
    payload = load_json(FUNDFLOW_PATH, {})
    rows = payload.get("all") if isinstance(payload, dict) else {}
    if isinstance(rows, dict):
        return {hk_code(code): item for code, item in rows.items() if isinstance(item, dict)}
    return {hk_code(item.get("code")): item for item in (rows or []) if isinstance(item, dict) and hk_code(item.get("code"))}


def stage1_candidates(limit: int) -> tuple[list[dict], dict]:
    holdings = load_json(HOLDINGS_PATH, {})
    prices = load_json(PRICES_PATH, {})
    signals = signal_map()
    announcements = announcement_map()
    rights_rows = rights_analysis_map()
    participant_patterns = participant_anomaly_map()
    flows = fundflow_map()
    rows = holdings.get("stocks") if isinstance(holdings, dict) else []
    ranked: list[dict] = []
    bucket_counts = {"small": 0, "mid": 0, "large": 0}
    for holding in rows or []:
        if not isinstance(holding, dict):
            continue
        code = hk_code(holding.get("c"))
        price = prices.get(code, {}) if isinstance(prices, dict) else {}
        last = num(price.get("lp")) or num(holding.get("lp"))
        market_cap = num(price.get("mc")) or num(holding.get("mc"))
        if not code or last is None or last <= 0 or holding.get("suspended"):
            continue
        bucket = "small" if market_cap is None or market_cap < 20 else ("mid" if market_cap < 100 else "large")
        bucket_counts[bucket] += 1
        score = 0.0
        reasons: list[str] = []
        p52 = num(price.get("p52")) or num(holding.get("p52"))
        vr = num(price.get("vr")) or num(holding.get("vr"))
        chg = num(price.get("chg")) or num(holding.get("chg"))
        turnover = num(price.get("turnover"))
        d5p = num(holding.get("d5p"))
        d20p = num(holding.get("d20p"))
        d5s = num(holding.get("d5s"))
        d20s = num(holding.get("d20s"))
        streak = int(num(holding.get("su")) or 0)
        concentration = ccass_concentration_proxy(holding.get("tp"), holding.get("t5"))
        observed_patterns = participant_patterns.get(code) or []
        participant_pattern = observed_patterns[0] if observed_patterns else None
        if p52 is not None:
            score += clamp((p52 - 50) / 6, -5, 8)
            if p52 >= 80:
                reasons.append("52-week strength")
            elif p52 <= 20:
                reasons.append("low-zone reversal watch")
        if vr is not None:
            score += clamp((vr - 1) * 5, -2, 10)
            if vr >= 1.5:
                reasons.append("relative volume")
        if chg is not None:
            score += clamp(chg * 0.4, -5, 5)
        if turnover is not None and turnover > 0:
            score += clamp(math.log10(turnover) - 6, 0, 3)
        if d5p is not None:
            score += clamp(d5p * 4, -5, 7)
            if d5p > 0:
                reasons.append("CCASS 5D increase")
        if d20p is not None:
            score += clamp(d20p * 2, -4, 6)
        if d5p is not None and d20p is not None and d5p > 0 and d20p > 0:
            score += 2.5
            reasons.append("CCASS 5D/20D increase")
        if streak >= 2:
            score += min(6.0, 1.2 + streak * 0.65)
            reasons.append(f"CCASS streak {streak}D")
        if concentration.get("tier") == "concentrated" and streak >= 2:
            score += 2
            reasons.append("CCASS concentrated + rising")
        if participant_pattern:
            pattern_key = participant_pattern.get("key")
            if pattern_key == "accumulation_cluster":
                score += 2
                reasons.append("observed multi-seat accumulation")
            elif pattern_key == "distribution_cluster":
                score -= 3
                reasons.append("observed multi-seat distribution")
            elif pattern_key == "suspected_transfer":
                reasons.append("suspected broker-seat transfer")
        sig = signals.get(code) or {}
        lanes = classify_signal_lanes(sig, announcements.get(code), rights_rows.get(code))
        technical = lanes["technical"]["labels"]
        score += min(len(technical), 4) * 1.5
        if technical:
            reasons.append("existing technical signal")
        corp_types = sig.get("corpTypes") or {}
        if corp_types.get("increase"):
            score += 2.5
            reasons.append("event: shareholder increase")
        if lanes["event"]["direction"] == "positive_supply":
            score += 1.5
            reasons.append("event: stock-supply setup")
        elif lanes["event"]["direction"] == "negative_supply":
            score -= 4
            reasons.append("supply event risk")
        elif (corp_types.get("placement") or corp_types.get("rights")) and lanes["event"]["direction"] != "watch":
            score -= 2
            reasons.append("supply event risk")
        elif lanes["event"]["active"]:
            reasons.append("corporate event trigger")
        if streak >= 3 and (d5p or 0) > 0 and (d20p or 0) > 0:
            ccass_tier = "strong"
        elif streak >= 2 and (d5p or 0) > 0:
            ccass_tier = "building"
        elif streak > 0:
            ccass_tier = "early"
        else:
            ccass_tier = "none"
        lanes["ccass"] = {
            "active": ccass_tier != "none" or bool(participant_pattern) or concentration.get("tier") == "concentrated",
            "tier": ccass_tier,
            "consecutive_increase_days": streak,
            "d5_pct": d5p,
            "d20_pct": d20p,
            "d5_shares": d5s,
            "d20_shares": d20s,
            "concentration": concentration,
            "participant_pattern": participant_pattern,
            "basis": "CCASS aggregate total_shares; neutral days do not break the streak",
            "is_observed": True,
        }
        flow = flows.get(code) or {}
        main_net = num(flow.get("main_net"))
        if main_net is not None:
            score += 3 if main_net > 0 else -2
            reasons.append("main flow in" if main_net > 0 else "main flow out")
        if bucket == "small":
            score += 2
        ranked.append({
            "code": code,
            "symbol": hk_symbol(code),
            "label": holding.get("n") or code,
            "market": "hk",
            "bucket": bucket,
            "stage1_score": round(score, 2),
            "reasons": reasons[:6],
            "snapshot": {
                "price": last,
                "market_cap_hkd_bn": market_cap,
                "p52": p52,
                "vr": vr,
                "change_pct": chg,
                "ccass_d5_pct": d5p,
                "ccass_d20_pct": d20p,
                "ccass_d5_shares": d5s,
                "ccass_d20_shares": d20s,
                "ccass_increase_days": streak,
                "ccass_market_pct": num(holding.get("tp")),
                "ccass_top5_pct": num(holding.get("t5")),
                "ccass_concentration_proxy_pct": concentration.get("top5_plus_non_ccass_pct"),
            },
            "evidence_lanes": lanes,
        })
    ranked.sort(key=lambda item: (-item["stage1_score"], item["code"]))
    quotas = {
        "small": max(1, round(limit * 0.42)),
        "mid": max(1, round(limit * 0.33)),
        "large": max(1, limit - round(limit * 0.42) - round(limit * 0.33)),
    }
    selected: list[dict] = []
    chosen: set[str] = set()
    for bucket in ("small", "mid", "large"):
        for item in (row for row in ranked if row["bucket"] == bucket):
            if sum(1 for row in selected if row["bucket"] == bucket) >= quotas[bucket]:
                break
            selected.append(item)
            chosen.add(item["code"])
    for item in ranked:
        if len(selected) >= limit:
            break
        if item["code"] not in chosen:
            selected.append(item)
            chosen.add(item["code"])
    selected.sort(key=lambda item: (-item["stage1_score"], item["code"]))
    return selected, {
        "universe_count": len(ranked),
        "available_by_bucket": bucket_counts,
        "selected_by_bucket": {bucket: sum(1 for item in selected if item["bucket"] == bucket) for bucket in bucket_counts},
        "candidate_limit": limit,
    }


def momentum_return(bars: list[dict], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    now = num(bars[-1].get("close"))
    old = num(bars[-1 - lookback].get("close"))
    if now is None or old is None or old <= 0:
        return None
    return (now / old - 1) * 100


def build_smallcap_playbook(candidate: dict, setup: dict, lanes: dict) -> dict:
    """Build an auditable finance x technical x CCASS funnel, never a buy instruction."""
    event = lanes.get("event") or {}
    technical = lanes.get("technical") or {}
    ccass = lanes.get("ccass") or {}
    confirmations = technical.get("technical_confirmations") or []
    confirmation_keys = [item.get("key") for item in confirmations if item.get("key")]
    ccass_confirmed = ccass.get("tier") in {"strong", "building"}
    concentration = ccass.get("concentration") or {}
    participant_pattern = ccass.get("participant_pattern")
    ccass_structure_key = (participant_pattern or {}).get("key") or concentration.get("tier")
    ccass_structure_support = (
        concentration.get("tier") == "concentrated"
        or (participant_pattern or {}).get("key") == "accumulation_cluster"
    )
    supply_risk = event.get("direction") == "negative_supply"
    event_active = bool(event.get("active"))
    technical_active = bool(confirmations)
    three_lane = event_active and technical_active and ccass_confirmed and not supply_risk

    if supply_risk:
        state_key, state_label = "supply_risk", "圈錢 / 攤薄風險"
    elif three_lane:
        state_key, state_label = "three_lane", "財技 × 技術 × CCASS"
    elif len(confirmations) >= 2:
        state_key, state_label = "technical_confirmed", "技術雙確認"
    elif event_active and not technical_active:
        state_key, state_label = "event_wait_technical", "財技後等技術"
    elif ccass_confirmed and not technical_active:
        state_key, state_label = "ccass_wait_technical", "收集後等技術"
    elif technical_active:
        state_key, state_label = "technical_watch", "技術確認"
    else:
        state_key, state_label = "observe", "證據未齊"

    return {
        "scope": candidate.get("bucket"),
        "state_key": state_key,
        "state_label": state_label,
        "three_lane": three_lane,
        "evidence_lane_count": int(event_active) + int(technical_active) + int(ccass_confirmed),
        "finance_event_active": event_active,
        "finance_events": event.get("finance_events") or [],
        "supply_direction": event.get("direction"),
        "supply_class": event.get("supply_class"),
        "technical_active": technical_active,
        "technical_confirmation_keys": confirmation_keys,
        "technical_confirmations": confirmations,
        "derived_kbar_setup": setup.get("activeKey"),
        "ccass_confirmed": ccass_confirmed,
        "ccass_tier": ccass.get("tier"),
        "ccass_increase_days": ccass.get("consecutive_increase_days"),
        "ccass_structure_key": ccass_structure_key,
        "ccass_structure_support": ccass_structure_support,
        "ccass_concentration": concentration,
        "ccass_participant_pattern": participant_pattern,
        "data_kind": "derived_evidence_funnel",
        "is_observed": False,
        "basis": "Observed announcements, published Kbar signals, aggregate holdings and broker-seat patterns stay separate; concentration is a derived broker-level proxy, not investor identity.",
    }


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
        score += clamp(r5 * 1.5, -15, 18)
    if r20 is not None:
        score += clamp(r20 * 0.8, -18, 22)
    if r60 is not None:
        score += clamp(r60 * 0.35, -15, 18)
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
        "score": round(clamp(score, -100, 100), 2),
        "tradePlan": setup.get("trade_plan") if setup else None,
        "analysisTimeframes": setup.get("analysis_timeframes") if setup else None,
        "extremeMove": any(abs(value) >= 50 for value in (r5, r20, r60) if value is not None),
    }


def build_engine(
    candidate_count: int = DEFAULT_CANDIDATES,
    workers: int = DEFAULT_WORKERS,
    cache_max_age_hours: float = 18,
    offline: bool = False,
) -> dict:
    cache = load_json(KBAR_PATH, {})
    symbols = (cache or {}).get("symbols") or {}
    built_at = datetime.now().isoformat(timespec="seconds")
    candidates, stage1 = stage1_candidates(candidate_count)
    by_symbol: dict[str, dict] = {}
    groups = {key: [] for key in SETUP_META}
    momentum_rows: list[dict] = []
    failures: list[dict] = []
    source_dates: list[str] = []

    def load_candidate(candidate: dict) -> tuple[dict, dict | None, dict | None]:
        code = candidate["code"]
        try:
            bars, source_meta = cached_daily_bars(code, cache_max_age_hours, offline)
        except Exception as exc:
            return candidate, None, {"code": code, "error": str(exc)}
        if len(bars) < 50:
            return candidate, None, {"code": code, "error": f"observed daily Kbar depth {len(bars)} < 50"}
        return candidate, {
            "symbol": candidate["symbol"],
            "label": candidate["label"],
            "market": "hk",
            "series": {"1d": bars},
            "series_meta": {"1d": {"count": len(bars), **source_meta}},
        }, None

    loaded: list[tuple[dict, dict]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(load_candidate, candidate) for candidate in candidates]
        for future in concurrent.futures.as_completed(futures):
            candidate, entry, failure = future.result()
            if failure:
                failures.append(failure)
            elif entry:
                loaded.append((candidate, entry))

    loaded.sort(key=lambda pair: (-pair[0]["stage1_score"], pair[0]["code"]))
    for candidate, entry in loaded:
        setup = analyze_daily_setups(entry)
        if not setup:
            failures.append({"code": candidate["code"], "error": "daily setup analysis unavailable"})
            continue
        lanes = candidate["evidence_lanes"]
        published_technical = lanes["technical"]
        lanes["technical"] = {
            **published_technical,
            "active": True,
            "published_signal_active": bool(published_technical.get("active")),
            "derived_setup_active": True,
            "setup_key": setup.get("activeKey"),
            "setup_score": (setup.get("scores") or {}).get(setup.get("activeKey")),
            "data_kind": "mixed_observed_signals_and_derived_kbar_setup",
            "setup_is_observed": False,
        }
        setup["stage1"] = {
            "score": candidate["stage1_score"],
            "bucket": candidate["bucket"],
            "reasons": candidate["reasons"],
            "snapshot": candidate["snapshot"],
            "evidence_lanes": lanes,
        }
        setup["smallcap_playbook"] = build_smallcap_playbook(candidate, setup, lanes)
        meta = entry["series_meta"]["1d"]
        setup["observed_source"] = {
            "source": meta.get("source"),
            "fetched_at": meta.get("fetched_at"),
            "trade_date": meta.get("trade_date"),
            "bar_count": meta.get("count"),
            "is_observed": True,
        }
        if meta.get("trade_date"):
            source_dates.append(str(meta["trade_date"])[:10])
        symbol = candidate["symbol"]
        by_symbol[symbol] = setup
        active_key = setup["activeKey"]
        groups[active_key].append({
            "symbol": symbol,
            "label": setup["label"],
            "market": "hk",
            "score": setup["scores"][active_key],
            "setupKey": active_key,
            "stage1Score": candidate["stage1_score"],
            "tradePlan": setup.get("trade_plan"),
            "tradeDate": meta.get("trade_date"),
        })
        row = build_momentum_row(entry, setup)
        if row:
            row["stage1Score"] = candidate["stage1_score"]
            row["bucket"] = candidate["bucket"]
            row["reasons"] = candidate["reasons"]
            row["tradeDate"] = meta.get("trade_date")
            momentum_rows.append(row)

    # Preserve non-HK preset analysis without making it part of the HK candidate count.
    for symbol, entry in symbols.items():
        if not isinstance(entry, dict) or symbol.endswith(".HK"):
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

    source_updated_at = max(source_dates) if source_dates else None
    holdings = load_json(HOLDINGS_PATH, {})
    prices = load_json(PRICES_PATH, {})
    price_dates = [
        str(item.get("price_updated_at") or item.get("lp_time"))[:10]
        for item in (prices.values() if isinstance(prices, dict) else [])
        if isinstance(item, dict) and (item.get("price_updated_at") or item.get("lp_time"))
    ]
    source_snapshot_dates = {
        "holdings": holdings.get("updated") if isinstance(holdings, dict) else None,
        "prices": max(price_dates) if price_dates else None,
        "daily_kbar": source_updated_at,
        "signals": (load_json(SIGNALS_PATH, {}) or {}).get("updatedAt"),
        "fundflow": (load_json(FUNDFLOW_PATH, {}) or {}).get("updated"),
    }

    return {
        "schema_v": 3,
        "runtime_version": "two-stage-hk-trading-engine-v2-finance-terms",
        "updated_at": built_at,
        "built_at": built_at,
        "source_updated_at": source_updated_at,
        "source": "CCASS + observed price snapshots + Tencent observed daily K-line",
        "data_kind": "derived_rule_output",
        "is_observed": False,
        "input_data_kind": "observed_market_and_ccass_data",
        "source_snapshot_dates": source_snapshot_dates,
        "universe_count": stage1["universe_count"],
        "candidate_count": len(candidates),
        "analyzed_count": len([symbol for symbol in by_symbol if symbol.endswith(".HK")]),
        "scope_count": len(by_symbol),
        "momentum_count": len(momentum_rows),
        "stage1": stage1,
        "errors": failures,
        "summary": {
            "setup_counts": {key: len(value) for key, value in groups.items()},
            "top_momentum_symbol": momentum_rows[0]["symbol"] if momentum_rows else None,
            "error_count": len(failures),
        },
        "by_symbol": by_symbol,
        "groups": groups,
        "momentum_rank": momentum_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the real-data two-stage HK trading engine")
    parser.add_argument("--candidate-count", type=int, default=DEFAULT_CANDIDATES)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--cache-max-age-hours", type=float, default=18)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    engine = build_engine(
        candidate_count=max(30, args.candidate_count),
        workers=max(1, args.workers),
        cache_max_age_hours=max(0, args.cache_max_age_hours),
        offline=args.offline,
    )
    OUT_PATH.write_text(json.dumps(engine, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        f"wrote {OUT_PATH}: universe={engine['universe_count']} candidates={engine['candidate_count']} "
        f"analyzed={engine['analyzed_count']} errors={len(engine['errors'])} momentum={engine['momentum_count']}"
    )
    minimum = max(20, int(engine["candidate_count"] * 0.8))
    return 0 if engine["analyzed_count"] >= minimum else 2


if __name__ == "__main__":
    raise SystemExit(main())
