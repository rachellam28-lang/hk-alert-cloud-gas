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

import requests
import yfinance as yf

# ── config ────────────────────────────────────────────────────────────────────
SMALL_CAP_USD   = int(os.getenv("US_SMALL_CAP_USD", str(2_000_000_000)))  # $2B
MIN_INSIDER_USD = int(os.getenv("US_MIN_INSIDER_USD", "50000"))            # filter noise
LOOKBACK_DAYS   = int(os.getenv("US_LOOKBACK_DAYS", "1"))
RATE_SLEEP      = 0.12  # stay under SEC 10 req/s

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


if __name__ == "__main__":
    run_us_corp_actions()
