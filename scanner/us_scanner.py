"""
US small-cap corporate events scanner via SEC EDGAR.
Events: insider buying (Form 4), secondary offering (424B5),
        large position (SC 13D), rights offering (S-3/F-3).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
import requests
import yfinance as yf

# ── config ────────────────────────────────────────────────────────────────────
SMALL_CAP_USD   = int(os.getenv("US_SMALL_CAP_USD", str(2_000_000_000)))  # $2B
MIN_INSIDER_USD = int(os.getenv("US_MIN_INSIDER_USD", "50000"))            # filter noise
LOOKBACK_DAYS   = int(os.getenv("US_LOOKBACK_DAYS", "1"))
RATE_SLEEP      = 0.12  # stay under SEC 10 req/s

# POC breakout config (same defaults as HK)
US_POC_LOOKBACK_6M  = int(os.getenv("US_POC_LOOKBACK_6M", "126"))
US_POC_LOOKBACK_12M = int(os.getenv("US_POC_LOOKBACK_12M", "252"))
US_POC_LOOKBACK_3Y  = int(os.getenv("US_POC_LOOKBACK_3Y", "756"))
US_POC_BINS         = int(os.getenv("US_POC_BINS", "80"))
US_POC_PERIOD       = os.getenv("US_POC_PERIOD", "4y")
US_YF_BATCH         = int(os.getenv("US_YF_BATCH", "60"))     # batch size for yfinance
US_YF_THREADS       = int(os.getenv("US_YF_THREADS", "8"))
US_YF_TIMEOUT       = float(os.getenv("US_YF_TIMEOUT", "10"))
US_HOLDINGS_DIR     = os.getenv("US_HOLDINGS_DIR", "") or os.path.join(os.path.dirname(__file__), "..", "data")

SEC_HEADERS = {
    "User-Agent": "HK-Alert-Scanner rachellam288@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

_TYPE_LABEL = {
    "insider_buy":        "🏦 大手增持",
    "secondary_offering": "📉 配股",
    "rights_offering":    "🔄 供股",
    "large_position":     "🎯 大手建倉",
}

# ── US ticker universe (top ~100 stocks for POC/holdings scan) ────────────────
US_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","BRK-B","LLY","AVGO","TSLA",
    "JPM","WMT","V","XOM","UNH","MA","ORCL","COST","HD","PG","JNJ","BAC","ABBV",
    "KO","CVX","NFLX","MRK","CRM","AMD","PEP","TMO","ACN","LIN","MCD","ADBE",
    "DHR","TXN","PM","GE","CAT","AMAT","ISRG","QCOM","IBM","GS","NOW","NEE",
    "RTX","INTU","VZ","MS","AXP","SPGI","AMGN","BLK","UNP","HON","LOW","ELV",
    "BKNG","SYK","C","BA","PLD","MMC","T","DE","MDT","ABT","SCHW","BMY","REGN",
    "ZTS","ETN","CB","SO","MDLZ","DUK","COP","USB","BDX","ADP","MO","F","GM",
    "DIS","TGT","UBER","SBUX","INTC","WFC","PFE","GILD","CI","CVS","EOG","SLB",
    "EMR","ITW","AON","MCO","LRCX","PCAR","KMB","GD","PYPL","NXPI","MCHP","ADI",
]

_POC_WINDOWS = [
    ("半年POC", "6M", US_POC_LOOKBACK_6M, "#60a5fa"),
    ("12個月POC", "12M", US_POC_LOOKBACK_12M, "#f472b6"),
    ("3年POC", "3Y", US_POC_LOOKBACK_3Y, "#a78bfa"),
]

# ── market-cap filter ─────────────────────────────────────────────────────────

_mc_cache: dict[str, float | None] = {}

def get_market_cap(ticker: str) -> float | None:
    if ticker in _mc_cache:
        return _mc_cache[ticker]
    try:
        mc = yf.Ticker(ticker).fast_info.market_cap
        val = float(mc) if mc else None
    except Exception:
        val = None
    _mc_cache[ticker] = val
    return val

def is_small_cap(ticker: str) -> bool:
    mc = get_market_cap(ticker)
    return mc is not None and 0 < mc < SMALL_CAP_USD

# ── SEC EDGAR helpers ─────────────────────────────────────────────────────────

def _sec_get(url: str, timeout: int = 20) -> requests.Response | None:
    try:
        time.sleep(RATE_SLEEP)
        r = requests.get(url, headers=SEC_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"[SEC] GET {url[:80]} error: {e}")
        return None

def _extract_ticker(title: str) -> str | None:
    m = re.search(r"\(([A-Z]{1,5})\)\s*\(\d{4}-\d{2}-\d{2}\)", title)
    return m.group(1) if m else None

def _filing_date_ok(updated: str) -> bool:
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt <= timedelta(days=LOOKBACK_DAYS)
    except Exception:
        return True

def _edgar_rss(form_type: str, count: int = 40) -> list[dict]:
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcurrent&type={form_type}&dateb=&owner=include"
        f"&count={count}&search_text=&output=atom"
    )
    r = _sec_get(url)
    if not r:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(r.content)
        entries = []
        for e in root.findall("a:entry", ns):
            link_el = e.find("a:link", ns)
            entries.append({
                "title":   e.findtext("a:title", "", ns),
                "link":    link_el.attrib.get("href", "") if link_el is not None else "",
                "updated": e.findtext("a:updated", "", ns),
                "summary": e.findtext("a:summary", "", ns),
            })
        return entries
    except Exception as ex:
        print(f"[SEC RSS] parse error: {ex}")
        return []

# ── Form 4 — insider purchase ─────────────────────────────────────────────────

def _parse_form4(entry: dict) -> dict | None:
    ticker = _extract_ticker(entry["title"])
    if not ticker or not _filing_date_ok(entry["updated"]):
        return None

    r_idx = _sec_get(entry["link"])
    if not r_idx:
        return None
    xml_m = re.search(r'href="(/Archives/edgar/data/[^"]+\.xml)"', r_idx.text)
    if not xml_m:
        return None

    r_xml = _sec_get("https://www.sec.gov" + xml_m.group(1))
    if not r_xml:
        return None
    try:
        root = ET.fromstring(r_xml.content)
    except Exception:
        return None

    purchases = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        if txn.findtext(".//transactionCode", "") != "P":
            continue
        try:
            shares = float(txn.findtext(".//transactionShares/value") or 0)
            price  = float(txn.findtext(".//transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        if shares > 0 and price > 0:
            purchases.append({"shares": shares, "price": price})

    if not purchases:
        return None

    total_shares = sum(p["shares"] for p in purchases)
    total_value  = sum(p["shares"] * p["price"] for p in purchases)
    if total_value < MIN_INSIDER_USD:
        return None

    return {
        "ticker": ticker,
        "name":   root.findtext(".//issuerName", ticker),
        "type":   "insider_buy",
        "shares": int(total_shares),
        "value":  int(total_value),
        "avg_price": round(total_value / total_shares, 4),
        "filer": root.findtext(".//rptOwnerName", ""),
        "title": root.findtext(".//officerTitle", ""),
        "url":   entry["link"],
        "updated": entry["updated"],
    }

# ── 424B5 — secondary offering ────────────────────────────────────────────────

def _parse_424b5(entry: dict) -> dict | None:
    ticker = _extract_ticker(entry["title"])
    if not ticker or not _filing_date_ok(entry["updated"]):
        return None
    r = _sec_get(entry["link"])
    offering_price, offering_shares = None, None
    if r:
        txt = r.text[:8000]
        pm = re.search(r"\$([\d,.]+)\s*per\s+share", txt, re.I)
        sm = re.search(r"([\d,]+)\s+shares", txt, re.I)
        if pm:
            try: offering_price = float(pm.group(1).replace(",", ""))
            except: pass
        if sm:
            try: offering_shares = int(sm.group(1).replace(",", ""))
            except: pass
    return {
        "ticker": ticker, "type": "secondary_offering",
        "offering_price": offering_price, "offering_shares": offering_shares,
        "url": entry["link"], "updated": entry["updated"],
    }

# ── SC 13D — large position ───────────────────────────────────────────────────

def _parse_13d(entry: dict) -> dict | None:
    ticker = _extract_ticker(entry["title"])
    if not ticker or not _filing_date_ok(entry["updated"]):
        return None
    return {
        "ticker": ticker, "type": "large_position",
        "url": entry["link"], "updated": entry["updated"],
    }

# ── Rights offering ───────────────────────────────────────────────────────────

def _fetch_rights() -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = (
        "https://efts.sec.gov/LATEST/search-index"
        f"?q=%22rights+offering%22&forms=S-3,F-3"
        f"&dateRange=custom&startdt={start}&enddt={end}"
    )
    r = _sec_get(url)
    if not r:
        return []
    results = []
    try:
        for hit in r.json().get("hits", {}).get("hits", []):
            src   = hit.get("_source", {})
            names = src.get("display_names") or []
            ticker = names[0].get("ticker", "") if names else ""
            name   = names[0].get("name", ticker) if names else ticker
            if not ticker or len(ticker) > 5 or not ticker.isalpha():
                continue
            results.append({
                "ticker": ticker.upper(), "name": name,
                "type": "rights_offering",
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={src.get('entity_id','')}&type=S-3",
                "updated": src.get("file_date", ""),
            })
    except Exception as ex:
        print(f"[rights] parse error: {ex}")
    return results

# ── emit ──────────────────────────────────────────────────────────────────────

def _emit(result: dict, mc: float | None) -> None:
    sys.path.insert(0, os.path.dirname(__file__))
    from hk_cloud_scanner import post_gas_alert, send_telegram_alert, build_inline_keyboard_

    ticker = result["ticker"]
    name   = result.get("name") or ticker
    label  = _TYPE_LABEL.get(result["type"], result["type"])
    mc_str = f"  市值：${mc / 1e6:.0f}M" if mc else ""
    tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"

    if result["type"] == "insider_buy":
        role = f"（{result['title']}）" if result.get("title") else ""
        caption = (
            f"{label}\n"
            f"{ticker}　{name}\n"
            f"買入：{result['shares']:,}股 @ ${result['avg_price']}\n"
            f"金額：${result['value']:,}{mc_str}\n"
            f"買家：{result.get('filer', '—')}{role}"
        )
        tags = ["美股", "大手增持", "Form4"]
    elif result["type"] == "secondary_offering":
        price_str  = f" @ ${result['offering_price']}" if result.get("offering_price") else ""
        shares_str = f"　{result['offering_shares']:,}股" if result.get("offering_shares") else ""
        caption = (
            f"{label}\n"
            f"{ticker}　{name}\n"
            f"配股{shares_str}{price_str}{mc_str}"
        )
        tags = ["美股", "配股", "424B5"]
    elif result["type"] == "rights_offering":
        caption = f"{label}\n{ticker}　{name}{mc_str}"
        tags = ["美股", "供股"]
    else:
        caption = f"{label} (SC 13D)\n{ticker}　{name}{mc_str}"
        tags = ["美股", "大手建倉", "13D"]

    payload: dict[str, Any] = {
        "source": "sec_edgar", "category": "us_corp",
        "code": ticker, "symbol": ticker, "name": name,
        "signal": label, "market": "US", "timeframe": "事件",
        "message": caption, "strategy": "SEC EDGAR Event",
        "chart_url": "", "source_url": result["url"],
        "tags": tags, "priority": 2,
        "raw": json.dumps(result, ensure_ascii=False),
    }
    post_gas_alert(payload)
    send_telegram_alert(caption, None, reply_markup=build_inline_keyboard_([
        ("📊 走勢圖", tv_url),
        ("📋 SEC", result["url"]),
    ]))
    time.sleep(0.5)

# ── main ──────────────────────────────────────────────────────────────────────

def run_us_corp_actions() -> None:
    print(f"[US] scan  small_cap<${SMALL_CAP_USD / 1e9:.1f}B  min_insider=${MIN_INSIDER_USD:,}")
    candidates: list[dict] = []

    for form, fn, count in [
        ("4",     _parse_form4, 40),
        ("424B5", _parse_424b5, 40),
        ("SC+13D",_parse_13d,   20),
    ]:
        print(f"[US] {form} ...")
        for entry in _edgar_rss(form, count):
            r = fn(entry)
            if r:
                candidates.append(r)

    print("[US] rights offerings ...")
    candidates.extend(_fetch_rights())

    print(f"[US] candidates={len(candidates)}, filtering small-cap ...")
    seen: set[str] = set()
    alerted = skipped = 0
    for result in candidates:
        key = f"{result['ticker']}:{result['type']}"
        if key in seen:
            continue
        seen.add(key)
        mc = get_market_cap(result["ticker"])
        if mc is None or mc >= SMALL_CAP_USD:
            skipped += 1
            label = f"${mc/1e9:.2f}B" if mc else "no data"
            print(f"[US] skip {result['ticker']} ({label})")
            continue
        print(f"[US] ALERT {result['ticker']} {result['type']}  mc=${mc/1e6:.0f}M")
        try:
            _emit(result, mc)
            alerted += 1
        except Exception as e:
            print(f"[US] emit error {result['ticker']}: {e}")

    print(f"[US] done  alerted={alerted}  skipped={skipped}")


# ═══════════════════════════════════════════════════════════════════════════════════
# US POC breakout + year-open (port from HK POC scanner)
# ═══════════════════════════════════════════════════════════════════════════════════

def _us_tv_url(ticker: str) -> str:
    """TradingView URL for US stocks (no HKEX: prefix)."""
    return f"https://www.tradingview.com/chart/?symbol={ticker}"

def _us_normalize_yfinance_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance DataFrame to internal OHLCV format."""
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df = df.rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    required = ["date", "open", "high", "low", "close", "volume"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[df["close"] > 0]
    df["volume"] = df["volume"].fillna(0)
    return df.sort_values("date").reset_index(drop=True)

def _us_batch_history(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Batch download US stock history via yfinance."""
    out: dict[str, pd.DataFrame] = {}
    try:
        raw = yf.download(
            tickers=tickers, period=period, interval="1d",
            auto_adjust=False, progress=False, threads=US_YF_THREADS,
            group_by="ticker", timeout=US_YF_TIMEOUT,
        )
    except Exception as exc:
        print(f"[US batch] download failed: {exc}")
        return out
    if raw is None or raw.empty:
        return out
    # Single ticker
    if not isinstance(raw.columns, pd.MultiIndex):
        if tickers:
            df = _us_normalize_yfinance_df(raw)
            if not df.empty:
                out[tickers[0]] = df
        return out
    for t in tickers:
        try:
            sub = raw[t]
        except KeyError:
            continue
        if sub is None or sub.dropna(how="all").empty:
            continue
        df = _us_normalize_yfinance_df(sub.copy())
        if not df.empty:
            out[t] = df
    return out

def _us_calculate_poc(profile_df: pd.DataFrame) -> float | None:
    """Replicate hk_cloud_scanner.calculate_poc() locally to avoid circular deps."""
    if profile_df.empty:
        return None
    low = profile_df["low"].min()
    high = profile_df["high"].max()
    if pd.isna(low) or pd.isna(high) or high <= low:
        return None
    bins = pd.interval_range(start=low, end=high, periods=US_POC_BINS)
    typical_price = (profile_df["high"] + profile_df["low"] + profile_df["close"]) / 3
    bucket = pd.cut(typical_price, bins)
    vol_by_bucket = profile_df.groupby(bucket, observed=False)["volume"].sum()
    if vol_by_bucket.empty:
        return None
    poc_interval = vol_by_bucket.idxmax()
    if pd.isna(poc_interval):
        return None
    return round((poc_interval.left + poc_interval.right) / 2, 4)

def _us_check_poc(ticker: str, name: str, df: pd.DataFrame) -> dict | None:
    """Check POC breakout for one US stock. Returns result dict or None."""
    if df.empty or len(df) < US_POC_LOOKBACK_6M + 2:
        return None
    today = df.iloc[-1]
    prev = df.iloc[-2]
    today_high = float(today["high"])
    prev_high = float(prev["high"])
    poc_results: list[dict] = []
    for label, short, lookback, _color in _POC_WINDOWS:
        if len(df) < lookback + 2:
            poc_results.append({"label": label, "short": short, "poc": None, "break_pct": None, "crossed": False})
            continue
        profile = df.iloc[-(lookback + 1):-1].copy()
        poc = _us_calculate_poc(profile)
        if poc is None or poc <= 0:
            poc_results.append({"label": label, "short": short, "poc": None, "break_pct": None, "crossed": False})
            continue
        crossed = today_high > poc and prev_high <= poc
        poc_results.append({
            "label": label, "short": short, "poc": round(poc, 3),
            "break_pct": round((today_high / poc - 1) * 100, 2),
            "crossed": crossed,
        })
    crossed = [x for x in poc_results if x["crossed"]]
    if not crossed:
        return None
    def _by(short: str) -> float | None:
        return next((x["poc"] for x in poc_results if x["short"] == short), None)
    main = crossed[0]
    return {
        "ticker": ticker, "name": name,
        "signal": " + ".join(x["label"] for x in crossed),
        "crossed_short": " / ".join(x["short"] for x in crossed),
        "poc": main["poc"],
        "poc_6m": _by("6M"), "poc_12m": _by("12M"), "poc_3y": _by("3Y"),
        "today_high": round(today_high, 3),
        "today_close": round(float(today["close"]), 3),
        "break_value": round(today_high, 3),
        "break_pct": main["break_pct"],
        "data_date": str(today["date"].date()),
    }

def _us_check_year_open(ticker: str, name: str, df: pd.DataFrame) -> dict | None:
    """Check if price crosses above current year's first trading day open."""
    if df.empty or len(df) < 3:
        return None
    current_year = datetime.now().year
    year_mask = df["date"].dt.year == current_year
    year_data = df[year_mask]
    if year_data.empty:
        return None
    year_open = float(year_data.iloc[0]["open"])
    year_open_date = str(year_data.iloc[0]["date"].date())
    if year_open <= 0:
        return None
    today = df.iloc[-1]
    prev = df.iloc[-2]
    today_close = float(today["close"])
    prev_close = float(prev["close"])
    if today_close > year_open and prev_close <= year_open:
        return {
            "ticker": ticker, "name": name,
            "year": current_year,
            "year_open": round(year_open, 3),
            "year_open_date": year_open_date,
            "break_pct": round((today_close / year_open - 1) * 100, 2),
            "data_date": str(today["date"].date()),
        }
    return None

def _us_emit_poc(result: dict, df: pd.DataFrame) -> None:
    """Send POC breakout alert to Telegram + GAS."""
    sys.path.insert(0, os.path.dirname(__file__))
    from hk_cloud_scanner import render_chart, build_inline_keyboard_, emit_alert

    ticker = result["ticker"]
    tv_url = _us_tv_url(ticker)
    caption = (
        f"⚡US POC觸發：{result['signal']}\n"
        f"📈{ticker} {result['name']}\n"
        f"高於觸發：<b>+{result['break_pct']}%</b> ({result['break_value']})"
    )
    levels = []
    for label, short, _lookback, color in _POC_WINDOWS:
        val = result.get(f"poc_{short.lower()}")
        if val is not None:
            levels.append((label, val, color))
    chart = render_chart(df, ticker, result["name"],
                          f"US POC · {result['crossed_short']}",
                          levels=levels,
                          lookback_days=180)
    payload: dict[str, Any] = {
        "source": "us_scanner", "category": "poc",
        "code": ticker, "symbol": ticker, "name": result["name"],
        "signal": result["signal"], "market": "US",
        "timeframe": "1D", "price": result["today_close"],
        "message": f"POC突破 {result['crossed_short']} 幅度 {result['break_pct']}%",
        "strategy": "US POC Breakout", "chart_url": tv_url,
        "source_url": tv_url,
        "tags": ["美股", "POC", "Breakout"],
        "priority": 2,
        "raw": json.dumps(result, ensure_ascii=False, default=str),
    }
    emit_alert(payload, caption, chart, reply_markup=build_inline_keyboard_([("📊 走勢圖", tv_url)]))

def _us_emit_year_open(result: dict, df: pd.DataFrame) -> None:
    sys.path.insert(0, os.path.dirname(__file__))
    from hk_cloud_scanner import render_chart, build_inline_keyboard_, emit_alert

    ticker = result["ticker"]
    tv_url = _us_tv_url(ticker)
    caption = (
        f"📅{result['year']}年開突破\n"
        f"{ticker} {result['name']}\n"
        f"年開：{result['year_open']}（{result['year_open_date']}）\n"
        f"突破：<b>+{result['break_pct']}%</b>"
    )
    chart = render_chart(df, ticker, result["name"],
                          f"US年開突破 {result['year']}",
                          levels=[(f"{result['year']}年開", result["year_open"], "#f59e0b")],
                          lookback_days=180)
    payload: dict[str, Any] = {
        "source": "us_scanner", "category": "year_open",
        "code": ticker, "symbol": ticker, "name": result["name"],
        "signal": "年開突破", "market": "US",
        "timeframe": "1D", "price": result.get("today_close", 0),
        "message": f"{result['year']}年開{result['year_open']}突破",
        "strategy": "US Year Open Breakout", "chart_url": tv_url,
        "source_url": tv_url,
        "tags": ["美股", "年開突破"],
        "priority": 2,
        "raw": json.dumps(result, ensure_ascii=False, default=str),
    }
    emit_alert(payload, caption, chart, reply_markup=build_inline_keyboard_([("📊 走勢圖", tv_url)]))

def run_us_breakout() -> None:
    """Scan US stocks for POC breakout + year-open breakout."""
    print(f"[US POC] scan {len(US_TICKERS)} US stocks (period={US_POC_PERIOD})")
    data = _us_batch_history(US_TICKERS, US_POC_PERIOD)
    print(f"[US POC] got data for {len(data)} tickers")

    poc_hits = 0
    yo_hits = 0
    for ticker in US_TICKERS:
        df = data.get(ticker)
        if df is None or df.empty:
            continue
        name = ticker

        # POC
        try:
            r = _us_check_poc(ticker, name, df)
            if r:
                poc_hits += 1
                print(f"[US POC] {ticker} POC: {r['signal']} +{r['break_pct']}%")
                try:
                    _us_emit_poc(r, df)
                except Exception as e:
                    print(f"[US POC] emit error {ticker}: {e}")
        except Exception as e:
            print(f"[US POC] check error {ticker}: {e}")

        # Year-open
        try:
            yo = _us_check_year_open(ticker, name, df)
            if yo:
                yo_hits += 1
                print(f"[US year-open] {ticker} +{yo['break_pct']}%")
                try:
                    _us_emit_year_open(yo, df)
                except Exception as e:
                    print(f"[US year-open] emit error {ticker}: {e}")
        except Exception as e:
            print(f"[US year-open] check error {ticker}: {e}")

        time.sleep(0.05)

    print(f"[US POC] done  poc_hits={poc_hits}  year_open_hits={yo_hits}")


# ═══════════════════════════════════════════════════════════════════════════════════
# US institutional holdings analysis (like CCASS for HK)
# ═══════════════════════════════════════════════════════════════════════════════════

def _fetch_us_holders(ticker: str) -> dict | None:
    """Fetch institutional holdings data for one US stock via yfinance."""
    try:
        t = yf.Ticker(ticker)
        mh = t.major_holders
        ih = t.institutional_holders
    except Exception as e:
        print(f"[US holdings] {ticker} yfinance error: {e}")
        return None
    if mh is None or mh.empty:
        return None

    # Parse major_holders
    inst_pct = None
    inst_count = None
    insider_pct = None
    try:
        for _, row in mh.iterrows():
            label = str(row.iloc[0]).lower() if row.iloc[0] else ""
            val = row.iloc[1] if len(row) > 1 else None
            if val is None:
                continue
            val = float(val)
            if "institution" in label and "count" in label:
                inst_count = int(val)
            elif "institution" in label and "percent" in label:
                inst_pct = round(val * 100, 2)
            elif "insider" in label and "percent" in label:
                insider_pct = round(val * 100, 2)
    except Exception:
        pass

    # Parse institutional_holders (top 10)
    holders: list[dict] = []
    if ih is not None and not ih.empty:
        for _, row in ih.iterrows():
            try:
                holders.append({
                    "name": str(row.get("Holder", row.iloc[1])),
                    "shares": int(row.get("Shares", 0)) if row.get("Shares", 0) else 0,
                    "pct": float(row.get("pctHeld", 0)) * 100 if row.get("pctHeld", 0) else 0,
                    "change": float(row.get("pctChange", 0)) if row.get("pctChange", 0) else 0,
                    "date": str(row.get("Date Reported", "")),
                })
            except Exception:
                continue

    if inst_pct is None and not holders:
        return None

    # Compute Top5 / Top10 concentration
    sorted_pcts = sorted([h["pct"] for h in holders], reverse=True)
    top5_pct = round(sum(sorted_pcts[:5]), 2) if len(sorted_pcts) >= 5 else None
    top10_pct = round(sum(sorted_pcts[:10]), 2) if len(sorted_pcts) >= 10 else None

    return {
        "ticker": ticker,
        "inst_pct": inst_pct,
        "inst_count": inst_count,
        "insider_pct": insider_pct,
        "top5_pct": top5_pct,
        "top10_pct": top10_pct,
        "top_holders": holders[:10],
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

def run_us_holdings() -> None:
    """Scan all US tickers for institutional holdings data (like CCASS analysis).

    Saves to us_holdings.json and sends Telegram for notable changes.
    """
    os.makedirs(US_HOLDINGS_DIR, exist_ok=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", "us_holdings.json")

    # Load previous snapshot for comparison
    prev: dict = {}
    if os.path.exists(out_path):
        try:
            prev = json.load(open(out_path, encoding="utf-8"))
        except Exception:
            prev = {}

    results: dict[str, dict] = {}
    total = len(US_TICKERS)
    notable: list[str] = []

    for i, ticker in enumerate(US_TICKERS, 1):
        if i % 20 == 0:
            print(f"[US holdings] progress {i}/{total}")
        try:
            h = _fetch_us_holders(ticker)
        except Exception as e:
            print(f"[US holdings] {ticker} error: {e}")
            continue
        if not h:
            continue
        results[ticker] = h

        # Compare with previous snapshot
        old = prev.get(ticker, {})
        if old:
            old_inst_count = old.get("inst_count")
            new_inst_count = h.get("inst_count")
            if old_inst_count and new_inst_count:
                change = (new_inst_count - old_inst_count) / old_inst_count * 100
                if abs(change) > 5:
                    notable.append(f"{ticker} 機構數 {old_inst_count}→{new_inst_count} ({change:+.1f}%)")
            old_top5 = old.get("top5_pct")
            new_top5 = h.get("top5_pct")
            if old_top5 and new_top5 and abs(new_top5 - old_top5) > 3:
                notable.append(f"{ticker} Top5集中度 {old_top5}%→{new_top5}%")

        time.sleep(0.1)

    # Save snapshot
    snapshot = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "stocks": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"[US holdings] saved to {out_path} ({len(results)} stocks)")

    # Send notable changes as admin-style summary
    if notable:
        sys.path.insert(0, os.path.dirname(__file__))
        from hk_cloud_scanner import send_telegram_message
        msg = f"📊 <b>US 機構持倉變化</b>\n" + "\n".join(notable[:10])
        if len(notable) > 10:
            msg += f"\n… 及 {len(notable) - 10} 項"
        try:
            send_telegram_message(msg)
        except Exception as e:
            print(f"[US holdings] tg error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════════
# Combined runner
# ═══════════════════════════════════════════════════════════════════════════════════

def run_us_all() -> None:
    """Run all US scans: corp actions → breakout → holdings."""
    run_us_corp_actions()
    print()
    run_us_breakout()
    print()
    run_us_holdings()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "corp"
    if mode == "all":
        run_us_all()
    elif mode == "breakout":
        run_us_breakout()
    elif mode == "holdings":
        run_us_holdings()
    else:
        run_us_corp_actions()
