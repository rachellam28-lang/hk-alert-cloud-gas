"""
HK Alert Cloud Scanner

Cloud version for GitHub Actions:
- No AKShare
- HK stock list from HKEX official ListOfSecurities.xlsx
- Price history from Yahoo Finance / yfinance
- Alerts to Telegram and Google Apps Script webhook

Signals:
1. IPO first-day high breakout
2. 6M POC breakout
3. 12M POC breakout
4. HKEXnews corporate action: rights issue / placing / shareholder increase
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import datetime
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

HKEX_LIST_URL = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
HKEXNEWS_BASE = "https://www.hkexnews.hk"

MAX_STOCKS = int(os.getenv("MAX_STOCKS", "0"))
MIN_LISTING_DAYS = int(os.getenv("MIN_LISTING_DAYS", "5"))
MAX_LISTING_DAYS = int(os.getenv("MAX_LISTING_DAYS", "0"))
POC_LOOKBACK_DAYS_6M = int(os.getenv("POC_LOOKBACK_DAYS_6M", "126"))
POC_LOOKBACK_DAYS_12M = int(os.getenv("POC_LOOKBACK_DAYS_12M", "252"))
POC_BINS = int(os.getenv("POC_BINS", "80"))
BREAKOUT_FIELD = os.getenv("BREAKOUT_FIELD", "high").lower().strip()
ANNOUNCEMENT_RANGE_DAYS = int(os.getenv("ANNOUNCEMENT_RANGE_DAYS", "7"))
SLEEP_SEC = float(os.getenv("SLEEP_SEC", "0.15"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "2"))
RETRY_SLEEP = int(os.getenv("RETRY_SLEEP", "3"))
YF_IPO_PERIOD = os.getenv("YF_IPO_PERIOD", "max")
YF_POC_PERIOD = os.getenv("YF_POC_PERIOD", "3y")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
GAS_SECRET = os.getenv("GAS_SECRET", "")


def hk_code_to_yahoo(code: str) -> str:
    code = str(code).strip().zfill(5)
    return f"{code[-4:]}.HK"


def tradingview_url(code: str) -> str:
    symbol = hk_code_to_yahoo(code).replace(".HK", "")
    return f"https://www.tradingview.com/chart/?symbol=HKEX%3A{symbol}"


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200:
            print("[Telegram] sent")
            return True
        print(f"[Telegram] failed: {r.status_code} {r.text[:300]}")
    except Exception as exc:
        print(f"[Telegram] error: {exc}")
    return False


def post_gas_alert(payload: dict[str, Any]) -> bool:
    if not GAS_WEBHOOK_URL:
        print("[GAS] GAS_WEBHOOK_URL not configured")
        return False
    body = dict(payload)
    if GAS_SECRET:
        body["secret"] = GAS_SECRET
    try:
        r = requests.post(GAS_WEBHOOK_URL, json=body, timeout=20)
        if r.status_code == 200:
            print("[GAS] posted")
            return True
        print(f"[GAS] failed: {r.status_code} {r.text[:300]}")
    except Exception as exc:
        print(f"[GAS] error: {exc}")
    return False


def emit_alert(payload: dict[str, Any], telegram_html: str) -> None:
    payload.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    post_gas_alert(payload)
    send_telegram(telegram_html)


CORP_ACTION_KEYWORDS = {
    "供股": ["rights issue", "open offer", "供股", "公開發售"],
    "配股": [
        "placing",
        "subscription of new shares",
        "subscription agreement",
        "issue of shares",
        "issue of new shares",
        "配售",
        "認購新股份",
        "認購事項",
        "發行股份",
    ],
    "股東增持": [
        "increase in shareholding",
        "acquire shares",
        "rights to acquire shares",
        "shareholding increase",
        "增持",
        "股權增加",
        "董事權利",
    ],
}


def html_to_text(value: Any) -> str:
    if value is None:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def classify_corp_action(text: str) -> list[str]:
    lower_text = text.lower()
    matched: list[str] = []
    for action_type, keywords in CORP_ACTION_KEYWORDS.items():
        if any(keyword.lower() in lower_text for keyword in keywords):
            matched.append(action_type)
    return matched


def should_skip_announcement_title(title: str) -> bool:
    lower_title = title.lower()
    skip_words = [
        "annual general meeting",
        "extraordinary general meeting",
        "shareholders' meeting",
        "notice of agm",
        "notice of egm",
        "proxy form",
        "circular",
    ]
    strong_words = [
        "rights issue",
        "open offer",
        "placing",
        "subscription of new shares",
        "issue of shares",
        "increase in shareholding",
        "acquire shares",
        "供股",
        "配售",
        "增持",
    ]
    if any(word in lower_title for word in skip_words):
        return not any(word in lower_title for word in strong_words)
    return False


def get_hkexnews_json_urls() -> list[str]:
    range_flag = "7" if ANNOUNCEMENT_RANGE_DAYS >= 7 else "1"
    first_url = f"{HKEXNEWS_BASE}/ncms/json/eds/lcisehk{range_flag}relsde_1.json"
    try:
        first = requests.get(first_url, timeout=20).json()
        max_files = int(first.get("maxNumOfFile", 1))
    except Exception as exc:
        print(f"HKEXnews first page failed: {exc}")
        max_files = 1
    return [f"{HKEXNEWS_BASE}/ncms/json/eds/lcisehk{range_flag}relsde_{page}.json" for page in range(1, max_files + 1)]


def fetch_corp_action_announcements() -> list[dict[str, Any]]:
    announcements: list[dict[str, Any]] = []
    for url in get_hkexnews_json_urls():
        try:
            rows = requests.get(url, timeout=20).json().get("newsInfoLst", [])
        except Exception as exc:
            print(f"HKEXnews JSON failed: {url} {exc}")
            continue
        for row in rows:
            if str(row.get("t1Code", "")) != "10000":
                continue
            headline = html_to_text(row.get("lTxt", ""))
            short_headline = html_to_text(row.get("sTxt", ""))
            title = html_to_text(row.get("title", ""))
            if should_skip_announcement_title(title):
                continue
            combined = f"{headline} {short_headline} {title}"
            action_types = classify_corp_action(combined)
            if not action_types:
                continue
            web_path = str(row.get("webPath", ""))
            doc_url = web_path if web_path.startswith("http") else HKEXNEWS_BASE + web_path
            for stock in row.get("stock", []):
                code = str(stock.get("sc", "")).zfill(5)
                name = html_to_text(stock.get("sn", ""))
                announcements.append({
                    "code": code,
                    "name": name,
                    "types": action_types,
                    "title": title or headline,
                    "release_time": row.get("relTime", ""),
                    "url": doc_url,
                })
    print(f"HKEXnews hits: {len(announcements)}")
    return announcements


def run_corp_actions() -> None:
    send_telegram(f"<b>披露易公告雲端掃描開始</b>\\n時間：{datetime.now():%Y-%m-%d %H:%M}\\n類型：供股 / 配股 / 股東增持")
    anns = fetch_corp_action_announcements()
    if not anns:
        send_telegram("披露易公告掃描完成，暫時沒有供股 / 配股 / 股東增持相關公告。")
        return
    for ann in anns:
        types = " / ".join(ann["types"])
        payload = {
            "source": "hkexnews",
            "category": "corp_action",
            "code": ann["code"],
            "symbol": hk_code_to_yahoo(ann["code"]),
            "name": ann["name"],
            "signal": f"披露易公告 - {types}",
            "timeframe": "公告",
            "message": ann["title"],
            "strategy": "HKEXnews Corp Action",
            "chart_url": tradingview_url(ann["code"]),
            "source_url": ann["url"],
            "tags": ["公告", *ann["types"]],
            "priority": 1,
            "raw": json.dumps(ann, ensure_ascii=False),
        }
        msg = (
            f"<b>港交所披露易 - {types}</b>\\n\\n"
            f"代號：{ann['code']} {ann['name']}\\n"
            f"{ann['title']}\\n"
            f"時間：{ann['release_time']}\\n"
            f"查看原文：{ann['url']}"
        )
        emit_alert(payload, msg)
        time.sleep(0.5)
    send_telegram(f"披露易公告掃描完成，共 {len(anns)} 則命中。")


def clean_stock_list(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["code", "name"]].copy()
    df["code"] = df["code"].astype(str).str.replace(".0", "", regex=False).str.strip().str.zfill(5)
    df["name"] = df["name"].astype(str).str.strip()
    df = df.dropna(subset=["code", "name"])
    df = df[df["code"].str.match(r"^\\d{5}$")]
    df = df[df["name"] != ""]
    df = df[df["code"].astype(int) <= 9999]
    return df.drop_duplicates(subset=["code"]).reset_index(drop=True)


def get_hk_stock_list() -> pd.DataFrame:
    df = pd.read_excel(HKEX_LIST_URL, header=2)
    df = df[df["Category"].astype(str).str.strip() == "Equity"].copy()
    if "Trading Currency" in df.columns:
        df = df[df["Trading Currency"].astype(str).str.strip() == "HKD"].copy()
    df = df[["Stock Code", "Name of Securities"]].copy()
    df.columns = ["code", "name"]
    out = clean_stock_list(df)
    if MAX_STOCKS > 0:
        out = out.head(MAX_STOCKS).copy()
    print(f"HK stock count: {len(out)}")
    return out


def normalize_yfinance_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    required = ["date", "open", "high", "low", "close", "volume"]
    if any(col not in df.columns for col in required):
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[df["close"] > 0]
    df["volume"] = df["volume"].fillna(0)
    return df.sort_values("date").reset_index(drop=True)


def get_daily_history(code: str, period: str) -> pd.DataFrame:
    ticker = hk_code_to_yahoo(code)
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            raw = yf.download(ticker, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
            df = normalize_yfinance_df(raw)
            if not df.empty:
                return df
        except Exception as exc:
            print(f"{code} {ticker} yfinance failed {attempt}/{RETRY_COUNT}: {exc}")
        if attempt < RETRY_COUNT:
            time.sleep(RETRY_SLEEP)
    return pd.DataFrame()


def calculate_poc(profile_df: pd.DataFrame) -> float | None:
    if profile_df.empty:
        return None
    low = profile_df["low"].min()
    high = profile_df["high"].max()
    if pd.isna(low) or pd.isna(high) or high <= low:
        return None
    bins = pd.interval_range(start=low, end=high, periods=POC_BINS)
    typical_price = (profile_df["high"] + profile_df["low"] + profile_df["close"]) / 3
    bucket = pd.cut(typical_price, bins)
    volume_by_bucket = profile_df.groupby(bucket, observed=False)["volume"].sum()
    if volume_by_bucket.empty:
        return None
    poc_interval = volume_by_bucket.idxmax()
    if pd.isna(poc_interval):
        return None
    return round((poc_interval.left + poc_interval.right) / 2, 4)


def check_ipo_breakout(code: str, name: str) -> dict[str, Any] | None:
    df = get_daily_history(code, YF_IPO_PERIOD)
    if df.empty or len(df) < MIN_LISTING_DAYS:
        return None
    listing_days = len(df)
    if MAX_LISTING_DAYS > 0 and listing_days > MAX_LISTING_DAYS:
        return None
    ipo_high = df.iloc[0]["high"]
    prev_high = df.iloc[-2]["high"]
    today = df.iloc[-1]
    if today["high"] > ipo_high and prev_high <= ipo_high and ipo_high > 0:
        return {
            "Code": code,
            "Name": name,
            "IPO Date": df.iloc[0]["date"].strftime("%Y-%m-%d"),
            "Listed Days": listing_days,
            "IPO High": round(ipo_high, 3),
            "Today High": round(today["high"], 3),
            "Today Close": round(today["close"], 3),
            "Break %": round((today["high"] / ipo_high - 1) * 100, 2),
            "Data Date": today["date"].strftime("%Y-%m-%d"),
        }
    return None


def check_poc_breakout(code: str, name: str) -> dict[str, Any] | None:
    df = get_daily_history(code, YF_POC_PERIOD)
    min_needed = max(POC_LOOKBACK_DAYS_6M, POC_LOOKBACK_DAYS_12M) + 2
    if df.empty or len(df) < min_needed:
        return None
    field = BREAKOUT_FIELD if BREAKOUT_FIELD in ["high", "close"] else "high"
    today = df.iloc[-1]
    prev = df.iloc[-2]
    today_value = today[field]
    prev_value = prev[field]
    poc_results: list[dict[str, Any]] = []
    for label, lookback_days in [("半年POC", POC_LOOKBACK_DAYS_6M), ("12個月POC", POC_LOOKBACK_DAYS_12M)]:
        profile_df = df.iloc[-(lookback_days + 1):-1].copy()
        poc = calculate_poc(profile_df)
        if poc is None or poc <= 0:
            continue
        crossed = today_value > poc and prev_value <= poc
        poc_results.append({"label": label, "poc": round(poc, 3), "break_pct": round((today_value / poc - 1) * 100, 2), "crossed": crossed})
    crossed = [x for x in poc_results if x["crossed"]]
    if not crossed:
        return None
    main = crossed[0]
    return {
        "Code": code,
        "Name": name,
        "Signal": " + ".join(x["label"] for x in crossed),
        "POC": main["poc"],
        "POC 6M": next((x["poc"] for x in poc_results if x["label"] == "半年POC"), None),
        "POC 12M": next((x["poc"] for x in poc_results if x["label"] == "12個月POC"), None),
        "Today High": round(today["high"], 3),
        "Today Close": round(today["close"], 3),
        "Break Field": field,
        "Break Value": round(today_value, 3),
        "Break %": main["break_pct"],
        "Data Date": today["date"].strftime("%Y-%m-%d"),
    }


def run_ipo() -> None:
    send_telegram(f"<b>IPO首日突破雲端掃描開始</b>\\n時間：{datetime.now():%Y-%m-%d %H:%M}\\n資料源：HKEX + Yahoo Finance")
    stocks = get_hk_stock_list()
    hits = 0
    for n, row in enumerate(stocks.to_dict("records"), start=1):
        if n % 100 == 0:
            print(f"IPO progress {n}/{len(stocks)} hits={hits}")
        result = check_ipo_breakout(row["code"], row["name"])
        if result:
            hits += 1
            code = result["Code"]
            payload = {
                "source": "cloud_scanner",
                "category": "ipo",
                "code": code,
                "symbol": hk_code_to_yahoo(code),
                "name": result["Name"],
                "signal": "IPO首日高突破",
                "timeframe": "1D",
                "price": result["Today Close"],
                "message": f"IPO日期：{result['IPO Date']}；IPO首日高：{result['IPO High']}；今日最高：{result['Today High']}；突破幅度：{result['Break %']}%",
                "strategy": "IPO First Day High Breakout",
                "chart_url": tradingview_url(code),
                "source_url": tradingview_url(code),
                "tags": ["IPO", "Breakout"],
                "priority": 2,
                "raw": json.dumps(result, ensure_ascii=False),
            }
            msg = (
                f"<b>IPO首日突破</b>\\n"
                f"股票：{code} {result['Name']}\\n"
                f"IPO日期：{result['IPO Date']}（資料交易日{result['Listed Days']}日）\\n"
                f"IPO首日高：{result['IPO High']}\\n"
                f"今日最高：{result['Today High']}\\n"
                f"今日收市：{result['Today Close']}\\n"
                f"突破幅度：{result['Break %']}%\\n"
                f"圖表：{tradingview_url(code)}"
            )
            emit_alert(payload, msg)
        time.sleep(SLEEP_SEC)
    send_telegram(f"IPO首日突破雲端掃描完成，共 {hits} 隻符合。")


def run_poc() -> None:
    send_telegram(f"<b>POC突破雲端掃描開始</b>\\n時間：{datetime.now():%Y-%m-%d %H:%M}\\n條件：突破半年或12個月 POC")
    stocks = get_hk_stock_list()
    hits = 0
    for n, row in enumerate(stocks.to_dict("records"), start=1):
        if n % 100 == 0:
            print(f"POC progress {n}/{len(stocks)} hits={hits}")
        result = check_poc_breakout(row["code"], row["name"])
        if result:
            hits += 1
            code = result["Code"]
            payload = {
                "source": "cloud_scanner",
                "category": "poc",
                "code": code,
                "symbol": hk_code_to_yahoo(code),
                "name": result["Name"],
                "signal": result["Signal"],
                "timeframe": "1D",
                "price": result["Today Close"],
                "message": f"突破欄位：{result['Break Field']}；突破價：{result['Break Value']}；今日最高：{result['Today High']}；突破幅度：{result['Break %']}%",
                "strategy": "POC Breakout",
                "chart_url": tradingview_url(code),
                "source_url": tradingview_url(code),
                "tags": ["POC", "Breakout", result["Signal"]],
                "poc_6m": result["POC 6M"],
                "poc_12m": result["POC 12M"],
                "priority": 2 if " + " in result["Signal"] else 1,
                "raw": json.dumps(result, ensure_ascii=False),
            }
            msg = (
                f"<b>POC突破</b>\\n"
                f"股票：{code} {result['Name']}\\n"
                f"資料日期：{result['Data Date']}\\n"
                f"訊號：{result['Signal']}\\n"
                f"半年POC：{result['POC 6M']}\\n"
                f"12個月POC：{result['POC 12M']}\\n"
                f"今日最高：{result['Today High']}\\n"
                f"今日收市：{result['Today Close']}\\n"
                f"突破幅度：{result['Break %']}%\\n"
                f"圖表：{tradingview_url(code)}"
            )
            emit_alert(payload, msg)
        time.sleep(SLEEP_SEC)
    send_telegram(f"POC突破雲端掃描完成，共 {hits} 隻符合。")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "corp":
        run_corp_actions()
    elif mode == "ipo":
        run_ipo()
    elif mode == "poc":
        run_poc()
    elif mode == "all":
        run_corp_actions()
        run_ipo()
        run_poc()
    else:
        raise SystemExit("Usage: python scanner/hk_cloud_scanner.py [corp|ipo|poc|all]")


if __name__ == "__main__":
    main()
