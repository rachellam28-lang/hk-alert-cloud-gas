#!/usr/bin/env python
"""Backfill technical signals for stocks with corporate announcements.

Downloads 1yr price history per stock, detects:
  - 向上跳空缺口 (gap up: today's low > yesterday's high)
  - 向上FVG (3-candle bullish fair value gap)

Only keeps signals within 30 days AFTER each stock's earliest announcement date.
Appends to history.json (deduplicates by code+date+type).
"""
import json, os, sys, time
from datetime import datetime, timedelta
from collections import defaultdict

import yfinance as yf
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SCRIPT_DIR)  # parent of scripts/
DATA = os.path.join(PROJ, "data")
ANN_PATH = os.path.join(DATA, "announcements.json")
HIST_PATH = os.path.join(DATA, "history.json")

SIGNAL_WINDOW_DAYS = 60  # detect signals within 60 days after earliest announcement
MIN_GAP_PCT = 1.5  # minimum gap up percentage
BATCH_SIZE = 20
SLEEP = 0.3


def detect_gaps(df: pd.DataFrame) -> list[dict]:
    """Detect upward gaps: today's low > yesterday's high. Expects lowercase columns."""
    if len(df) < 2:
        return []
    gaps = []
    for i in range(1, len(df)):
        prev_high = df.iloc[i - 1]["high"]
        curr_low = df.iloc[i]["low"]
        curr_open = df.iloc[i]["open"]
        if curr_low > prev_high:
            gap_pct = (curr_low / prev_high - 1) * 100
            if gap_pct >= MIN_GAP_PCT:
                date_str = df.index[i].strftime("%Y-%m-%d")
                gaps.append({
                    "type": "向上跳空缺口",
                    "fvg_pct": round(gap_pct, 2),
                    "gap_low": round(float(curr_low), 3),
                    "gap_high": round(float(prev_high), 3),
                    "current": round(float(curr_open), 3),
                    "date": date_str,
                })
    return gaps


def detect_fvg(df: pd.DataFrame) -> list[dict]:
    """Detect bullish FVG: candle[i-2].High < candle[i].Low. Expects lowercase columns."""
    if len(df) < 3:
        return []
    fvgs = []
    for i in range(2, len(df)):
        h2 = df.iloc[i - 2]["high"]
        l0 = df.iloc[i]["low"]
        if h2 < l0:
            gap_pct = (l0 / h2 - 1) * 100
            if gap_pct >= MIN_GAP_PCT:
                date_str = df.index[i].strftime("%Y-%m-%d")
                fvgs.append({
                    "type": "向上FVG",
                    "fvg_pct": round(gap_pct, 2),
                    "gap_low": round(float(h2), 3),
                    "gap_high": round(float(l0), 3),
                    "current": round(float(df.iloc[i]["close"]), 3),
                    "date": date_str,
                })
    return fvgs


def code_to_yahoo(code: str) -> str:
    """Convert HK stock code to Yahoo Finance ticker."""
    c = code.lstrip("0") or "0"
    return f"{c}.HK"


def main():
    print("Loading announcements...")
    with open(ANN_PATH, "r") as f:
        announcements = json.load(f)

    # Get unique stocks and their earliest announcement date
    stock_dates: dict[str, str] = {}
    stock_names: dict[str, str] = {}
    for a in announcements:
        code = str(a.get("code", "")).zfill(5)
        date = a.get("date", "")
        if not code or not date:
            continue
        if code not in stock_dates or date < stock_dates[code]:
            stock_dates[code] = date
            stock_names[code] = a.get("name", "")

    codes = sorted(stock_dates.keys())
    print(f"Stocks to backfill: {len(codes)}")
    print(f"Date range: {min(stock_dates.values())} to {max(stock_dates.values())}")

    # Load existing history
    if os.path.exists(HIST_PATH):
        with open(HIST_PATH, "r") as f:
            history = json.load(f)
    else:
        history = {"ok": True, "total": 0, "days": []}

    # Build existing signal set for dedup
    existing = set()
    signal_days: dict[str, list] = defaultdict(list)
    for day in history.get("days", []):
        for alert in day.get("alerts", []):
            code = str(alert.get("code", "")).zfill(5)
            sig = alert.get("signal", "")
            st = sig.get("type", "") if isinstance(sig, dict) else str(sig)
            sd = sig.get("date", "") if isinstance(sig, dict) else day.get("date", "")
            existing.add((code, sd, st))

    new_signals: dict[str, list] = defaultdict(list)  # date -> [alerts]
    total_signals = 0
    processed = 0
    failed = 0

    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i : i + BATCH_SIZE]
        tickers = [code_to_yahoo(c) for c in batch]

        try:
            data = yf.download(tickers, period="6mo", progress=False, threads=True, group_by="ticker")
        except Exception as e:
            print(f"  Batch {i}-{i+len(batch)} download failed: {e}")
            failed += len(batch)
            continue

        for j, code in enumerate(batch):
            processed += 1
            ticker = tickers[j]
            ann_date_str = stock_dates[code]
            try:
                ann_date = datetime.strptime(ann_date_str, "%Y-%m-%d")
            except ValueError:
                continue
            cutoff = ann_date + timedelta(days=SIGNAL_WINDOW_DAYS)

            # Extract this stock's dataframe
            if len(batch) == 1:
                df = data.copy()
            elif isinstance(data.columns, pd.MultiIndex):
                try:
                    df = data.xs(ticker, axis=1, level=0).copy()
                except KeyError:
                    failed += 1
                    continue
            else:
                # Single ticker returned flat columns — but batch>1, skip
                failed += 1
                continue

            if df is None or df.empty:
                continue

            # Normalize column names
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna(subset=["open", "high", "low", "close"])
            if len(df) < 3:
                continue

            # Detect signals
            gaps = detect_gaps(df)
            fvgs = detect_fvg(df)

            count = 0
            for sig in gaps + fvgs:
                sig_date_str = sig["date"]
                try:
                    sig_date = datetime.strptime(sig_date_str, "%Y-%m-%d")
                except ValueError:
                    continue

                # Only keep signals after announcement date
                if sig_date < ann_date or sig_date > cutoff:
                    continue

                dedup_key = (code, sig_date_str, sig["type"])
                if dedup_key in existing:
                    continue
                existing.add(dedup_key)

                new_signals[sig_date_str].append({
                    "code": code,
                    "name": stock_names.get(code, ""),
                    "signal": sig,
                    "corp_type": "",
                })
                count += 1
                total_signals += 1

            if count > 0:
                print(f"  [{processed}/{len(codes)}] {code} {stock_names.get(code,'')[:20]}: {count} signals")

        time.sleep(SLEEP)

    print(f"\nProcessed: {processed}, Failed: {failed}, New signals: {total_signals}")

    if total_signals == 0:
        print("No new signals found.")
        return

    # Merge new signals into history
    day_map = {d["date"]: d for d in history.get("days", [])}
    for date_str, alerts in sorted(new_signals.items()):
        if date_str in day_map:
            day_map[date_str]["alerts"].extend(alerts)
        else:
            day_map[date_str] = {"date": date_str, "alerts": alerts}

    history["days"] = sorted(day_map.values(), key=lambda d: d["date"], reverse=True)
    history["total"] = sum(len(d["alerts"]) for d in history["days"])
    history["ok"] = True

    with open(HIST_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"Saved {history['total']} total signals across {len(history['days'])} days")


if __name__ == "__main__":
    main()
