#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_events_v2.py — 配股供股啟動雷達 數據管線

現代兼容版：
  - 仍然輸出 docs/ccass_events.json，畀 ccass-warroom / Telegram workflow 用
  - 只用 TradingView / tvdatafeed，唔再落 legacy quote fallback
  - CCASS 資料改用 ccass/holdings.db

跑法:
  TV_USER=xxx TV_PASS=xxx python build_events_v2.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
WATCHLIST = BASE / "events_watchlist.json"
CCASS_DB = BASE / "ccass" / "holdings.db"
OUTPUT = BASE / "docs" / "ccass_events.json"

POC_BARS = 500       # ~2 years daily bars
POC_BINS = 60
SERIES_DAYS = 20
IPO_BARS = 5000      # as much as possible for IPO open

_tv = None


def tv():
    global _tv
    if _tv is None:
        from tvDatafeed import TvDatafeed

        u = os.environ.get("TV_USER")
        p = os.environ.get("TV_PASS")
        _tv = TvDatafeed(u, p) if u else TvDatafeed()
        print(f"TV 連線: {'登入 '+u if u else '匿名模式'}")
    return _tv


def fetch_tv(code: str, n_bars: int) -> pd.DataFrame:
    from tvDatafeed import Interval

    sym = str(int(code))
    df = tv().get_hist(symbol=sym, exchange="HKEX", interval=Interval.in_daily, n_bars=n_bars)
    if df is None or df.empty:
        raise RuntimeError("TV 無數據")
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })
    return df[["Open", "High", "Low", "Close", "Volume"]]


def fetch(code: str, n_bars: int) -> tuple[pd.DataFrame, str]:
    try:
        return fetch_tv(code, n_bars), "TV"
    except Exception as e:
        raise RuntimeError(f"{code} TV 失敗 ({e})")


def year_open(df: pd.DataFrame) -> float:
    y = datetime.now().year
    cur = df[df.index.year == y]
    if cur.empty:
        raise RuntimeError("本年度無交易數據")
    return float(cur.iloc[0]["Open"])


def long_term_poc(df: pd.DataFrame) -> float:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"].fillna(0)
    if vol.sum() == 0:
        return float(tp.median())
    profile = vol.groupby(pd.cut(tp, bins=POC_BINS), observed=True).sum()
    top = profile.idxmax()
    return float((top.left + top.right) / 2)


def ipo_open(code: str) -> float:
    """攞第一支 bar 嘅 Open."""
    df, src = fetch(code, IPO_BARS)
    v = float(df.iloc[0]["Open"])
    print(f"  IPO開價({src}, 首bar {df.index[0].date()}): {v}")
    return v


def load_ccass(code: str) -> dict:
    if not CCASS_DB.exists():
        return {"trend": 0.0, "top": []}

    try:
        con = sqlite3.connect(CCASS_DB)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        latest_date = cur.execute(
            "SELECT MAX(trade_date) FROM ccass_holdings WHERE stock_code=?",
            (code,),
        ).fetchone()[0]
        if not latest_date:
            return {"trend": 0.0, "top": []}

        latest_rows = cur.execute(
            """
            SELECT participant_id, participant_name, pct_of_issued
            FROM ccass_holdings
            WHERE stock_code=? AND trade_date=?
            ORDER BY pct_of_issued DESC
            LIMIT 5
            """,
            (code, latest_date),
        ).fetchall()

        old_date = cur.execute(
            """
            SELECT MAX(trade_date)
            FROM ccass_holdings
            WHERE stock_code=? AND trade_date <= date(?, '-30 day')
            """,
            (code, latest_date),
        ).fetchone()[0]

        old = {}
        if old_date:
            old_rows = cur.execute(
                """
                SELECT participant_id, participant_name, pct_of_issued
                FROM ccass_holdings
                WHERE stock_code=? AND trade_date=?
                """,
                (code, old_date),
            ).fetchall()
            old = {
                f"{(r['participant_id'] or '').strip()} {(r['participant_name'] or '').strip()}".strip(): float(r["pct_of_issued"] or 0.0)
                for r in old_rows
            }

        latest = []
        for r in latest_rows:
            name = f"{(r['participant_id'] or '').strip()} {(r['participant_name'] or '').strip()}".strip()
            pct = float(r["pct_of_issued"] or 0.0)
            latest.append((name, pct))

        top = [[n, round(p, 1), round(p - old.get(n, p), 1)] for n, p in latest]
        trend = round(sum(p for _, p in latest) - sum(old.get(n, p) for n, p in latest), 1)
        con.close()
        return {"trend": trend, "top": top}
    except Exception as e:
        print(f"  ⚠ CCASS {code}: {e}", file=sys.stderr)
        return {"trend": 0.0, "top": []}


def build_one(ev: dict) -> dict:
    code = str(ev["code"]).zfill(4)
    print(f"▶ {code} {ev.get('name', '')}")
    df, src = fetch(code, POC_BARS)

    levels = {
        "yearOpen": ev.get("year_open_override") or round(year_open(df), 3),
        "ipoOpen": ev.get("ipo_open_override") or round(ipo_open(code), 3),
        "ltPOC": ev.get("poc_override") or round(long_term_poc(df), 3),
    }
    last2 = df.tail(2)
    px = {
        "last": round(float(last2.iloc[-1]["Close"]), 3),
        "open": round(float(last2.iloc[-1]["Open"]), 3),
        "prevClose": round(float(last2.iloc[-2]["Close"]), 3),
    }
    tail = df.tail(SERIES_DAYS)
    series = [round(float(v), 3) for v in tail["Close"]]
    ev_idx = None
    try:
        ev_d = pd.Timestamp(ev["date"])
        if tail.index.tz is not None:
            ev_d = ev_d.tz_localize(tail.index.tz)
        ev_idx = int(max(0, (tail.index <= ev_d).sum() - 1))
    except Exception:
        pass

    return {
        "code": code,
        "name": ev.get("name", ""),
        "event": {
            "type": ev["type"],
            "date": ev["date"],
            "discount": ev.get("discount", 0.0),
            "dilution": ev.get("dilution", 0.0),
            "agent": ev.get("agent", ""),
        },
        "levels": levels,
        "px": px,
        "ccass": load_ccass(code),
        "series": series,
        "evIdx": ev_idx,
        "src": src,
        "asof": date.today().isoformat(),
    }


def main() -> None:
    if not WATCHLIST.exists():
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text("[]", encoding="utf-8")
        print("⚠ events_watchlist.json not found, wrote empty docs/ccass_events.json")
        return

    events = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    out = []
    fails = []

    for ev in events:
        for attempt in range(3):
            try:
                out.append(build_one(ev))
                break
            except Exception as e:
                print(f"  ✗ {ev['code']} 第{attempt + 1}次: {e}", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        else:
            fails.append(ev["code"])
        time.sleep(1)  # 對 TV 溫柔啲

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ 出咗 {len(out)} 隻 → {OUTPUT}" + (f" | 失敗: {fails}" if fails else ""))


if __name__ == "__main__":
    main()
