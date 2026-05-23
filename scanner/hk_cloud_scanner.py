"""
HK Alert Cloud Scanner

Cloud version for GitHub Actions:
- No AKShare
- HK stock list from HKEX official ListOfSecurities.xlsx
- Price history from Yahoo Finance / yfinance
- Alerts to Telegram (single message per alert, with chart image when feasible)
  and Google Apps Script webhook (chart PNG sent base64 so GAS can host it on Drive)

Signals:
1. IPO first-day high breakout
2. POC breakout (6M / 12M / 3Y)
3. HKEXnews corporate action: rights issue / placing / shareholder increase
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import sys
import tempfile
import time
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

# Matplotlib is optional - if it fails to import we fall back to text-only alerts.
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    _MPL_OK = True
except Exception as _mpl_exc:  # pragma: no cover
    print(f"[chart] matplotlib unavailable: {_mpl_exc}")
    _MPL_OK = False

HKEX_LIST_URL = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
HKEX_LIST_URL_CN = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
HKEXNEWS_BASE = "https://www.hkexnews.hk"

MAX_STOCKS = int(os.getenv("MAX_STOCKS", "0"))
# POC-specific cap. If unset, falls back to MAX_STOCKS. 0 = no cap.
POC_MAX_STOCKS_PER_RUN = int(os.getenv("POC_MAX_STOCKS_PER_RUN", "0"))
# Sharding: split the HK stock universe into POC_SHARD_COUNT contiguous slices
# and only scan slice POC_SHARD_INDEX (0-based). 1/0 = scan everything.
POC_SHARD_COUNT = max(int(os.getenv("POC_SHARD_COUNT", "1")), 1)
POC_SHARD_INDEX = max(int(os.getenv("POC_SHARD_INDEX", "0")), 0)
MIN_LISTING_DAYS = int(os.getenv("MIN_LISTING_DAYS", "5"))
MAX_LISTING_DAYS = int(os.getenv("MAX_LISTING_DAYS", "0"))
POC_LOOKBACK_DAYS_6M = int(os.getenv("POC_LOOKBACK_DAYS_6M", "126"))
POC_LOOKBACK_DAYS_12M = int(os.getenv("POC_LOOKBACK_DAYS_12M", "252"))
POC_LOOKBACK_DAYS_3Y = int(os.getenv("POC_LOOKBACK_DAYS_3Y", "756"))
POC_BINS = int(os.getenv("POC_BINS", "80"))
BREAKOUT_FIELD = os.getenv("BREAKOUT_FIELD", "high").lower().strip()
ANNOUNCEMENT_RANGE_DAYS = int(os.getenv("ANNOUNCEMENT_RANGE_DAYS", "7"))
SLEEP_SEC = float(os.getenv("SLEEP_SEC", "0.0"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "1"))
RETRY_SLEEP = int(os.getenv("RETRY_SLEEP", "2"))
# Per-HTTP-request timeout for yfinance calls. Caps how long any one ticker can hang.
YF_HTTP_TIMEOUT = float(os.getenv("YF_HTTP_TIMEOUT", "10"))
YF_IPO_PERIOD = os.getenv("YF_IPO_PERIOD", "max")
YF_POC_PERIOD = os.getenv("YF_POC_PERIOD", "4y")
# Batch size for yfinance multi-ticker downloads (POC scan). Yahoo accepts large batches
# but very large ones increase per-request cost and reduce parallelism benefits.
YF_BATCH_SIZE = int(os.getenv("YF_BATCH_SIZE", "60"))
YF_BATCH_THREADS = int(os.getenv("YF_BATCH_THREADS", "8"))
# Hard wall-clock budget for the POC scan (seconds). 0 = no budget.
POC_TIME_BUDGET_SEC = int(os.getenv("POC_TIME_BUDGET_SEC", "1500"))
CHART_LOOKBACK_DAYS = int(os.getenv("CHART_LOOKBACK_DAYS", "180"))
# Cap base64 image size sent to GAS so we don't blow up the Drive upload payload.
GAS_CHART_MAX_BYTES = int(os.getenv("GAS_CHART_MAX_BYTES", "350000"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
GAS_SECRET = os.getenv("GAS_SECRET", "")

WATCHLIST_EXPIRY_DAYS = int(os.getenv("WATCHLIST_EXPIRY_DAYS", "5"))
VOLUME_MULTIPLIER = float(os.getenv("VOLUME_MULTIPLIER", "1.5"))
VOLUME_AVG_DAYS = int(os.getenv("VOLUME_AVG_DAYS", "20"))

# ── Futu OpenD settings ────────────────────────────────────────────────────────
# Set USE_FUTU=true to use FutuOpenD as primary data source (falls back to
# yfinance if OpenD is unavailable or a fetch fails).
# FutuOpenD must be running at FUTU_HOST:FUTU_PORT.  Default: localhost:11111.
USE_FUTU = os.getenv("USE_FUTU", "false").lower() in ("1", "true", "yes")
FUTU_HOST = os.getenv("FUTU_HOST", "127.0.0.1")
FUTU_PORT = int(os.getenv("FUTU_PORT", "11111"))

try:
    from futu import OpenQuoteContext, KLType, AuType, KL_FIELD, RET_OK as _FUTU_RET_OK  # type: ignore
    _FUTU_AVAILABLE = True
except ImportError:
    _FUTU_AVAILABLE = False
    if USE_FUTU:
        print("[futu] futu-api not installed; falling back to yfinance. pip install futu-api")

# Telegram caption max length is 1024 chars for photos, 4096 for text messages.
_TG_CAPTION_LIMIT = 1024

# Corp action types that always trigger an immediate alert regardless of volume.
_IMMEDIATE_ALERT_TYPES: frozenset[str] = frozenset({"股東增持"})

# Alert priority by corp action type (higher = more urgent).
_CORP_TYPE_PRIORITY: dict[str, int] = {
    "股東增持": 3,
    "大手轉倉": 2,
    "供股": 2,
    "配股": 1,
}


def hk_code_to_yahoo(code: str) -> str:
    code = str(code).strip().zfill(5)
    return f"{code[-4:]}.HK"


def tradingview_url(code: str) -> str:
    symbol = hk_code_to_yahoo(code).replace(".HK", "")
    return f"https://www.tradingview.com/chart/?symbol=HKEX%3A{symbol}"


def get_year_open_price(df: pd.DataFrame) -> float | None:
    """Return the current year's first trading-day open price."""
    if df is None or df.empty or "open" not in df.columns or "date" not in df.columns:
        return None
    current_year = datetime.now(HKT_TZ).year
    year_data = df[df["date"].dt.year == current_year]
    if year_data.empty:
        return None
    return round(float(year_data.iloc[0]["open"]), 3)


def get_prev_week_low(df: pd.DataFrame) -> float | None:
    """Return the lowest low of the previous complete trading week (Mon–Fri).

    Uses HKT 'today' to determine week boundaries.  Returns None if no data
    exists for that period (e.g. newly-listed stock or df is empty).
    """
    if df is None or df.empty or "low" not in df.columns or "date" not in df.columns:
        return None
    today = datetime.now(HKT_TZ).date()
    days_since_monday = today.weekday()          # Mon=0 … Sun=6
    current_monday = today - timedelta(days=days_since_monday)
    prev_monday = current_monday - timedelta(days=7)
    prev_sunday = current_monday - timedelta(days=1)   # Fri is the last trading day
    mask = (df["date"].dt.date >= prev_monday) & (df["date"].dt.date <= prev_sunday)
    prev_week = df[mask]
    if prev_week.empty:
        return None
    return round(float(prev_week["low"].min()), 3)


def sl_yr_line(pw_low: float | None, price: float, df: pd.DataFrame) -> str:
    """Return the stop-loss + year-open indicator line, or empty string if no data."""
    yr_open = get_year_open_price(df)
    if yr_open is not None:
        yr_mark = f" 🔺高於年開：{yr_open}" if price > yr_open else f" 🔻低於年開：{yr_open}"
    else:
        yr_mark = ""
    if pw_low is not None:
        return f"止蝕：{pw_low}{yr_mark}"
    if yr_mark:
        return yr_mark.strip()
    return ""


def build_inline_keyboard_(buttons: list[tuple[str, str]]) -> dict:
    """Build a single-row Telegram InlineKeyboardMarkup from (text, url) pairs."""
    return {"inline_keyboard": [[{"text": t, "url": u} for t, u in buttons]]}


def send_telegram_message(message: str, reply_markup: dict | None = None) -> bool:
    """Send a plain HTML text message (used for scan-status pings only)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200:
            print("[Telegram] message sent")
            return True
        print(f"[Telegram] message failed: {r.status_code} {r.text[:300]}")
    except Exception as exc:
        print(f"[Telegram] message error: {exc}")
    return False


def send_telegram_photo(photo_path: str, caption: str, reply_markup: dict | None = None) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    if len(caption) > _TG_CAPTION_LIMIT:
        caption = caption[: _TG_CAPTION_LIMIT - 1] + "…"
    try:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data: dict[str, Any] = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            r = requests.post(url, data=data, files=files, timeout=30)
        if r.status_code == 200:
            print("[Telegram] photo sent")
            return True
        print(f"[Telegram] photo failed: {r.status_code} {r.text[:300]}")
    except Exception as exc:
        print(f"[Telegram] photo error: {exc}")
    return False


def send_telegram_alert(caption_html: str, photo_path: str | None, reply_markup: dict | None = None) -> bool:
    """Single Telegram alert: photo+caption when chart is available, otherwise one text message."""
    if photo_path and os.path.exists(photo_path):
        if send_telegram_photo(photo_path, caption_html, reply_markup=reply_markup):
            return True
        # Photo failed - fall back to one text message.
    return send_telegram_message(caption_html, reply_markup=reply_markup)


def post_gas_alert(payload: dict[str, Any]) -> bool:
    if not GAS_WEBHOOK_URL:
        print("[GAS] GAS_WEBHOOK_URL not configured")
        return False
    body = dict(payload)
    if GAS_SECRET:
        body["secret"] = GAS_SECRET
    try:
        r = requests.post(GAS_WEBHOOK_URL, json=body, timeout=30)
        if r.status_code == 200:
            print("[GAS] posted")
            return True
        print(f"[GAS] failed: {r.status_code} {r.text[:300]}")
    except Exception as exc:
        print(f"[GAS] error: {exc}")
    return False


def encode_chart_for_gas(chart_path: str | None) -> tuple[str | None, str | None]:
    """Return (base64-encoded PNG bytes, filename) for embedding in GAS payload.
    None if the file is missing or larger than GAS_CHART_MAX_BYTES."""
    if not chart_path or not os.path.exists(chart_path):
        return None, None
    try:
        size = os.path.getsize(chart_path)
        if size > GAS_CHART_MAX_BYTES:
            print(f"[chart] skip GAS upload, {size}B > {GAS_CHART_MAX_BYTES}B")
            return None, None
        with open(chart_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return data, os.path.basename(chart_path)
    except Exception as exc:
        print(f"[chart] encode failed: {exc}")
        return None, None


def _cleanup_chart(chart_path: str | None) -> None:
    if chart_path:
        try:
            os.remove(chart_path)
        except OSError:
            pass


def _is_above_year_open(df: pd.DataFrame) -> bool | None:
    """Check if latest close > current year's first trading day open.
    Returns None if can't determine (insufficient data / no current-year rows)."""
    if df is None or df.empty or len(df) < 2:
        return None
    current_year = datetime.now(HKT_TZ).year
    year_mask = df["date"].dt.year == current_year
    year_data = df[year_mask]
    if year_data.empty:
        return None
    year_open = float(year_data.iloc[0]["open"])
    if year_open <= 0:
        return None
    today_close = float(df.iloc[-1]["close"])
    return today_close > year_open


def emit_alert(payload: dict[str, Any], caption_html: str, chart_path: str | None, reply_markup: dict | None = None, df: pd.DataFrame | None = None) -> None:
    payload.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    chart_b64, chart_name = encode_chart_for_gas(chart_path)
    if chart_b64:
        payload["chart_image_b64"] = chart_b64
        payload["chart_image_name"] = chart_name
    post_gas_alert(payload)

    # -- year-open filter: skip Telegram for stocks below current-year first-day open --
    if df is not None:
        above = _is_above_year_open(df)
        if above is False:
            code = payload.get("code", "?")
            print(f"[filter] {code} below year-open, skip Telegram")
            _cleanup_chart(chart_path)
            return

    send_telegram_alert(caption_html, chart_path, reply_markup=reply_markup)
    _cleanup_chart(chart_path)


def compute_volume_ratio(df: pd.DataFrame) -> float | None:
    """Return today's volume divided by the VOLUME_AVG_DAYS-day average. None if insufficient data."""
    if df.empty or len(df) < VOLUME_AVG_DAYS + 2:
        return None
    today_vol = float(df.iloc[-1]["volume"])
    hist = df.iloc[-(VOLUME_AVG_DAYS + 1):-1]["volume"].dropna()
    avg = float(hist.mean()) if not hist.empty else 0.0
    if avg == 0:
        return None
    return round(today_vol / avg, 2)


def format_volume_ratio(ratio: float | None) -> str:
    """Format volume ratio as a display string for Telegram captions."""
    if ratio is None:
        return ""
    if ratio >= 2.0:
        return f"量比：🔥 {ratio:.1f}x"
    if ratio >= VOLUME_MULTIPLIER:
        return f"量比：⬆️ {ratio:.1f}x"
    return f"量比：⬇️ {ratio:.1f}x"


def fetch_watchlist_from_gas() -> dict[str, dict]:
    """Fetch active watched stocks from GAS. Returns {code: entry} dict."""
    if not GAS_WEBHOOK_URL:
        return {}
    params: dict[str, str] = {"mode": "watchlist"}
    if GAS_SECRET:
        params["secret"] = GAS_SECRET
    try:
        r = requests.get(GAS_WEBHOOK_URL, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            entries = data if isinstance(data, list) else data.get("watchlist", [])
            out: dict[str, dict] = {}
            if isinstance(entries, dict):
                # Already a {code: entry} map
                for code, entry in entries.items():
                    out[str(code).zfill(5)] = entry
            else:
                for entry in entries:
                    code = str(entry.get("code", "")).zfill(5)
                    if code:
                        out[code] = entry
            print(f"[watchlist] fetched {len(out)} active entries")
            return out
    except Exception as exc:
        print(f"[watchlist] fetch failed: {exc}")
    return {}


def post_watchlist_to_gas(code: str, name: str, types: list[str], ann_date: str) -> None:
    """Add a stock to the GAS watchlist for N-day follow-up tracking."""
    if not GAS_WEBHOOK_URL:
        return
    body: dict[str, Any] = {
        "type": "watchlist",
        "code": code,
        "name": name,
        "types": types,
        "ann_date": ann_date,
        "expiry_days": WATCHLIST_EXPIRY_DAYS,
    }
    if GAS_SECRET:
        body["secret"] = GAS_SECRET
    try:
        r = requests.post(GAS_WEBHOOK_URL, json=body, timeout=15)
        if r.status_code == 200:
            print(f"[watchlist] added {code} ({', '.join(types)})")
        else:
            print(f"[watchlist] add failed {code}: {r.status_code} {r.text[:200]}")
    except Exception as exc:
        print(f"[watchlist] add error {code}: {exc}")


def render_chart(
    df: pd.DataFrame,
    code: str,
    name: str,
    title_suffix: str,
    levels: list[tuple[str, float, str]] | None = None,
    lookback_days: int | None = None,
) -> str | None:
    """Render an OHLC candlestick chart with horizontal reference levels.

    levels: list of (label, price, color)
    Returns the saved PNG path, or None if rendering failed.
    """
    if not _MPL_OK or df is None or df.empty:
        return None
    try:
        plot_df = df.copy()
        if lookback_days and len(plot_df) > lookback_days:
            plot_df = plot_df.iloc[-lookback_days:].copy()
        if plot_df.empty:
            return None
        plot_df = plot_df.reset_index(drop=True)

        fig, ax = plt.subplots(figsize=(8, 4.2), dpi=110)
        fig.patch.set_facecolor("#0b1220")
        ax.set_facecolor("#0b1220")

        # Candlesticks drawn against integer x positions for compactness.
        width = 0.6
        for i, row in plot_df.iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            up = c >= o
            color = "#22c55e" if up else "#ef4444"
            ax.vlines(i, l, h, color=color, linewidth=0.8)
            body_low = min(o, c)
            body_h = max(abs(c - o), (h - l) * 0.001 if h > l else 0.0001)
            ax.add_patch(
                Rectangle(
                    (i - width / 2, body_low),
                    width,
                    body_h,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.5,
                )
            )

        # Horizontal reference lines (POC / IPO high / etc.).
        for entry in levels or []:
            label, price = entry[0], entry[1]
            color = entry[2] if len(entry) > 2 else "#f59e0b"
            lw = entry[3] if len(entry) > 3 else 1.2
            ls = entry[4] if len(entry) > 4 else "--"
            if price is None or pd.isna(price):
                continue
            ax.axhline(price, color=color, linewidth=lw, linestyle=ls, alpha=0.9)
            ax.text(
                len(plot_df) - 1,
                price,
                f" {label} {price:.3f}",
                color=color,
                fontsize=8,
                va="bottom",
                ha="right",
            )

        # X tick labels: a handful of dates.
        n = len(plot_df)
        tick_idx = list(range(0, n, max(1, n // 6)))
        if tick_idx[-1] != n - 1:
            tick_idx.append(n - 1)
        ax.set_xticks(tick_idx)
        ax.set_xticklabels(
            [plot_df["date"].iloc[i].strftime("%Y-%m-%d") for i in tick_idx],
            color="#94a3b8",
            fontsize=8,
            rotation=0,
        )
        ax.tick_params(axis="y", colors="#94a3b8", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#1f2937")
        ax.grid(True, color="#1f2937", linewidth=0.5, alpha=0.6)
        ax.set_xlim(-1, n)
        ax.invert_yaxis()   # 反轉 Y 軸刻度（高位在上、低位在下，傳統金融圖表方向）

        title = f"{code} {name} · {title_suffix}"
        ax.set_title(title, color="#e5e7eb", fontsize=11, loc="left", pad=10)
        fig.tight_layout()

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fig.savefig(tmp.name, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        return tmp.name
    except Exception as exc:
        print(f"[chart] render failed for {code}: {exc}")
        try:
            plt.close("all")
        except Exception:
            pass
        return None


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
    "大手轉倉": [
        "block trade",
        "off-market transfer",
        "off-exchange transfer",
        "transfer of shares",
        "transfer of beneficial interest",
        "大手轉倉",
        "大宗交易",
        "場外轉讓",
        "股份轉讓",
    ],
}

# Short labels shown alongside POC alerts. Map the full classification key to
# the concise label the user wants to see in Telegram.
POC_ANNOUNCEMENT_LABELS = {
    "供股": "供股",
    "配股": "配股",
    "股東增持": "增持",
    "大手轉倉": "大手轉倉",
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
        "block trade",
        "off-market transfer",
        "off-exchange transfer",
        "供股",
        "配售",
        "增持",
        "大手轉倉",
        "大宗交易",
        "場外轉讓",
    ]
    if any(word in lower_title for word in skip_words):
        return not any(word in lower_title for word in strong_words)
    return False


# Ordered phrase map for English -> Traditional Chinese normalization of HKEXnews
# corporate-action announcement titles. Order matters: longer / more specific
# phrases must appear before their shorter substrings (e.g. "PLACING OF NEW SHARES"
# before "PLACING"). Keys are lower-cased for case-insensitive matching.
TITLE_PHRASE_MAP: list[tuple[str, str]] = [
    # Specific multi-word phrases first
    ("very substantial acquisition", "非常重大收購"),
    ("very substantial disposal", "非常重大出售"),
    ("major transaction", "主要交易"),
    ("discloseable transaction", "須予披露交易"),
    ("connected transaction", "關連交易"),
    ("supplemental announcement in relation to", "補充公告："),
    ("supplemental announcement", "補充公告"),
    ("clarification announcement", "澄清公告"),
    ("further announcement in relation to", "進一步公告："),
    ("further announcement", "進一步公告"),
    ("inside information", "內幕消息"),
    ("voluntary announcement", "自願公告"),
    ("announcement in relation to", "公告："),
    ("in relation to", "有關"),
    ("under specific mandate", "（特別授權）"),
    ("under general mandate", "（一般授權）"),
    ("specific mandate", "特別授權"),
    ("general mandate", "一般授權"),
    # Placing / subscription / issuance
    ("completion of placing", "配股完成"),
    ("completion of the placing", "配股完成"),
    ("completion of subscription", "認購完成"),
    ("termination of placing", "終止配股"),
    ("termination of the placing", "終止配股"),
    ("termination of issue of shares", "終止發行股份"),
    ("termination of issue", "終止發行"),
    ("placing of new shares", "配售新股"),
    ("placing of shares", "配售股份"),
    ("placing agreement", "配售協議"),
    ("subscription of new shares", "認購新股"),
    ("subscription agreement", "認購協議"),
    ("issue of new shares", "發行新股"),
    ("issue of shares", "發行股份"),
    ("placing", "配股"),
    # Rights issue / open offer
    ("rights issue", "供股"),
    ("open offer", "公開發售"),
    # Repurchases
    ("share repurchase", "股份回購"),
    ("repurchase mandate", "回購授權"),
    ("repurchase of shares", "股份回購"),
    ("buy-back", "回購"),
    ("buyback", "回購"),
    # Shareholding changes
    ("proposed shareholding increase", "擬增持"),
    ("shareholding increase", "股東增持"),
    ("increase in shareholding", "股東增持"),
    ("rights to acquire shares", "認購股份權利"),
    ("acquire shares", "收購股份"),
    # Block trade / off-market
    ("block trade", "大手轉倉"),
    ("off-market transfer", "場外轉讓"),
    ("off-exchange transfer", "場外轉讓"),
    ("transfer of beneficial interest", "實益權益轉讓"),
    ("transfer of shares", "股份轉讓"),
    # Generic announcement glue words (last so above wins)
    ("announcement", "公告"),
]

_GENERIC_TITLE_FALLBACK = "公司公告"
_TITLE_MAX_LEN = 80


def translate_title_cn(title: str) -> str:
    """Translate / normalize an HKEXnews English title into concise Traditional Chinese.

    Rule-based: replaces known phrases, then strips residual ASCII words. If the
    output ends up empty or still mostly English, falls back to a generic
    "公司公告：<original>" form so we never silently drop information.
    """
    if not title:
        return ""
    raw = " ".join(str(title).split())
    # If the title is already mostly Chinese, pass it through unchanged (trimmed).
    han_count = sum(1 for ch in raw if "一" <= ch <= "鿿")
    if han_count >= 2 and han_count >= len(raw.replace(" ", "")) * 0.5:
        return raw[:_TITLE_MAX_LEN] + ("…" if len(raw) > _TITLE_MAX_LEN else "")

    working = raw
    lower = working.lower()
    # Replace phrases case-insensitively while preserving non-matching segments.
    out_parts: list[str] = []
    i = 0
    while i < len(working):
        matched = False
        for needle, repl in TITLE_PHRASE_MAP:
            if lower.startswith(needle, i):
                out_parts.append(repl)
                i += len(needle)
                matched = True
                break
        if not matched:
            out_parts.append(working[i])
            i += 1
    translated = "".join(out_parts)

    # Clean up: collapse whitespace, drop stray ASCII connector words.
    translated = " ".join(translated.split())
    # Strip residual standalone English connectors that look noisy in Chinese text.
    for junk in [" of ", " the ", " a ", " an ", " and ", " for ", " to ", " in ", " on "]:
        translated = translated.replace(junk, "")
    translated = translated.replace(" ：", "：").replace("： ", "：")
    translated = translated.replace(" （", "（").replace("） ", "）")
    translated = " ".join(translated.split()).strip(" :,-")

    # If translation still looks mostly English, fall back to generic form.
    han_after = sum(1 for ch in translated if "一" <= ch <= "鿿")
    ascii_letters = sum(1 for ch in translated if ch.isascii() and ch.isalpha())
    if not translated or han_after == 0 or ascii_letters > han_after * 2:
        translated = f"{_GENERIC_TITLE_FALLBACK}：{raw}"

    if len(translated) > _TITLE_MAX_LEN:
        translated = translated[: _TITLE_MAX_LEN - 1] + "…"
    return translated


HKT_TZ = timezone(timedelta(hours=8))


def hkt_today_str() -> str:
    return datetime.now(HKT_TZ).strftime("%Y-%m-%d")


def parse_rel_time_date(rel_time: str) -> str | None:
    """Parse HKEXnews relTime ('dd/mm/yyyy HH:MM') to 'YYYY-MM-DD' (HKT, naive).

    Returns None if the value cannot be parsed; callers must treat unparseable
    timestamps as not-same-day rather than fabricating a date.
    """
    if not rel_time:
        return None
    s = str(rel_time).strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


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


def fetch_cn_title_map() -> dict[str, str]:
    """Fetch the HKEXnews Chinese feed and return {webPath: chinese_title}.

    HKEXnews publishes parallel Chinese-language JSON feeds at the same URL
    with prefix 'c' instead of 'l'  (e.g. ccisehk1relsde_1.json).  We use
    these to get the official Traditional-Chinese title for each announcement,
    falling back to rule-based translate_title_cn() when unavailable.
    """
    range_flag = "7" if ANNOUNCEMENT_RANGE_DAYS >= 7 else "1"
    first_url = f"{HKEXNEWS_BASE}/ncms/json/eds/ccisehk{range_flag}relsde_1.json"
    try:
        first = requests.get(first_url, timeout=20).json()
        max_files = int(first.get("maxNumOfFile", 1))
    except Exception as exc:
        print(f"HKEXnews CN first page failed: {exc}")
        return {}
    cn_map: dict[str, str] = {}
    for page in range(1, max_files + 1):
        url = f"{HKEXNEWS_BASE}/ncms/json/eds/ccisehk{range_flag}relsde_{page}.json"
        try:
            rows = requests.get(url, timeout=20).json().get("newsInfoLst", [])
        except Exception as exc:
            print(f"HKEXnews CN page {page} failed: {exc}")
            continue
        for row in rows:
            web_path = str(row.get("webPath", "")).strip()
            if not web_path:
                continue
            cn_title = html_to_text(row.get("title", "")) or html_to_text(row.get("lTxt", ""))
            if cn_title:
                cn_map[web_path] = cn_title
    print(f"HKEXnews CN title map: {len(cn_map)} entries")
    return cn_map


def fetch_corp_action_announcements() -> list[dict[str, Any]]:
    # Fetch Chinese title map first (parallel would be ideal but keep it simple).
    cn_title_map = fetch_cn_title_map()

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
            rel_time = row.get("relTime", "")
            release_date = parse_rel_time_date(rel_time)
            # Use official Chinese title from CN feed; fall back to rule-based translation.
            cn_title = cn_title_map.get(web_path) or translate_title_cn(title or headline)
            for stock in row.get("stock", []):
                code = str(stock.get("sc", "")).zfill(5)
                name = html_to_text(stock.get("sn", ""))
                announcements.append({
                    "code": code,
                    "name": name,
                    "types": action_types,
                    "title": cn_title,
                    "title_en": title or headline,
                    "release_time": rel_time,
                    "release_date": release_date,
                    "url": doc_url,
                })
    print(f"HKEXnews hits: {len(announcements)}")
    return announcements


def run_corp_actions() -> None:
    today_hkt = hkt_today_str()
    send_telegram_message(
        f"<b>披露易掃描開始</b> · {datetime.now(HKT_TZ):%Y-%m-%d %H:%M} HKT\n"
        f"類型：配股 / 供股 / 增持 / 大手轉倉（只發送當日 {today_hkt} 公告）\n"
        f"量比確認：{VOLUME_MULTIPLIER}x · 觀察期：{WATCHLIST_EXPIRY_DAYS} 日"
    )
    raw_anns = fetch_corp_action_announcements()
    # Same-day-only filter: drop anything whose HKT release date is not today.
    anns: list[dict[str, Any]] = []
    skipped_old = 0
    skipped_unknown = 0
    seen_urls: set[str] = set()
    for ann in raw_anns:
        rd = ann.get("release_date")
        if rd is None:
            skipped_unknown += 1
            continue
        if rd != today_hkt:
            skipped_old += 1
            continue
        key = f"{ann.get('code', '')}|{ann.get('url', '')}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        anns.append(ann)
    print(
        f"corp filter: kept={len(anns)} skipped_old={skipped_old} "
        f"skipped_unknown_date={skipped_unknown} today_hkt={today_hkt}"
    )
    if not anns:
        send_telegram_message(f"披露易掃描完成，無 {today_hkt} 當日相關公告。")
        return

    alerted = 0
    watchlisted = 0
    for ann in anns:
        code = ann["code"]
        types_list = ann["types"]
        types = " / ".join(types_list)
        title_cn = ann["title"]  # already Chinese (from CN feed or rule-based fallback)
        ann_date = ann.get("release_date") or ""
        corp_tv_url = tradingview_url(code)

        # Determine priority and whether this type always alerts immediately.
        priority = max((_CORP_TYPE_PRIORITY.get(t, 1) for t in types_list), default=1)
        immediate = any(t in _IMMEDIATE_ALERT_TYPES for t in types_list)

        # Fetch price history once — used for both volume check and chart.
        df: pd.DataFrame = pd.DataFrame()
        vol_ratio: float | None = None
        try:
            df = get_daily_history(code, "1y")
            if not df.empty:
                vol_ratio = compute_volume_ratio(df)
                if vol_ratio is not None and vol_ratio >= VOLUME_MULTIPLIER:
                    immediate = True
        except Exception as exc:
            print(f"[corp] price fetch failed for {code}: {exc}")

        # Always add to watchlist for N-day follow-up regardless of immediate flag.
        post_watchlist_to_gas(code, ann["name"], types_list, ann_date)
        watchlisted += 1

        if not immediate:
            vol_str = f"{vol_ratio:.1f}x" if vol_ratio is not None else "N/A"
            print(f"[corp] {code} watchlist-only — volume={vol_str} types={types_list}")
            # Post low-priority record to Alerts sheet so it appears in dashboard 最近公告.
            post_gas_alert({
                "source": "hkexnews",
                "category": "corp_action",
                "code": code,
                "symbol": hk_code_to_yahoo(code),
                "name": ann["name"],
                "signal": f"觀察·{types}",
                "timeframe": "公告",
                "message": title_cn,
                "strategy": "HKEXnews Corp Action (觀察)",
                "chart_url": "",
                "source_url": ann["url"],
                "announcement_date": ann_date,
                "release_time": ann.get("release_time", ""),
                "tags": ["公告", "觀察", *types_list],
                "priority": 0,
                "raw": json.dumps(ann, ensure_ascii=False),
            })
            continue

        alerted += 1
        vol_line = format_volume_ratio(vol_ratio)

        payload: dict[str, Any] = {
            "source": "hkexnews",
            "category": "corp_action",
            "code": code,
            "symbol": hk_code_to_yahoo(code),
            "name": ann["name"],
            "signal": f"披露易公告 - {types}",
            "timeframe": "公告",
            "message": title_cn,
            "title_original": ann["title"],
            "strategy": "HKEXnews Corp Action",
            "chart_url": "",
            "source_url": ann["url"],
            "announcement_date": ann_date,
            "release_time": ann.get("release_time", ""),
            "tags": ["公告", *types_list],
            "priority": priority,
            "raw": json.dumps(ann, ensure_ascii=False),
        }
        vol_line_str = f"量比：{vol_line}" if vol_line else ""
        date_vol = f"{ann_date}　{vol_line_str}" if vol_line_str else ann_date
        pw_low = get_prev_week_low(df) if not df.empty else None
        cur_price = float(df.iloc[-1]["close"]) if not df.empty else 0.0
        _sl = sl_yr_line(pw_low, cur_price, df) if not df.empty else ""
        sl_part = f"\n\n{_sl}" if _sl else ""
        caption = (
            f"📰{types}\n"
            f"{date_vol}\n"
            f"{code} {ann['name']}"
            f"{sl_part}"
        )
        corp_kb = build_inline_keyboard_([
            ("📰 披露易", ann["url"]),
            ("📊 走勢圖", corp_tv_url),
        ])
        chart_path: str | None = None
        corp_levels = [("前周低", pw_low, "#ef4444")] if pw_low is not None else []
        try:
            df_weekly = get_weekly_history(code, "2y")
            chart_df = df_weekly if not df_weekly.empty else df
            if not chart_df.empty:
                chart_path = render_chart(
                    chart_df, code, ann["name"],
                    f"披露易 · {types}（周線）",
                    levels=corp_levels,
                    lookback_days=None,
                )
        except Exception as exc:
            print(f"[chart] corp action chart failed for {code}: {exc}")
        emit_alert(payload, caption, chart_path, reply_markup=corp_kb)
        time.sleep(0.5)

    send_telegram_message(
        f"披露易掃描完成：即時提醒 {alerted} 則，加入觀察 {watchlisted} 則。"
    )

    # ── Save placing/rights history (配股/供股記錄，保留一年) ──────────────
    _save_placing_history(anns)


def _save_placing_history(anns: list[dict[str, Any]]) -> None:
    """Append 配股/供股 announcements to placing_history.json, keep 365 days."""
    placing_types = {"配股", "供股"}
    new_entries: list[dict] = []
    for ann in anns:
        types = set(ann.get("types", []))
        if not (types & placing_types):
            continue
        new_entries.append({
            "date": ann.get("release_date", ""),
            "code": ann["code"],
            "name": ann.get("name", ""),
            "type": " / ".join(sorted(types & placing_types)),
            "title": ann.get("title", ""),
            "title_en": ann.get("title_en", ""),
            "url": ann.get("url", ""),
        })

    if not new_entries:
        return

    out_path = os.path.join(os.path.dirname(__file__), "..", "placing_history.json")
    existing: dict = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    # Merge: deduplicate by (code, date, type)
    all_entries: list[dict] = existing.get("entries", [])
    seen = {(e["code"], e["date"], e.get("type", "")) for e in all_entries}
    added = 0
    for e in new_entries:
        key = (e["code"], e["date"], e["type"])
        if key not in seen:
            all_entries.append(e)
            seen.add(key)
            added += 1

    # Keep only entries within 365 days
    cutoff = (datetime.now(HKT_TZ) - timedelta(days=365)).strftime("%Y-%m-%d")
    all_entries = [e for e in all_entries if e.get("date", "") >= cutoff]

    # Sort newest first
    all_entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    snapshot = {
        "updated": datetime.now(HKT_TZ).strftime("%Y-%m-%d %H:%M HKT"),
        "count": len(all_entries),
        "entries": all_entries,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"[placing] saved {len(all_entries)} entries ({added} new) → placing_history.json")


def clean_stock_list(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["code", "name"]].copy()
    df["code"] = df["code"].astype(str).str.replace(".0", "", regex=False).str.strip().str.zfill(5)
    df["name"] = df["name"].astype(str).str.strip()
    df = df.dropna(subset=["code", "name"])
    df = df[df["code"].str.match(r"^\d{5}$")]
    df = df[df["name"] != ""]
    df = df[df["code"].astype(int) <= 9999]
    return df.drop_duplicates(subset=["code"]).reset_index(drop=True)


def _fetch_cn_name_map() -> dict[str, str]:
    """Fetch HKEX Chinese securities list; return {zero-padded-code: chinese_name}."""
    try:
        df = pd.read_excel(HKEX_LIST_URL_CN, header=2)
        # Column names are in Chinese; find by keywords.
        code_col = next((c for c in df.columns if any(k in str(c) for k in ["代號", "代码", "Code", "號"])), None)
        name_col = next((c for c in df.columns if any(k in str(c) for k in ["名稱", "名称", "Name"])), None)
        if code_col is None or name_col is None:
            print(f"[cn_names] columns not found: {list(df.columns)}")
            return {}
        df = df[[code_col, name_col]].copy()
        df.columns = ["code", "name"]
        df["code"] = df["code"].astype(str).str.replace(".0", "", regex=False).str.strip().str.zfill(5)
        df["name"] = df["name"].astype(str).str.strip()
        df = df[df["code"].str.match(r"^\d{5}$") & (df["name"] != "") & (df["name"] != "nan")]
        result = dict(zip(df["code"], df["name"]))
        print(f"[cn_names] loaded {len(result)} Chinese names")
        return result
    except Exception as exc:
        print(f"[cn_names] fetch failed: {exc}")
        return {}


def get_hk_stock_list() -> pd.DataFrame:
    df = pd.read_excel(HKEX_LIST_URL, header=2)
    df = df[df["Category"].astype(str).str.strip() == "Equity"].copy()
    if "Trading Currency" in df.columns:
        df = df[df["Trading Currency"].astype(str).str.strip() == "HKD"].copy()
    df = df[["Stock Code", "Name of Securities"]].copy()
    df.columns = ["code", "name"]
    out = clean_stock_list(df)
    # Overwrite English names with official Chinese names from HKEX Chinese list.
    cn_map = _fetch_cn_name_map()
    if cn_map:
        out["name"] = out["code"].map(cn_map).fillna(out["name"])
        merged = out["code"].isin(cn_map).sum()
        print(f"[cn_names] merged {merged}/{len(out)} Chinese company names")
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


def _period_to_years(period: str) -> int:
    """Convert yfinance period string ('4y', 'max', '1y') to integer years for Futu."""
    p = str(period).lower().strip()
    if p == "max":
        return 20
    for suffix, mult in [("y", 1.0), ("mo", 1 / 12.0)]:
        if p.endswith(suffix):
            try:
                return max(1, round(float(p[: -len(suffix)]) * mult))
            except ValueError:
                break
    return 4


def _normalize_futu_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a Futu get_history_kline result to the internal OHLCV format."""
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        df = df.copy()
        if "time_key" in df.columns:
            df = df.rename(columns={"time_key": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "open", "high", "low", "close"])
        df = df[df["close"] > 0]
        df["volume"] = df["volume"].fillna(0)
        return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)
    except Exception as exc:
        print(f"[futu] normalize failed: {exc}")
        return pd.DataFrame()


def get_daily_history_futu(code: str, years: int = 4) -> pd.DataFrame:
    """Fetch daily OHLCV from Futu OpenD.  Requires FutuOpenD running locally.

    Returns empty DataFrame on any error so callers can fall back to yfinance.
    """
    if not _FUTU_AVAILABLE or not USE_FUTU:
        return pd.DataFrame()
    futu_code = f"HK.{code}"
    end_str = datetime.now(HKT_TZ).strftime("%Y-%m-%d")
    start_str = (datetime.now(HKT_TZ) - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")
    try:
        ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
        try:
            ret, df, _ = ctx.get_history_kline(
                futu_code,
                start=start_str,
                end=end_str,
                ktype=KLType.K_DAY,
                autype=AuType.QFQ,
                fields=[
                    KL_FIELD.DATE_TIME, KL_FIELD.OPEN, KL_FIELD.HIGH,
                    KL_FIELD.LOW, KL_FIELD.CLOSE, KL_FIELD.VOLUME,
                ],
                max_count=5000,
            )
        finally:
            ctx.close()
        if ret != _FUTU_RET_OK:
            return pd.DataFrame()
        return _normalize_futu_df(df)
    except Exception as exc:
        print(f"[futu] {code} failed: {exc}")
        return pd.DataFrame()


def _get_daily_history_batch_futu(codes: list[str], years: int) -> dict[str, pd.DataFrame]:
    """Parallel Futu batch download using a thread pool.  Each thread opens its own
    OpenQuoteContext (Futu recommends one context per thread)."""
    if not _FUTU_AVAILABLE or not USE_FUTU or not codes:
        return {}
    workers = min(YF_BATCH_THREADS, len(codes), 8)

    def _fetch(code: str) -> tuple[str, pd.DataFrame]:
        return code, get_daily_history_futu(code, years)

    out: dict[str, pd.DataFrame] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for code, df in pool.map(_fetch, codes):
            if not df.empty:
                out[code] = df
    return out


def get_daily_history(code: str, period: str) -> pd.DataFrame:
    # Futu first (if enabled), fall back to yfinance.
    if USE_FUTU and _FUTU_AVAILABLE:
        df = get_daily_history_futu(code, _period_to_years(period))
        if not df.empty:
            return df
    ticker = hk_code_to_yahoo(code)
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=YF_HTTP_TIMEOUT,
            )
            df = normalize_yfinance_df(raw)
            if not df.empty:
                return df
        except Exception as exc:
            print(f"{code} {ticker} yfinance failed {attempt}/{RETRY_COUNT}: {exc}")
        if attempt < RETRY_COUNT:
            time.sleep(RETRY_SLEEP)
    return pd.DataFrame()


def get_weekly_history(code: str, period: str = "2y") -> pd.DataFrame:
    """Download weekly OHLC (interval=1wk) for chart rendering."""
    ticker = hk_code_to_yahoo(code)
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval="1wk",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=YF_HTTP_TIMEOUT,
            )
            df = normalize_yfinance_df(raw)
            if not df.empty:
                return df
        except Exception as exc:
            print(f"{code} {ticker} weekly yfinance failed {attempt}/{RETRY_COUNT}: {exc}")
        if attempt < RETRY_COUNT:
            time.sleep(RETRY_SLEEP)
    return pd.DataFrame()


def get_daily_history_batch(codes: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Download daily OHLC for many tickers.

    Uses Futu OpenD parallel batch if USE_FUTU=true; otherwise yfinance bulk download.
    Tickers with no data are omitted from the result map.
    """
    if not codes:
        return {}
    if USE_FUTU and _FUTU_AVAILABLE:
        result = _get_daily_history_batch_futu(codes, _period_to_years(period))
        if result:
            return result
        # If Futu returned nothing (OpenD down?), fall through to yfinance.
    ticker_map = {hk_code_to_yahoo(c): c for c in codes}
    tickers = list(ticker_map.keys())
    out: dict[str, pd.DataFrame] = {}
    try:
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=YF_BATCH_THREADS,
            group_by="ticker",
            timeout=YF_HTTP_TIMEOUT,
        )
    except Exception as exc:
        print(f"[batch] yfinance batch of {len(tickers)} failed: {exc}")
        return out
    if raw is None or raw.empty:
        return out
    # Single ticker: yfinance returns a flat frame (no top-level ticker index).
    if not isinstance(raw.columns, pd.MultiIndex):
        only_code = ticker_map[tickers[0]]
        df = normalize_yfinance_df(raw)
        if not df.empty:
            out[only_code] = df
        return out
    for ticker in tickers:
        try:
            sub = raw[ticker]
        except KeyError:
            continue
        if sub is None or sub.dropna(how="all").empty:
            continue
        df = normalize_yfinance_df(sub.copy())
        if not df.empty:
            out[ticker_map[ticker]] = df
    return out


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


def check_ipo_breakout(
    code: str,
    name: str,
    df: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], pd.DataFrame] | None:
    """Check for IPO first-day HIGH breakout.  Pass pre-fetched df to avoid double fetch."""
    if df is None:
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
        return (
            {
                "Code": code,
                "Name": name,
                "IPO Date": df.iloc[0]["date"].strftime("%Y-%m-%d"),
                "Listed Days": listing_days,
                "IPO High": round(ipo_high, 3),
                "Today High": round(today["high"], 3),
                "Today Close": round(today["close"], 3),
                "Break %": round((today["high"] / ipo_high - 1) * 100, 2),
                "Data Date": today["date"].strftime("%Y-%m-%d"),
            },
            df,
        )
    return None


def check_ipo_open_breakout(
    code: str,
    name: str,
    df: pd.DataFrame,
) -> dict[str, Any] | None:
    """Check if today's close crosses above IPO first-day OPEN price.

    Lower barrier than the first-day HIGH — signals stock returning to IPO starting price.
    Requires pre-fetched df (share with check_ipo_breakout to avoid double fetch).
    """
    if df.empty or len(df) < MIN_LISTING_DAYS + 1:
        return None
    listing_days = len(df)
    if MAX_LISTING_DAYS > 0 and listing_days > MAX_LISTING_DAYS:
        return None
    ipo_open = float(df.iloc[0]["open"])
    if ipo_open <= 0:
        return None
    today = df.iloc[-1]
    prev = df.iloc[-2]
    # Breakout: close crosses from below to above IPO open
    if float(today["close"]) > ipo_open and float(prev["close"]) <= ipo_open:
        return {
            "Code": code,
            "Name": name,
            "IPO Date": df.iloc[0]["date"].strftime("%Y-%m-%d"),
            "Listed Days": listing_days,
            "IPO Open": round(ipo_open, 3),
            "Today High": round(float(today["high"]), 3),
            "Today Close": round(float(today["close"]), 3),
            "Break %": round((float(today["close"]) / ipo_open - 1) * 100, 2),
            "Data Date": today["date"].strftime("%Y-%m-%d"),
        }


POC_WINDOWS = [
    ("半年POC", "6M", POC_LOOKBACK_DAYS_6M, "#60a5fa"),
    ("12個月POC", "12M", POC_LOOKBACK_DAYS_12M, "#f472b6"),
    ("3年POC", "3Y", POC_LOOKBACK_DAYS_3Y, "#a78bfa"),
]


def check_poc_breakout(
    code: str,
    name: str,
    df: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], pd.DataFrame] | None:
    if df is None:
        df = get_daily_history(code, YF_POC_PERIOD)
    if df.empty or len(df) < POC_LOOKBACK_DAYS_6M + 2:
        return None
    field = BREAKOUT_FIELD if BREAKOUT_FIELD in ["high", "close"] else "high"
    today = df.iloc[-1]
    prev = df.iloc[-2]
    today_value = today[field]
    prev_value = prev[field]
    poc_results: list[dict[str, Any]] = []
    for label, short, lookback_days, _color in POC_WINDOWS:
        if len(df) < lookback_days + 2:
            poc_results.append({"label": label, "short": short, "poc": None, "break_pct": None, "crossed": False})
            continue
        profile_df = df.iloc[-(lookback_days + 1):-1].copy()
        poc = calculate_poc(profile_df)
        if poc is None or poc <= 0:
            poc_results.append({"label": label, "short": short, "poc": None, "break_pct": None, "crossed": False})
            continue
        crossed = today_value > poc and prev_value <= poc
        poc_results.append({
            "label": label,
            "short": short,
            "poc": round(poc, 3),
            "break_pct": round((today_value / poc - 1) * 100, 2),
            "crossed": crossed,
        })
    crossed = [x for x in poc_results if x["crossed"]]
    if not crossed:
        return None

    def _by(short: str) -> float | None:
        return next((x["poc"] for x in poc_results if x["short"] == short), None)

    main = crossed[0]
    return (
        {
            "Code": code,
            "Name": name,
            "Signal": " + ".join(x["label"] for x in crossed),
            "Crossed Short": " / ".join(x["short"] for x in crossed),
            "POC": main["poc"],
            "POC 6M": _by("6M"),
            "POC 12M": _by("12M"),
            "POC 3Y": _by("3Y"),
            "Today High": round(today["high"], 3),
            "Today Close": round(today["close"], 3),
            "Break Field": field,
            "Break Value": round(today_value, 3),
            "Break %": main["break_pct"],
            "Data Date": today["date"].strftime("%Y-%m-%d"),
            "All POC": poc_results,
        },
        df,
    )


def _emit_ipo_high_hit(result: dict[str, Any], df: pd.DataFrame, wl_entry: dict | None) -> None:
    code = result["Code"]
    tv_url = tradingview_url(code)
    on_watchlist = wl_entry is not None
    if on_watchlist:
        wl_types = " / ".join(wl_entry.get("types") or [])
        wl_date = wl_entry.get("ann_date") or wl_entry.get("announcement_date", "")
        wl_line = f"⭐ 公告後突破 · {wl_types}（{wl_date}）\n"
        title_prefix = "⭐🚀"
        priority = 3
        tags = ["IPO", "IPO首日高突破", "公告後突破"]
    else:
        wl_line = ""
        title_prefix = "🚀"
        priority = 2
        tags = ["IPO", "IPO首日高突破"]
    payload = {
        "source": "cloud_scanner",
        "category": "ipo",
        "code": code,
        "symbol": hk_code_to_yahoo(code),
        "name": result["Name"],
        "signal": "IPO首日高突破",
        "timeframe": "1D",
        "price": result["Today Close"],
        "message": (
            f"IPO日期：{result['IPO Date']}；IPO首日高：{result['IPO High']}；"
            f"今日最高：{result['Today High']}；突破幅度：{result['Break %']}%"
        ),
        "strategy": "IPO First Day High Breakout",
        "chart_url": "",
        "source_url": "",
        "tags": tags,
        "priority": priority,
        "raw": json.dumps(result, ensure_ascii=False),
    }
    break_sign = "+" if result["Break %"] >= 0 else ""
    pw_low = get_prev_week_low(df)
    _sl = sl_yr_line(pw_low, float(result["Today Close"]), df)
    sl_line = f"\n{_sl}" if _sl else ""
    caption = (
        f"🚀首日高：{result['IPO High']}（{result['IPO Date']}）\n"
        f"{code} {result['Name']}\n"
        + (f"{wl_line.strip()}\n" if wl_line else "")
        + f"突破：{result['Today High']}　<b>{break_sign}{result['Break %']}%</b>{sl_line}"
    )
    ipo_high_levels = [("IPO首日高", result["IPO High"], "#fbbf24")]
    if pw_low is not None:
        ipo_high_levels.append(("前周低", pw_low, "#ef4444"))
    chart_path = render_chart(
        df, code, result["Name"], "IPO首日高突破",
        levels=ipo_high_levels,
        lookback_days=min(len(df), max(60, result["Listed Days"] + 5)),
    )
    emit_alert(payload, caption, chart_path, reply_markup=build_inline_keyboard_([("📊 走勢圖", tv_url)]), df=df)


def _emit_ipo_open_hit(result: dict[str, Any], df: pd.DataFrame, wl_entry: dict | None) -> None:
    code = result["Code"]
    tv_url = tradingview_url(code)
    on_watchlist = wl_entry is not None
    if on_watchlist:
        wl_types = " / ".join(wl_entry.get("types") or [])
        wl_date = wl_entry.get("ann_date") or wl_entry.get("announcement_date", "")
        wl_line = f"⭐ 公告後突破 · {wl_types}（{wl_date}）\n"
        title_prefix = "⭐🚀"
        priority = 3
        tags = ["IPO", "IPO首日開突破", "公告後突破"]
    else:
        wl_line = ""
        title_prefix = "🚀"
        priority = 2
        tags = ["IPO", "IPO首日開突破"]
    break_sign = "+" if result["Break %"] >= 0 else ""
    payload = {
        "source": "cloud_scanner",
        "category": "ipo",
        "code": code,
        "symbol": hk_code_to_yahoo(code),
        "name": result["Name"],
        "signal": "IPO首日開突破",
        "timeframe": "1D",
        "price": result["Today Close"],
        "message": (
            f"IPO日期：{result['IPO Date']}；IPO首日開：{result['IPO Open']}；"
            f"今日收：{result['Today Close']}；突破幅度：{result['Break %']}%"
        ),
        "strategy": "IPO First Day Open Breakout",
        "chart_url": "",
        "source_url": "",
        "tags": tags,
        "priority": priority,
        "raw": json.dumps(result, ensure_ascii=False),
    }
    pw_low = get_prev_week_low(df)
    _sl = sl_yr_line(pw_low, float(result["Today Close"]), df)
    sl_line = f"\n{_sl}" if _sl else ""
    caption = (
        f"🚀首日開：{result['IPO Open']}（{result['IPO Date']}）\n"
        f"{code} {result['Name']}\n"
        + (f"{wl_line.strip()}\n" if wl_line else "")
        + f"突破：{result['Today Close']}　<b>{break_sign}{result['Break %']}%</b>{sl_line}"
    )
    ipo_open_levels = [("IPO首日開", result["IPO Open"], "#a78bfa")]
    if pw_low is not None:
        ipo_open_levels.append(("前周低", pw_low, "#ef4444"))
    chart_path = render_chart(
        df, code, result["Name"], "IPO首日開突破",
        levels=ipo_open_levels,
        lookback_days=min(len(df), max(60, result["Listed Days"] + 5)),
    )
    emit_alert(payload, caption, chart_path, reply_markup=build_inline_keyboard_([("📊 走勢圖", tv_url)]), df=df)


def run_ipo() -> None:
    send_telegram_message(
        f"<b>IPO首日突破掃描開始</b> · {datetime.now():%Y-%m-%d %H:%M}\n"
        f"信號：首日高突破 + 首日開突破"
    )
    stocks = get_hk_stock_list()
    try:
        watchlist_map = fetch_watchlist_from_gas()
    except Exception as exc:
        print(f"[ipo] watchlist fetch failed: {exc}")
        watchlist_map = {}
    print(f"IPO watchlist: {len(watchlist_map)} active entries")
    total = len(stocks)
    hits = 0
    started = time.monotonic()
    for n, row in enumerate(stocks.to_dict("records"), start=1):
        if n % 50 == 0:
            elapsed = time.monotonic() - started
            rate = n / elapsed if elapsed > 0 else 0
            print(f"IPO progress {n}/{total} hits={hits} rate={rate:.1f}/s", flush=True)
        code, name = row["code"], row["name"]
        # Fetch once, share df across both checks.
        df = get_daily_history(code, YF_IPO_PERIOD)
        if df.empty:
            time.sleep(SLEEP_SEC)
            continue
        wl_entry = watchlist_map.get(code)
        # ── IPO first-day HIGH breakout ──────────────────────────────────────
        high_outcome = check_ipo_breakout(code, name, df=df)
        if high_outcome:
            result, _ = high_outcome
            hits += 1
            _emit_ipo_high_hit(result, df, wl_entry)
        # ── IPO first-day OPEN breakout ──────────────────────────────────────
        open_result = check_ipo_open_breakout(code, name, df)
        if open_result:
            hits += 1
            _emit_ipo_open_hit(open_result, df, wl_entry)
        time.sleep(SLEEP_SEC)
    send_telegram_message(f"IPO首日突破掃描完成，共 {hits} 隻（首日高＋首日開合計）。")


def _fmt_poc_line(result: dict[str, Any]) -> str:
    parts: list[str] = []
    pairs = [("6M", result.get("POC 6M")), ("12M", result.get("POC 12M")),
             ("3Y", result.get("POC 3Y"))]
    for short, val in pairs:
        if val is None or pd.isna(val):
            continue
        parts.append(f"{short} {val}")
    return "｜".join(parts) if parts else "—"


def build_announcement_label_map(
    announcements: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Map zero-padded HK code -> ordered unique short labels for POC enrichment.

    Labels are 配股 / 供股 / 增持 / 大手轉倉. Missing or unknown classifications
    are dropped so we never fabricate a label.
    """
    out: dict[str, list[str]] = {}
    for ann in announcements or []:
        raw_code = str(ann.get("code", "")).strip()
        if not raw_code:
            continue
        code = raw_code.zfill(5)
        short_labels: list[str] = []
        for t in ann.get("types", []) or []:
            label = POC_ANNOUNCEMENT_LABELS.get(t)
            if label:
                short_labels.append(label)
        if not short_labels:
            continue
        bucket = out.setdefault(code, [])
        for label in short_labels:
            if label not in bucket:
                bucket.append(label)
    return out


def _emit_poc_hit(
    result: dict[str, Any],
    df: pd.DataFrame,
    announcement_labels: list[str] | None = None,
    watchlist_entry: dict | None = None,
) -> None:
    code = result["Code"]
    tv_url = tradingview_url(code)
    crossed_short = result["Crossed Short"]
    labels = list(announcement_labels or [])
    tags = ["POC", "Breakout", result["Signal"]]
    tags.extend(labels)

    on_watchlist = watchlist_entry is not None
    if on_watchlist:
        wl_types = " / ".join(watchlist_entry.get("types") or [])
        wl_date = watchlist_entry.get("ann_date") or watchlist_entry.get("announcement_date", "")
        wl_line = f"⭐ 公告後突破 · {wl_types}（{wl_date}）"
        tags.append("公告後突破")
    else:
        wl_line = ""

    base_priority = 2 if "+" in result["Signal"] else 1
    priority = (base_priority + 1) if on_watchlist else base_priority

    payload = {
        "source": "cloud_scanner",
        "category": "poc",
        "code": code,
        "symbol": hk_code_to_yahoo(code),
        "name": result["Name"],
        "signal": result["Signal"],
        "timeframe": "1D",
        "price": result["Today Close"],
        "message": (
            f"觸發 {crossed_short}；突破價 {result['Break Value']}；"
            f"高 {result['Today High']}；幅度 {result['Break %']}%"
        ),
        "strategy": "POC Breakout",
        "chart_url": "",
        "source_url": "",
        "tags": tags,
        "poc_6m": result["POC 6M"],
        "poc_12m": result["POC 12M"],
        "poc_3y": result["POC 3Y"],
        "announcement_labels": labels,
        "priority": priority,
        "raw": json.dumps(result, ensure_ascii=False, default=str),
    }
    break_sign = "+" if (result.get("Break %") or 0) >= 0 else ""
    title_prefix = "⭐📈" if on_watchlist else "📈"
    pw_low = get_prev_week_low(df)
    _sl = sl_yr_line(pw_low, float(result["Today Close"]), df)
    _trig_map = {"6M": "POC 6M", "12M": "POC 12M", "3Y": "POC 3Y"}
    _trig_parts = []
    for _sh in crossed_short.split(" / "):
        _sh = _sh.strip()
        _v = result.get(_trig_map.get(_sh, ""))
        _trig_parts.append(f"{_sh} {_v}" if _v is not None and not pd.isna(_v) else _sh)
    _trig_line = "/ ".join(_trig_parts)
    caption_lines = [
        f"⚡觸發：{_trig_line}",
        f"📈{code} {result['Name']}",
        f"高於觸發：<b>{break_sign}{result['Break %']}%</b> ({result['Break Value']})",
    ]
    if _sl:
        caption_lines.append(_sl)
    if labels:
        caption_lines.append(f"公告：{' / '.join(labels)}")
    if wl_line:
        caption_lines.append(wl_line.strip())
    caption = "\n".join(caption_lines)
    chart_levels = []
    key_map = {"6M": "POC 6M", "12M": "POC 12M", "3Y": "POC 3Y"}
    for label, short, _days, color in POC_WINDOWS:
        val = result.get(key_map[short])
        if val is not None and not pd.isna(val):
            chart_levels.append((label, val, color))
    if pw_low is not None:
        chart_levels.append(("前周低", pw_low, "#ef4444"))
    chart_path = render_chart(
        df,
        code,
        result["Name"],
        f"POC突破 · {crossed_short}",
        levels=chart_levels,
        lookback_days=CHART_LOOKBACK_DAYS,
    )
    poc_kb = build_inline_keyboard_([("📊 走勢圖", tv_url)])
    emit_alert(payload, caption, chart_path, reply_markup=poc_kb, df=df)


def run_poc() -> None:
    stocks = get_hk_stock_list()
    universe_size = len(stocks)
    shard_count = POC_SHARD_COUNT
    shard_index = POC_SHARD_INDEX if POC_SHARD_INDEX < shard_count else 0
    shard_label = f"{shard_index + 1}/{shard_count}"
    if shard_count > 1:
        # Contiguous slice keyed by sorted code so the slicing is deterministic
        # across runs even if the upstream HKEX list reorders.
        stocks = stocks.sort_values("code").reset_index(drop=True)
        chunk_size = (universe_size + shard_count - 1) // shard_count
        start = shard_index * chunk_size
        end = min(start + chunk_size, universe_size)
        stocks = stocks.iloc[start:end].copy()
        print(f"POC shard {shard_label}: stocks {start}-{end} of {universe_size}")
    # Pull the recent HKEXnews corp-action map once per run so each POC hit can
    # be enriched with a 公告 label line without paying per-stock lookup cost.
    try:
        ann_map = build_announcement_label_map(fetch_corp_action_announcements())
    except Exception as exc:
        print(f"[poc] announcement enrichment failed: {exc}")
        ann_map = {}
    print(f"POC announcement label map size: {len(ann_map)}")
    # Fetch persisted watchlist for cross-run 公告後突破 detection.
    try:
        watchlist_map = fetch_watchlist_from_gas()
    except Exception as exc:
        print(f"[poc] watchlist fetch failed: {exc}")
        watchlist_map = {}
    print(f"POC watchlist: {len(watchlist_map)} active entries")
    send_telegram_message(
        f"<b>POC突破掃描開始</b> · {datetime.now():%Y-%m-%d %H:%M}\n"
        f"條件：股價向上突破 半年／1年／3年 POC\n"
        f"批次：{shard_label}（{len(stocks)} / {universe_size}）"
    )
    poc_cap = POC_MAX_STOCKS_PER_RUN if POC_MAX_STOCKS_PER_RUN > 0 else 0
    if poc_cap and len(stocks) > poc_cap:
        stocks = stocks.head(poc_cap).copy()
        print(f"POC capped to {poc_cap} stocks")
    records = stocks.to_dict("records")
    total = len(records)
    hits = 0
    processed = 0
    aborted = False
    started = time.monotonic()
    print(f"POC scan starting: shard={shard_label} stocks={total} batch={YF_BATCH_SIZE} threads={YF_BATCH_THREADS} period={YF_POC_PERIOD}")

    for batch_start in range(0, total, YF_BATCH_SIZE):
        if POC_TIME_BUDGET_SEC and (time.monotonic() - started) > POC_TIME_BUDGET_SEC:
            print(f"POC time budget exceeded at {processed}/{total}, stopping early")
            aborted = True
            break
        chunk = records[batch_start: batch_start + YF_BATCH_SIZE]
        chunk_codes = [row["code"] for row in chunk]
        t0 = time.monotonic()
        try:
            data = get_daily_history_batch(chunk_codes, YF_POC_PERIOD)
        except Exception as exc:
            print(f"[batch] {batch_start}-{batch_start + len(chunk)} crashed: {exc}; skipping")
            data = {}
        dl_secs = time.monotonic() - t0
        chunk_hits = 0
        for row in chunk:
            processed += 1
            code = row["code"]
            df = data.get(code)
            if df is None or df.empty:
                continue
            try:
                outcome = check_poc_breakout(code, row["name"], df=df)
            except Exception as exc:
                print(f"{code} POC check failed: {exc}")
                continue
            if outcome:
                hits += 1
                chunk_hits += 1
                try:
                    # Watchlist entry: prefer persisted watchlist; synthesise from
                    # current-run ann_map so same-day corp+POC also gets ⭐.
                    wl_entry = watchlist_map.get(code)
                    if wl_entry is None and ann_map.get(code):
                        wl_entry = {"types": ann_map[code], "ann_date": hkt_today_str()}
                    _emit_poc_hit(
                        *outcome,
                        announcement_labels=ann_map.get(code),
                        watchlist_entry=wl_entry,
                    )
                except Exception as exc:
                    print(f"{code} emit failed: {exc}")
        elapsed = time.monotonic() - started
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        print(
            f"POC progress {processed}/{total} hits={hits} "
            f"(chunk dl={dl_secs:.1f}s hits={chunk_hits} rate={rate:.1f}/s eta={eta:.0f}s)",
            flush=True,
        )
        if SLEEP_SEC > 0:
            time.sleep(SLEEP_SEC)

    elapsed = time.monotonic() - started
    summary = (
        f"POC突破掃描完成（批次 {shard_label}），共 {hits} 隻符合"
        f"（掃描 {processed}/{total}，用時 {elapsed:.0f}s）"
    )
    if aborted:
        summary += "（已達時間上限提前結束）"
    print(summary)
    send_telegram_message(summary)


def check_year_open_breakout(
    code: str,
    name: str,
    df: pd.DataFrame,
) -> dict[str, Any] | None:
    """Check if today's price crosses above the current year's first trading-day open.

    Signal: bullish momentum reclaiming the annual starting price.
    Uses BREAKOUT_FIELD (high or close) consistent with POC scan.
    """
    if df is None or df.empty or len(df) < 3:
        return None
    current_year = datetime.now(HKT_TZ).year
    year_mask = df["date"].dt.year == current_year
    year_data = df[year_mask]
    if year_data.empty:
        return None
    year_open = float(year_data.iloc[0]["open"])
    year_open_date = year_data.iloc[0]["date"].strftime("%Y-%m-%d")
    if year_open <= 0:
        return None
    today = df.iloc[-1]
    prev = df.iloc[-2]
    field = BREAKOUT_FIELD if BREAKOUT_FIELD in ["high", "close"] else "high"
    today_val = float(today[field])
    prev_val = float(prev[field])
    if today_val > year_open and prev_val <= year_open:
        return {
            "Code": code,
            "Name": name,
            "Year": current_year,
            "Year Open Date": year_open_date,
            "Year Open": round(year_open, 3),
            "Break Field": field,
            "Break Value": round(today_val, 3),
            "Today High": round(float(today["high"]), 3),
            "Today Close": round(float(today["close"]), 3),
            "Break %": round((today_val / year_open - 1) * 100, 2),
            "Data Date": today["date"].strftime("%Y-%m-%d"),
        }
    return None


def run_year_open_breakout() -> None:
    """Scan all HK stocks for price crossing above current-year first-day open."""
    current_year = datetime.now(HKT_TZ).year
    send_telegram_message(
        f"<b>年開突破掃描開始</b> · {datetime.now():%Y-%m-%d %H:%M}\n"
        f"條件：股價向上穿越 {current_year} 年首個交易日開市價"
    )
    stocks = get_hk_stock_list()
    try:
        watchlist_map = fetch_watchlist_from_gas()
    except Exception as exc:
        print(f"[year_open] watchlist fetch failed: {exc}")
        watchlist_map = {}

    records = stocks.to_dict("records")
    total = len(records)
    hits = 0
    processed = 0
    started = time.monotonic()

    for batch_start in range(0, total, YF_BATCH_SIZE):
        chunk = records[batch_start: batch_start + YF_BATCH_SIZE]
        chunk_codes = [r["code"] for r in chunk]
        try:
            data = get_daily_history_batch(chunk_codes, "1y")
        except Exception as exc:
            print(f"[year_open] batch failed: {exc}")
            data = {}
        for row in chunk:
            processed += 1
            code = row["code"]
            df = data.get(code)
            if df is None or df.empty:
                continue
            try:
                result = check_year_open_breakout(code, row["name"], df)
            except Exception as exc:
                print(f"[year_open] {code} check failed: {exc}")
                continue
            if not result:
                continue
            hits += 1
            tv_url = tradingview_url(code)
            wl_entry = watchlist_map.get(code)
            on_watchlist = wl_entry is not None
            if on_watchlist:
                wl_types = " / ".join(wl_entry.get("types") or [])
                wl_date = wl_entry.get("ann_date") or wl_entry.get("announcement_date", "")
                wl_line = f"⭐ 公告後突破 · {wl_types}（{wl_date}）\n"
                title_prefix = "⭐📅"
                priority = 3
                tags = ["年開突破", "公告後突破"]
            else:
                wl_line = ""
                title_prefix = "📅"
                priority = 1
                tags = ["年開突破"]
            break_sign = "+" if result["Break %"] >= 0 else ""
            payload = {
                "source": "cloud_scanner",
                "category": "year_open",
                "code": code,
                "symbol": hk_code_to_yahoo(code),
                "name": result["Name"],
                "signal": "年開突破",
                "timeframe": "1D",
                "price": result["Today Close"],
                "message": (
                    f"{current_year}年首日開：{result['Year Open']}（{result['Year Open Date']}）；"
                    f"突破幅度：{result['Break %']}%"
                ),
                "strategy": "Year Open Breakout",
                "chart_url": "",
                "source_url": "",
                "tags": tags,
                "priority": priority,
                "raw": json.dumps(result, ensure_ascii=False),
            }
            pw_low = get_prev_week_low(df)
            _sl = sl_yr_line(pw_low, float(result["Today Close"]), df)
            sl_line = f"\n{_sl}" if _sl else ""
            caption = (
                f"📅{current_year}年開：{result['Year Open']}（{result['Year Open Date']}）\n"
                f"{code} {result['Name']}\n"
                + (f"{wl_line.strip()}\n" if wl_line else "")
                + f"突破：{result['Break Value']}　<b>{break_sign}{result['Break %']}%</b>{sl_line}"
            )
            yr_levels = [(f"{current_year}年首日開", result["Year Open"], "#ffffff", 2.2, "--")]
            if pw_low is not None:
                yr_levels.append(("前周低", pw_low, "#ef4444"))
            chart_path = render_chart(
                df, code, result["Name"], f"年開突破 {current_year}",
                levels=yr_levels,
                lookback_days=CHART_LOOKBACK_DAYS,
            )
            emit_alert(payload, caption, chart_path, reply_markup=build_inline_keyboard_([("📊 走勢圖", tv_url)]))
        elapsed = time.monotonic() - started
        rate = processed / elapsed if elapsed > 0 else 0
        if batch_start % (YF_BATCH_SIZE * 5) == 0:
            print(f"年開突破 {processed}/{total} hits={hits} rate={rate:.1f}/s", flush=True)
        if SLEEP_SEC > 0:
            time.sleep(SLEEP_SEC)

    send_telegram_message(f"年開突破掃描完成，共 {hits} 隻（掃描 {processed}/{total}）。")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "corp":
        run_corp_actions()
    elif mode == "ipo":
        run_ipo()
    elif mode == "poc":
        run_poc()
    elif mode == "year_open":
        run_year_open_breakout()
    elif mode == "us":
        from us_scanner import run_us_corp_actions
        run_us_corp_actions()
    elif mode == "us_all":
        from us_scanner import run_us_all
        run_us_all()
    elif mode == "all":
        run_corp_actions()
        run_ipo()
        run_poc()
        run_year_open_breakout()
    else:
        raise SystemExit(
            "Usage: python scanner/hk_cloud_scanner.py [corp|ipo|poc|year_open|us|all]"
        )


if __name__ == "__main__":
    main()

