#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_events_v2.py — 配股供股啟動雷達 數據管線 (TradingView 主源 + yfinance fallback)
數據優先序: TradingView (你 Ultimate 帳戶, 交易所授權數據) → 失敗先用 yfinance
跑法:
  pip install pandas yfinance
  pip install git+https://github.com/rongardF/tvdatafeed.git
  TV_USER=xxx TV_PASS=xxx python build_events_v2.py
唔設 TV_USER 就行匿名模式 (bar 數有限制, 計2年POC通常都夠)
"""
import json, os, sqlite3, sys, time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

WATCHLIST   = Path("events_watchlist.json")
CCASS_DB    = Path("ccass.db")
OUTPUT      = Path("docs/ccass_events.json")
POC_BARS    = 500          # ~2年日線
POC_BINS    = 60
SERIES_DAYS = 20
IPO_BARS    = 5000         # 拉到盡搵上市首日 (Ultimate 登入先攞到咁多)

# ── 數據層: TradingView 主源 ──────────────────────────
_tv = None
def tv():
    global _tv
    if _tv is None:
        from tvDatafeed import TvDatafeed
        u, p = os.environ.get("TV_USER"), os.environ.get("TV_PASS")
        _tv = TvDatafeed(u, p) if u else TvDatafeed()
        print(f"TV 連線: {'登入 '+u if u else '匿名模式'}")
    return _tv

def fetch_tv(code: str, n_bars: int) -> pd.DataFrame:
    from tvDatafeed import Interval
    sym = str(int(code))                       # TV 港股冇前置零: 0700 → "700"
    df = tv().get_hist(symbol=sym, exchange="HKEX",
                       interval=Interval.in_daily, n_bars=n_bars)
    if df is None or df.empty:
        raise RuntimeError("TV 無數據")
    df = df.rename(columns={"open":"Open","high":"High","low":"Low",
                            "close":"Close","volume":"Volume"})
    return df[["Open","High","Low","Close","Volume"]]

def fetch_yf(code: str, n_bars: int) -> pd.DataFrame:
    import yfinance as yf
    period = "max" if n_bars >= IPO_BARS else f"{max(1, round(n_bars/250))}y"
    df = yf.Ticker(f"{int(code):04d}.HK").history(period=period, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("yahoo 無數據")
    return df

def fetch(code: str, n_bars: int) -> tuple[pd.DataFrame, str]:
    try:
        return fetch_tv(code, n_bars), "TV"
    except Exception as e:
        print(f"  ⚠ {code} TV 失敗 ({e}), fallback yfinance", file=sys.stderr)
        return fetch_yf(code, n_bars), "YF"

# ── 三重關卡計算 ─────────────────────────────────────
def year_open(df: pd.DataFrame) -> float:
    y = datetime.now().year
    cur = df[df.index.year == y]
    if cur.empty:
        raise RuntimeError("本年度無交易數據")
    return float(cur.iloc[0]["Open"])

def long_term_poc(df: pd.DataFrame) -> float:
    tp  = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"].fillna(0)
    if vol.sum() == 0:
        return float(tp.median())
    profile = vol.groupby(pd.cut(tp, bins=POC_BINS), observed=True).sum()
    top = profile.idxmax()
    return float((top.left + top.right) / 2)

def ipo_open(code: str) -> float:
    """拉最長歷史攞第一支 bar 嘅 Open。
    注意: 經歷合股嘅股, TV/Yahoo 都會回調歷史價 → 用 watchlist 嘅 ipo_open_override 鎖死先準。"""
    df, src = fetch(code, IPO_BARS)
    v = float(df.iloc[0]["Open"])
    print(f"  IPO開價({src}, 首bar {df.index[0].date()}): {v}")
    return v

# ── CCASS ────────────────────────────────────────────
def load_ccass(code: str):
    if not CCASS_DB.exists():
        return {"trend": 0.0, "top": []}
    try:
        con = sqlite3.connect(CCASS_DB); cur = con.cursor()
        cur.execute("""
            SELECT participant_id || ' ' || participant_name, pct
            FROM daily_snapshot
            WHERE stock_code=? AND snap_date=(SELECT MAX(snap_date) FROM daily_snapshot WHERE stock_code=?)
            ORDER BY pct DESC LIMIT 5""", (code, code))
        latest = cur.fetchall()
        cur.execute("""
            SELECT participant_id || ' ' || participant_name, pct
            FROM daily_snapshot
            WHERE stock_code=? AND snap_date=(
                SELECT MAX(snap_date) FROM daily_snapshot
                WHERE stock_code=? AND snap_date<=date('now','-30 day'))""", (code, code))
        old = dict(cur.fetchall()); con.close()
        top = [[n, round(p,1), round(p - old.get(n,p),1)] for n,p in latest]
        trend = round(sum(p for _,p in latest) - sum(old.get(n,p) for n,p in latest), 1)
        return {"trend": trend, "top": top}
    except Exception as e:
        print(f"  ⚠ CCASS {code}: {e}", file=sys.stderr)
        return {"trend": 0.0, "top": []}

# ── 組裝 ─────────────────────────────────────────────
def build_one(ev: dict) -> dict:
    code = str(ev["code"]).zfill(4)
    print(f"▶ {code} {ev.get('name','')}")
    df, src = fetch(code, POC_BARS)

    levels = {
        "yearOpen": ev.get("year_open_override") or round(year_open(df), 3),
        "ipoOpen":  ev.get("ipo_open_override") or round(ipo_open(code), 3),
        "ltPOC":    ev.get("poc_override") or round(long_term_poc(df), 3),
    }
    last2 = df.tail(2)
    px = {
        "last":      round(float(last2.iloc[-1]["Close"]), 3),
        "open":      round(float(last2.iloc[-1]["Open"]), 3),
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
        "code": code, "name": ev.get("name",""),
        "event": {"type": ev["type"], "date": ev["date"],
                  "discount": ev.get("discount",0.0), "dilution": ev.get("dilution",0.0),
                  "agent": ev.get("agent","")},
        "levels": levels, "px": px, "ccass": load_ccass(code),
        "series": series, "evIdx": ev_idx,
        "src": src, "asof": date.today().isoformat(),
    }

def main():
    events = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    out, fails = [], []
    for ev in events:
        for attempt in range(3):
            try:
                out.append(build_one(ev)); break
            except Exception as e:
                print(f"  ✗ {ev['code']} 第{attempt+1}次: {e}", file=sys.stderr)
                time.sleep(3*(attempt+1))
        else:
            fails.append(ev["code"])
        time.sleep(1)   # 對 TV websocket 溫柔啲
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ 出咗 {len(out)} 隻 → {OUTPUT}" + (f" | 失敗: {fails}" if fails else ""))

if __name__ == "__main__":
    main()
