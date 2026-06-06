"""
向上跳空缺口 + 向上FVG 警報 — 針對剛做配股/供股嘅股票
Stores alerts in scanner_alerts table (shared with hk_cloud_scanner).
"""
import json, os, sys, time, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf
import pandas as pd

# local dopamine system
try:
    from scanner.dopamine import compute_dopamine, save_dopamine
except ImportError:
    from dopamine import compute_dopamine, save_dopamine

HKT = timezone(timedelta(hours=8))
PROJECT = Path(__file__).resolve().parent.parent
DB = PROJECT / "ccass" / "ccass.db"
CORP_FILE = PROJECT / "scanner" / "corp_scan_result.json"
ALERT_FILE = PROJECT / "data" / "alerts.json"
POC_BINS = 80
POC_LOOKBACK_12M = 252

def calculate_poc(df_lower: pd.DataFrame) -> float | None:
    """Calculate 12-month POC (Point of Control) from OHLCV data. 
    Expects columns: open, high, low, close, volume (lowercase)."""
    if df_lower.empty:
        return None
    low = df_lower["low"].min()
    high = df_lower["high"].max()
    if pd.isna(low) or pd.isna(high) or high <= low:
        return None
    bins = pd.interval_range(start=low, end=high, periods=POC_BINS)
    typical_price = (df_lower["high"] + df_lower["low"] + df_lower["close"]) / 3
    bucket = pd.cut(typical_price, bins)
    volume_by_bucket = df_lower.groupby(bucket, observed=False)["volume"].sum()
    if volume_by_bucket.empty:
        return None
    poc_interval = volume_by_bucket.idxmax()
    if pd.isna(poc_interval):
        return None
    return round((poc_interval.left + poc_interval.right) / 2, 4)

# ═══════════════════════════════════════════════════════════════
def get_db():
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def load_corp_stocks() -> list[dict]:
    """Load stocks with recent placements/rights from corp scan result."""
    if not CORP_FILE.exists():
        return []
    with open(CORP_FILE, encoding="utf-8") as f:
        data = json.load(f)
    stocks = []
    for item in data.get("alerted", []) + data.get("watchlisted", []):
        code = item.get("code", "").strip()
        if code:
            stocks.append({"code": code.zfill(5), "name": item.get("name", ""), "type": item.get("type", "")})
    return stocks

def detect_upward_gaps(df) -> list[dict]:
    """Check ALL candles for upward gaps: open > prev high. Returns list of gaps found."""
    if len(df) < 2:
        return []
    gaps = []
    for i in range(1, len(df)):
        today = df.iloc[i]
        yesterday = df.iloc[i - 1]
        if today["Open"] > yesterday["High"]:
            gap_pct = (today["Open"] - yesterday["High"]) / yesterday["High"] * 100
            gaps.append({
                "type": "向上跳空缺口",
                "gap_pct": round(gap_pct, 2),
                "open": round(float(today["Open"]), 3),
                "prev_high": round(float(yesterday["High"]), 3),
                "date": str(df.index[i].date()),
                "close": round(float(today["Close"]), 3),
            })
    return gaps

def detect_bullish_fvgs(df) -> list[dict]:
    """Detect ALL bullish FVGs on daily: c1.high < c3.low (3-candle pattern)."""
    if len(df) < 3:
        return []
    fvgs = []
    for i in range(2, len(df)):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        if c1["High"] < c3["Low"]:
            gap_low = float(c1["High"])
            gap_high = float(c3["Low"])
            current = float(c3["Close"])
            if current > gap_low:
                fvg_pct = (gap_high - gap_low) / gap_low * 100
                fvgs.append({
                    "type": "向上FVG",
                    "fvg_pct": round(fvg_pct, 2),
                    "gap_low": round(gap_low, 3),
                    "gap_high": round(gap_high, 3),
                    "current": round(current, 3),
                    "date": str(df.index[i].date()),
                })
    return fvgs

def fetch_stock_data(code: str, days: int = 20) -> Any:
    """Fetch daily OHLCV from yfinance. Returns DataFrame or None."""
    try:
        # yfinance HK format: strip leading zeros (1128.HK not 01128.HK)
        ticker = f"{int(code)}.HK"
        df = yf.download(ticker, period=f"{days+5}d", progress=False)
        if df.empty:
            return None
        # flatten multi-level columns if auto_adjust
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.tail(days)
    except Exception:
        return None

def save_alert(code: str, name: str, signal: dict, corp_type: str = ""):
    """Save alert to scanner_alerts table. Dedup by date."""
    db = get_db()
    try:
        now = datetime.now(HKT).isoformat()
        signal_date = signal.get("date", datetime.now(HKT).strftime("%Y-%m-%d"))
        dedup_key = f"{code}_{signal['type']}_{signal_date}"
        payload = json.dumps({"code": code, "name": name, "signal": signal, "corp_type": corp_type}, ensure_ascii=False)
        
        msg_parts = [f"{code} {name}"]
        if corp_type:
            msg_parts.append(f"({corp_type})")
        if signal["type"] == "向上跳空缺口":
            msg_parts.append(f"🔼缺口 {signal['gap_pct']}% ({signal_date})")
        elif signal["type"] == "向上FVG":
            msg_parts.append(f"📈FVG {signal['fvg_pct']}% ({signal_date})")
        elif signal["type"] == "上破POC 12M":
            msg_parts.append(f"🎯POC {signal['breakout_pct']}% (POC={signal['poc']})")
        else:
            msg_parts.append(f"{signal['type']} ({signal_date})")
        message = " ".join(msg_parts)

        db.execute("""INSERT OR REPLACE INTO scanner_alerts
            (dedup_key, market, code, category, signal, priority, message, payload_json, created_at)
            VALUES (?, 'HK', ?, 'gap_fvg', ?, 2, ?, ?, ?)""",
            (dedup_key, code, signal["type"], message, payload, now))
        db.commit()
        return True
    except Exception as e:
        print(f"  save_alert error: {e}", file=sys.stderr)
        return False
    finally:
        db.close()

def export_alerts_json(dopamine_cap: int = 50):
    """Export recent gap/FVG alerts to data/alerts.json for dashboard."""
    db = get_db()
    try:
        rows = db.execute(f"""SELECT code, category, signal, message, created_at, payload_json
            FROM scanner_alerts WHERE category='gap_fvg'
            AND created_at >= datetime('now', '-7 days')
            ORDER BY created_at DESC LIMIT {dopamine_cap}""").fetchall()
        alerts = [dict(r) for r in rows]
        for a in alerts:
            if a.get("payload_json"):
                try:
                    a["payload"] = json.loads(a["payload_json"])
                except:
                    pass
        ALERT_FILE.parent.mkdir(exist_ok=True)
        with open(ALERT_FILE, "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.now(HKT).isoformat(), "count": len(alerts), "alerts": alerts}, f, ensure_ascii=False, indent=2)
        return len(alerts)
    finally:
        db.close()

def detect_poc_12m_breakout(code: str) -> list[dict]:
    """Check if stock broke above its 12-month POC. Returns list of POC signals."""
    try:
        ticker = f"{int(code)}.HK"
        df = yf.download(ticker, period=f"{POC_LOOKBACK_12M + 30}d", progress=False)
        if df.empty or len(df) < 60:
            return []
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # Normalize columns to lowercase
        df_lower = df.rename(columns={c: c.lower() for c in df.columns})
        
        poc = calculate_poc(df_lower)
        if poc is None:
            return []
        
        current = float(df_lower.iloc[-1]["close"])
        if current > poc:
            breakout_pct = (current - poc) / poc * 100
            return [{
                "type": "上破POC 12M",
                "poc": round(poc, 3),
                "current": round(current, 3),
                "breakout_pct": round(breakout_pct, 2),
                "date": str(df.index[-1].date()),
            }]
        return []
    except Exception:
        return []

# Update main loop
def main():
    stocks = load_corp_stocks()
    if not stocks:
        print("No corp action stocks found.")
        return

    # ── Dopamine system ──
    dop = compute_dopamine()
    save_dopamine(dop)
    th = dop.get("thresholds", {})
    poc_min = th.get("poc_min_pct", 2.5)
    gap_min = th.get("gap_min_pct", 1.0)
    fvg_min = th.get("fvg_min_pct", 1.0)
    alert_cap = th.get("alert_cap", 50)
    print(f"🧠 Dopamine: {dop['dopamine']} ({dop['label']}) | HSI {dop['hsi']} | "
          f"poc≥{poc_min}% gap≥{gap_min}% fvg≥{fvg_min}% cap={alert_cap}")

    print(f"Scanning {len(stocks)} corp-action stocks for upward gaps/FVGs...")
    found = 0

    for i, s in enumerate(stocks):
        code, name = s["code"], s["name"]
        corp = s.get("type", "")
        
        df = fetch_stock_data(code, days=60)
        if df is None:
            continue
        
        gaps = detect_upward_gaps(df)
        fvgs = detect_bullish_fvgs(df)
        
        for gap in gaps:
            if gap["gap_pct"] < gap_min:
                continue
            if save_alert(code, name, gap, corp):
                print(f"  🔼 {code} {name}: {gap['type']} {gap['gap_pct']}% ({gap['date']})")
                found += 1
        
        for fvg in fvgs:
            if fvg["fvg_pct"] < fvg_min:
                continue
            if save_alert(code, name, fvg, corp):
                print(f"  📈 {code} {name}: {fvg['type']} {fvg['fvg_pct']}% ({fvg['date']})")
                found += 1
        
        # Check POC 12M breakout
        pocs = detect_poc_12m_breakout(code)
        for poc in pocs:
            if poc["breakout_pct"] < poc_min:
                continue
            if save_alert(code, name, poc, corp):
                print(f"  🎯 {code} {name}: {poc['type']} {poc['breakout_pct']}% (POC={poc['poc']})")
                found += 1
        
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(stocks)}, found={found}")
        
        time.sleep(0.3)  # gentle rate limit

    n = export_alerts_json(alert_cap)
    print(f"Done: {found} alerts found, {n} exported to {ALERT_FILE}")

if __name__ == "__main__":
    main()
