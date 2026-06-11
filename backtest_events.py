#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_events.py — 配股供股 × 三重突破 事件研究回測
════════════════════════════════════════════════════════
問題: 深折讓配售/供股後,三重突破訊號觸發,之後 T+5/20/60 報酬分佈係點?
       邊套出場規則先留得住個 edge?

訊號 (修正版, 無前視):
  S1 破年開   : close > 觸發日所屬年度首個交易日 Open
  S2 破IPO開價: close > 上市首日 Open
  S3 跳空破POC: 跳空 >= max(5%, 1×ATR20/prevClose) 且 close > POC(只用觸發日之前數據計)
                且 當日成交量 >= 3× 20日均量
評級: 3中=S, 2中=A, 1中=B
觸發窗: 事件日 T-30 至 T+60 個交易日,取第一個 grade>=A 嘅日子做入場(觸發日收市價)

出場規則模擬 (由觸發日起):
  HOLD60    : 持有到 T+60
  GAP_STOP  : 收市跌穿觸發日最低價即走 (啟動缺口失守)
  TIME40    : T+40 硬性時間止損
  VOL_CLIMAX: 爆量滯漲 (量>=5×均量 且 收低於開) 翌日開市走
  COMBO     : 以上三者最早觸發

跑法:
  pip install pandas numpy yfinance
  pip install git+https://github.com/rongardF/tvdatafeed.git
  TV_USER=xxx TV_PASS=xxx python backtest_events.py
輸出: backtest_results.csv (逐事件) + backtest_report.txt (統計總結)
════════════════════════════════════════════════════════
"""
import json, os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

EVENTS_FILE = Path("events_history.json")
OUT_CSV     = Path("backtest_results.csv")
OUT_RPT     = Path("backtest_report.txt")
PRE_DAYS    = 30      # 事件前觸發窗
POST_DAYS   = 60      # 事件後觸發窗 / 持有期
POC_BINS    = 60
POC_LOOKBACK= 500     # POC 回看 bar 數 (~2年)
GAP_MIN     = 0.05    # 跳空門檻下限 5%
VOL_X       = 3.0     # 突破日量能倍數
HIST_BARS   = 5000

# ── 數據層 (TV 主源 / YF fallback,同 build_events_v2) ──
_tv = None
def tv():
    global _tv
    if _tv is None:
        from tvDatafeed import TvDatafeed
        u, p = os.environ.get("TV_USER"), os.environ.get("TV_PASS")
        _tv = TvDatafeed(u, p) if u else TvDatafeed()
    return _tv

def fetch(code: str) -> pd.DataFrame:
    """成段歷史拉一次落 cache,回測逐日切片用"""
    cache = Path(f".cache/{code}.parquet")
    if cache.exists():
        return pd.read_parquet(cache)
    df = None
    try:
        from tvDatafeed import Interval
        df = tv().get_hist(symbol=str(int(code)), exchange="HKEX",
                           interval=Interval.in_daily, n_bars=HIST_BARS)
        if df is not None and not df.empty:
            df = df.rename(columns={"open":"Open","high":"High","low":"Low",
                                    "close":"Close","volume":"Volume"})[
                                    ["Open","High","Low","Close","Volume"]]
    except Exception as e:
        print(f"  ⚠ {code} TV: {e}", file=sys.stderr)
    if df is None or df.empty:
        import yfinance as yf
        df = yf.Ticker(f"{int(code):04d}.HK").history(period="max", auto_adjust=False)
        if df is None or df.empty:
            raise RuntimeError("無數據")
        df = df[["Open","High","Low","Close","Volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated()]
    cache.parent.mkdir(exist_ok=True)
    df.to_parquet(cache)
    return df

# ── 指標 (全部只用 t 之前/當日數據,無前視) ──────────────
def poc_asof(df: pd.DataFrame, t: int) -> float:
    win = df.iloc[max(0, t - POC_LOOKBACK):t]            # 唔包觸發日
    if len(win) < 60:
        return np.nan
    tp  = (win.High + win.Low + win.Close) / 3
    vol = win.Volume.fillna(0)
    if vol.sum() == 0:
        return float(tp.median())
    prof = vol.groupby(pd.cut(tp, bins=POC_BINS), observed=True).sum()
    top = prof.idxmax()
    return float((top.left + top.right) / 2)

def signals_at(df, t, ipo_open, year_opens, atr20, vol20):
    """t = iloc 位置。回傳 (sig dict, grade)"""
    row, prev = df.iloc[t], df.iloc[t-1]
    yo = year_opens.get(df.index[t].year, np.nan)
    s1 = bool(row.Close > yo) if np.isfinite(yo) else False
    s2 = bool(row.Close > ipo_open) if np.isfinite(ipo_open) else False
    gap = row.Open / prev.Close - 1
    thr = max(GAP_MIN, (atr20.iloc[t-1] / prev.Close) if np.isfinite(atr20.iloc[t-1]) else GAP_MIN)
    poc = poc_asof(df, t)
    volok = np.isfinite(vol20.iloc[t-1]) and vol20.iloc[t-1] > 0 and row.Volume >= VOL_X * vol20.iloc[t-1]
    s3 = bool(gap >= thr and np.isfinite(poc) and row.Close > poc and volok)
    hits = s1 + s2 + s3
    grade = "S" if hits == 3 else "A" if hits == 2 else "B" if hits == 1 else "C"
    return {"s1": s1, "s2": s2, "s3": s3, "gap": gap, "poc": poc}, grade

def ret(a, b):
    return (b / a - 1) * 100 if (np.isfinite(a) and np.isfinite(b) and a > 0) else np.nan

# ── 單一事件回測 ─────────────────────────────────────
def run_event(ev: dict):
    code = str(ev["code"]).zfill(4)
    df = fetch(code)
    if len(df) < 120:
        raise RuntimeError("歷史太短")
    ipo_open = float(df.iloc[0].Open)
    year_opens = {y: float(g.iloc[0].Open) for y, g in df.groupby(df.index.year)}
    tr = pd.concat([df.High-df.Low, (df.High-df.Close.shift()).abs(),
                    (df.Low-df.Close.shift()).abs()], axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean()
    vol20 = df.Volume.rolling(20).mean()

    ev_d = pd.Timestamp(ev["date"])
    pos = df.index.searchsorted(ev_d)
    if pos >= len(df) or pos < PRE_DAYS + 21:
        raise RuntimeError("事件日超出數據範圍")

    # 觸發窗掃描: 第一個 grade ∈ {S,A}
    trig_t, trig_grade, trig_sig = None, None, None
    for t in range(max(21, pos - PRE_DAYS), min(len(df), pos + POST_DAYS)):
        sig, grade = signals_at(df, t, ipo_open, year_opens, atr20, vol20)
        if grade in ("S", "A"):
            trig_t, trig_grade, trig_sig = t, grade, sig
            break

    base = {
        "code": code, "name": ev.get("name",""), "type": ev["type"], "event_date": ev["date"],
        # 基準: 事件日收市 → T+20/T+60 (所有事件,有冇觸發都計)
        "base_r20": ret(df.iloc[pos].Close, df.iloc[min(len(df)-1, pos+20)].Close),
        "base_r60": ret(df.iloc[pos].Close, df.iloc[min(len(df)-1, pos+60)].Close),
        "triggered": trig_t is not None,
    }
    if trig_t is None:
        return base

    entry = float(df.iloc[trig_t].Close)
    trig_low = float(df.iloc[trig_t].Low)
    fwd = df.iloc[trig_t : trig_t + POST_DAYS + 1]
    if len(fwd) < 6:
        raise RuntimeError("觸發後數據不足")

    closes = fwd.Close.values
    base.update({
        "trigger_date": str(df.index[trig_t].date()),
        "grade": trig_grade,
        "days_from_event": int(trig_t - pos),
        "s1_yearopen": trig_sig["s1"], "s2_ipoopen": trig_sig["s2"], "s3_gappoc": trig_sig["s3"],
        "gap_pct": round(trig_sig["gap"]*100, 1),
        "r5":  ret(entry, closes[5]  if len(closes) > 5  else np.nan),
        "r20": ret(entry, closes[20] if len(closes) > 20 else np.nan),
        "r60": ret(entry, closes[-1]),
        "max_runup": ret(entry, float(np.nanmax(fwd.High.values))),
        "mdd": ret(entry, float(np.nanmin(fwd.Low.values))),
    })

    # ── 出場規則模擬 ──
    exits = {}
    # GAP_STOP
    g = next((i for i in range(1, len(fwd)) if fwd.iloc[i].Close < trig_low), None)
    exits["exit_gapstop"] = ret(entry, float(fwd.iloc[g].Close)) if g else base["r60"]
    # TIME40
    exits["exit_time40"] = ret(entry, float(fwd.iloc[min(40, len(fwd)-1)].Close))
    # VOL_CLIMAX → 翌日開市
    v = next((i for i in range(1, len(fwd)-1)
              if np.isfinite(vol20.iloc[trig_t+i-1]) and vol20.iloc[trig_t+i-1] > 0
              and fwd.iloc[i].Volume >= 5*vol20.iloc[trig_t+i-1]
              and fwd.iloc[i].Close < fwd.iloc[i].Open), None)
    exits["exit_volclimax"] = ret(entry, float(fwd.iloc[v+1].Open)) if v else base["r60"]
    # COMBO: 最早出場嗰個
    cands = [(g, "C", None), (40, "T", None), (v+1 if v is not None else None, "V", None)]
    cands = [(i, k) for i, k, _ in cands if i is not None and i < len(fwd)]
    if cands:
        i, k = min(cands)
        px = float(fwd.iloc[i].Open) if k == "V" else float(fwd.iloc[i].Close)
        exits["exit_combo"] = ret(entry, px)
    else:
        exits["exit_combo"] = base["r60"]
    base.update({k: round(x, 1) if np.isfinite(x) else np.nan for k, x in exits.items()})
    return base

# ── 統計報告 ─────────────────────────────────────────
def report(res: pd.DataFrame) -> str:
    L = ["═"*62, "配股供股 × 三重突破 事件研究回測", "═"*62,
         f"事件總數: {len(res)} | 觸發 (S/A): {int(res.triggered.sum())} "
         f"({res.triggered.mean()*100:.0f}%)", ""]
    def block(name, s):
        s = s.dropna()
        if len(s) == 0:
            return [f"{name}: 無樣本"]
        return [f"{name}: n={len(s)} | 中位 {s.median():+.1f}% | 平均 {s.mean():+.1f}% | "
                f"勝率 {(s>0).mean()*100:.0f}% | P10 {s.quantile(.1):+.1f}% | P90 {s.quantile(.9):+.1f}%"]
    trg = res[res.triggered]
    L += ["── 觸發後報酬 (入場=觸發日收市) " + "─"*28]
    for col, lab in [("r5","T+5 "),("r20","T+20"),("r60","T+60"),("mdd","期間最大回撤"),("max_runup","期間最大升幅")]:
        if col in trg: L += block(lab, trg[col])
    L += ["", "── 按評級分拆 (T+20) " + "─"*38]
    for gr in ("S","A"):
        if "grade" in trg: L += block(f"{gr}級", trg[trg.grade==gr]["r20"])
    L += ["", "── 出場規則對比 (同一批觸發事件) " + "─"*26]
    for col, lab in [("r60","持有T+60  "),("exit_gapstop","缺口止損  "),
                     ("exit_time40","T+40時間止損"),("exit_volclimax","爆量滯漲走"),
                     ("exit_combo","三規則合併")]:
        if col in trg: L += block(lab, trg[col])
    L += ["", "── 基準對照 (事件日買入,唔等訊號) " + "─"*24]
    L += block("全部事件 T+20", res["base_r20"])
    L += block("全部事件 T+60", res["base_r60"])
    L += block("無觸發事件 T+60", res[~res.triggered]["base_r60"])
    L += ["", "註: 入場用觸發日收市價屬保守假設;細價股實際滑價/買賣差價會再食一截。", "═"*62]
    return "\n".join(L)

def main():
    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    rows, fails = [], []
    for i, ev in enumerate(events):
        try:
            rows.append(run_event(ev))
            print(f"[{i+1}/{len(events)}] ✓ {ev['code']} {rows[-1].get('grade','未觸發')}")
        except Exception as e:
            fails.append((ev["code"], str(e)))
            print(f"[{i+1}/{len(events)}] ✗ {ev['code']}: {e}", file=sys.stderr)
        time.sleep(0.5)
    res = pd.DataFrame(rows)
    res.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    rpt = report(res)
    OUT_RPT.write_text(rpt, encoding="utf-8")
    print("\n" + rpt)
    print(f"\n✓ 逐事件結果 → {OUT_CSV} | 報告 → {OUT_RPT}" +
          (f" | 失敗 {len(fails)} 件" if fails else ""))

if __name__ == "__main__":
    main()
