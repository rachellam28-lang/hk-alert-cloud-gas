"""
Bullish Fair Value Gap (FVG) Scanner
Detects fresh bullish FVGs on daily / weekly / monthly timeframes for HK stocks.

Bullish FVG definition:
  Three consecutive candles where candle[i-2].High < candle[i].Low.
  The gap zone = (candle[i-2].High, candle[i].Low).
  A FVG is "fresh" if no subsequent candle's Low has traded below the gap's midpoint.
  A FVG is "retesting" if current price is inside or just above (≤ NEAR_PCT) the zone.

Weekly FVG: uses emit_alert() with chart + year-open filter (same as POC alerts).
Daily / Monthly FVG: text-only Telegram alerts.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

# ── Config ────────────────────────────────────────────────────────────────────
NEAR_PCT     = float(os.getenv("FVG_NEAR_PCT", "0.01"))   # 1% above FVG top = "near" (was 3%, too noisy)
RATE_SLEEP   = float(os.getenv("FVG_SLEEP", "0.15"))
MAX_TG_ALERTS = int(os.getenv("FVG_MAX_TG", "10"))         # max Telegram alerts per run (rest → JSON only)

# ── Ticker universes ──────────────────────────────────────────────────────────
HK_TICKERS = [
    "0005.HK","0011.HK","0017.HK","0027.HK","0066.HK","0083.HK","0101.HK","0175.HK",
    "0241.HK","0267.HK","0288.HK","0291.HK","0316.HK","0322.HK","0388.HK","0669.HK",
    "0700.HK","0762.HK","0823.HK","0857.HK","0868.HK","0881.HK","0883.HK","0909.HK",
    "0914.HK","0916.HK","0939.HK","0941.HK","0960.HK","0968.HK","0992.HK","1038.HK",
    "1044.HK","1093.HK","1109.HK","1113.HK","1177.HK","1209.HK","1211.HK","1299.HK",
    "1378.HK","1398.HK","1810.HK","1876.HK","1928.HK","1929.HK","2007.HK","2018.HK",
    "2020.HK","2269.HK","2313.HK","2318.HK","2319.HK","2331.HK","2382.HK","2388.HK",
    "2628.HK","2688.HK","2899.HK","3328.HK","3690.HK","3988.HK","6098.HK","6862.HK",
    "6969.HK","9618.HK","9633.HK","9698.HK","9888.HK","9961.HK","9988.HK","9999.HK",
]

_TF_PARAMS = {
    "日線": ("3mo",  "1d"),
    "周線": ("2y",   "1wk"),
    "月線": ("5y",   "1mo"),
}

_TF_LABEL = {"日線": "D", "周線": "W", "月線": "M"}

# ── Core FVG logic ────────────────────────────────────────────────────────────

def _find_fresh_bullish_fvgs(df: pd.DataFrame) -> list[dict]:
    """Return list of unfilled bullish FVGs in OHLC dataframe."""
    if len(df) < 3:
        return []

    # Flatten MultiIndex columns if batch download
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    dates  = df.index

    fvgs = []
    for i in range(2, len(df)):
        gap_low  = float(highs[i - 2])   # c1 high
        gap_high = float(lows[i])         # c3 low

        if gap_low >= gap_high:
            continue  # no gap

        # A FVG is filled if any subsequent Low trades below (gap_low + gap_high) / 2
        midpoint = (gap_low + gap_high) / 2
        filled = any(float(lows[j]) < midpoint for j in range(i + 1, len(df)))
        if filled:
            continue

        fvgs.append({
            "date":      str(dates[i].date()),
            "gap_low":   round(gap_low, 6),
            "gap_high":  round(gap_high, 6),
            "current":   round(float(closes[-1]), 6),
        })

    return fvgs


def _proximity(fvg: dict) -> str | None:
    """
    Returns 'in' if price is inside FVG, 'near' if within NEAR_PCT above FVG,
    None otherwise.
    """
    p = fvg["current"]
    lo, hi = fvg["gap_low"], fvg["gap_high"]
    if lo <= p <= hi:
        return "in"
    if hi < p <= hi * (1 + NEAR_PCT):
        return "near"
    return None


def scan_ticker(ticker: str, name: str = "", market: str = "HK") -> list[dict]:
    alerts = []
    for tf, (period, interval) in _TF_PARAMS.items():
        try:
            time.sleep(RATE_SLEEP)
            df = yf.download(ticker, period=period, interval=interval,
                             progress=False, auto_adjust=True, multi_level_index=False)
            if df is None or df.empty or len(df) < 3:
                continue
            # Only care about FVGs formed on the LATEST candle
            last_date = str(df.index[-1].date())
            fvgs = _find_fresh_bullish_fvgs(df)
            for fvg in fvgs:
                if fvg["date"] != last_date:
                    continue  # skip old FVGs
                prox = _proximity(fvg)
                if prox:
                    alerts.append({
                        "ticker":    ticker,
                        "name":      name or ticker,
                        "market":    market,
                        "timeframe": tf,
                        "tf_short":  _TF_LABEL[tf],
                        "gap_low":   fvg["gap_low"],
                        "gap_high":  fvg["gap_high"],
                        "current":   fvg["current"],
                        "fvg_date":  fvg["date"],
                        "status":    prox,
                    })
        except Exception as e:
            print(f"[FVG] {ticker} {tf}: {e}")
    return alerts


# ── Name lookup ───────────────────────────────────────────────────────────────

def _build_name_map(tickers: list[str]) -> dict[str, str]:
    """Batch-fetch short names via yfinance fast_info (best-effort)."""
    names: dict[str, str] = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info
            names[t] = getattr(info, "display_name", None) or t
        except Exception:
            names[t] = t
        time.sleep(0.05)
    return names


# ── Telegram + GAS ────────────────────────────────────────────────────────────

def _tv_url(alert: dict) -> str:
    sym = alert["ticker"].replace(".HK", "")
    return f"https://www.tradingview.com/chart/?symbol=HKEX%3A{sym}"


def _emit_telegram(alert: dict) -> None:
    """Simple text-only Telegram alert (日線 Bullish FVG)."""
    sys.path.insert(0, os.path.dirname(__file__))
    from hk_cloud_scanner import send_telegram_alert, build_inline_keyboard_

    status_icon = "🎯 FVG內" if alert["status"] == "in" else "⬇️接近FVG"
    pct_from_top = round((alert["current"] - alert["gap_high"]) / alert["gap_high"] * 100, 2)
    dist_str = (f"{pct_from_top:.2f}%上方" if alert["status"] == "near" else "在FVG內")

    caption = (
        f"📐 🇭🇰 <b>{alert['ticker']}</b> {alert['timeframe']} {status_icon}\n"
        f"FVG {alert['gap_low']} – {alert['gap_high']}  現價 {alert['current']} ({dist_str})"
    )

    tv_url = _tv_url(alert)
    send_telegram_alert(caption, None, reply_markup=build_inline_keyboard_([
        ("📊 走勢圖", tv_url),
    ]))
    time.sleep(0.5)


def _emit_weekly_fvg(alert: dict) -> None:
    """Weekly FVG alert with chart + year-open filter (same as POC alerts).

    Downloads daily OHLCV data, renders a chart with the FVG zone highlighted,
    and uses emit_alert() which automatically applies the year-open filter — if
    the stock is below its current-year first-day open, the Telegram alert is
    suppressed (but still posted to GAS).
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from hk_cloud_scanner import (
        render_chart, build_inline_keyboard_, emit_alert,
        get_daily_history, normalize_yfinance_df,
    )

    ticker = alert["ticker"]   # e.g. "0700.HK"
    code = ticker.replace(".HK", "").zfill(5)
    name = alert.get("name") or code

    # ── Download daily price history for chart + year-open check ──
    df = get_daily_history(code, "1y")
    if df.empty:
        # Fallback: try yfinance directly
        try:
            raw = yf.download(ticker, period="1y", interval="1d",
                              progress=False, auto_adjust=False, threads=False)
            df = normalize_yfinance_df(raw)
        except Exception:
            print(f"[FVG weekly] no daily data for {ticker}, fallback to text-only")
            _emit_telegram(alert)
            return

    if df.empty:
        _emit_telegram(alert)
        return

    # ── Build caption ──
    status_icon = "🎯 周線+月線FVG內" if alert["status"] == "in" else "⬇️接近周線+月線FVG"
    pct_from_top = round((alert["current"] - alert["gap_high"]) / alert["gap_high"] * 100, 2)
    dist_str = (f"{pct_from_top:.2f}%上方" if alert["status"] == "near" else "在FVG內")

    caption = (
        f"📐 🇭🇰 <b>{code} {name}</b> 周線+月線 {status_icon}\n"
        f"FVG {alert['gap_low']:.3f} – {alert['gap_high']:.3f}  現價 {alert['current']:.3f} ({dist_str})"
    )

    # ── Render chart with FVG zone ──
    tv_url = _tv_url(alert)
    levels = [
        ("FVG頂", alert["gap_high"], "#22c55e"),
        ("FVG底", alert["gap_low"], "#ef4444"),
    ]
    chart_path = render_chart(df, code, name,
                               f"周線+月線FVG · {alert['fvg_date']}",
                               levels=levels,
                               lookback_days=180)

    # ── Build payload + emit (year-open filter applied automatically) ──
    payload: dict[str, Any] = {
        "source": "fvg_scanner",
        "category": "tech",
        "code": code,
        "name": name,
        "signal": f"周線+月線Bullish FVG ({alert['status']})",
        "timeframe": "周線+月線",
        "price": alert["current"],
        "market": "HK",
        "chart_url": tv_url,
        "message": f"周線+月線FVG {alert['gap_low']:.3f}–{alert['gap_high']:.3f} 現價{alert['current']:.3f} ({dist_str})",
        "tags": "FVG,周線+月線",
        "priority": 2,
        "raw": json.dumps(alert, ensure_ascii=False, default=str),
    }

    kb = build_inline_keyboard_([("📊 走勢圖", tv_url)])
    emit_alert(payload, caption, chart_path, reply_markup=kb, df=df)
    time.sleep(0.5)


def _post_to_gas(alert: dict) -> None:
    sys.path.insert(0, os.path.dirname(__file__))
    from hk_cloud_scanner import post_gas_alert

    code = alert["ticker"].replace(".HK", "").zfill(5)

    dist_str = (
        f"{(alert['current'] - alert['gap_high']) / alert['gap_high'] * 100:.2f}%上方"
        if alert["status"] == "near" else "在FVG內"
    )

    post_gas_alert({
        "source":    "fvg_scanner",
        "category":  "tech",
        "code":      code,
        "name":      alert.get("name") or code,
        "signal":    f"日線Bullish FVG {alert['timeframe']}",
        "timeframe": alert["timeframe"],
        "price":     alert["current"],
        "market":    alert["market"],
        "chart_url": _tv_url(alert),
        "message":   f"FVG {alert['gap_low']}–{alert['gap_high']} 現價{alert['current']} ({dist_str})",
        "tags":      "FVG",
    })


# ── JSON export ───────────────────────────────────────────────────────────────

def _export_json(alerts: list[dict]) -> None:
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count":   len(alerts),
        "alerts":  alerts,
    }
    path = os.path.join(os.path.dirname(__file__), "..", "fvg.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[FVG] exported fvg.json  ({len(alerts)} alerts)")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_fvg_scan(market: str = "hk") -> None:
    """market: 'hk' | 'us' | 'both' (default: 'hk' for cron)"""
    print(f"[FVG] scan market={market}  near_pct={NEAR_PCT:.0%}")

    tasks: list[tuple[str, str, str]] = []  # (ticker, name, market)
    if market in ("hk", "both"):
        tasks += [(t, "", "HK") for t in HK_TICKERS]
    if market in ("us", "both"):
        tasks += [(t, "", "US") for t in []]  # US FVG disabled — use POC breakout instead

    all_alerts: list[dict] = []
    tg_sent = 0
    for i, (ticker, name, mkt) in enumerate(tasks, 1):
        if i % 20 == 0:
            print(f"[FVG] progress {i}/{len(tasks)}")
        alerts = scan_ticker(ticker, name, mkt)
        for a in alerts:
            print(f"[FVG] ALERT {a['ticker']} {a['timeframe']} {a['status']}  "
                  f"FVG={a['gap_low']:.2f}–{a['gap_high']:.2f}  now={a['current']:.2f}")

            # Always post to GAS
            try:
                _post_to_gas(a)
            except Exception as e:
                print(f"[FVG] GAS error {ticker}: {e}")

            # ── Telegram: rules differ by timeframe ──
            is_weekly = a["timeframe"] == "周線" and a["market"] == "HK"
            is_daily_in = a["status"] == "in"
            is_daily_near = a["status"] == "near" and a["timeframe"] == "日線"
            is_monthly_in = a["status"] == "in" and a["timeframe"] == "月線"

            send_tg = is_weekly or is_daily_in or is_daily_near or is_monthly_in

            if send_tg and tg_sent < MAX_TG_ALERTS:
                try:
                    if is_weekly:
                        _emit_weekly_fvg(a)   # chart + year-open filter
                    else:
                        _emit_telegram(a)      # text-only
                    tg_sent += 1
                except Exception as e:
                    print(f"[FVG] telegram error {ticker}: {e}")
        all_alerts.extend(alerts)

    _export_json(all_alerts)
    print(f"[FVG] done  total_alerts={len(all_alerts)}  tg_sent={tg_sent}")


if __name__ == "__main__":
    market = sys.argv[1] if len(sys.argv) > 1 else "hk"
    run_fvg_scan(market)
