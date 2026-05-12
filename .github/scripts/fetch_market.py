import json, re, datetime
import pandas as pd
import yfinance as yf
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

_EVAL_MAP = {
    "pe-under-2":  {"label": "極平", "color": "green"},
    "pe-under-1":  {"label": "偏平", "color": "green"},
    "pe-in-range": {"label": "合理", "color": "neutral"},
    "pe-over-1":   {"label": "偏貴", "color": "orange"},
    "pe-over-2":   {"label": "貴",   "color": "red"},
}

# ── 52-week breadth ticker lists ──────────────────────────────────────────
_HK_TICKERS = [
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

_US_TICKERS = [
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

# ── Helpers ───────────────────────────────────────────────────────────────
def yf_quote(ticker, dp=2):
    try:
        info = yf.Ticker(ticker).fast_info
        val  = float(info.last_price)
        prev = float(info.previous_close)
        chg  = val - prev
        pct  = chg / prev * 100 if prev else None
        return {"value": round(val, dp), "change": round(chg, dp),
                "changePct": round(pct, 2) if pct is not None else None, "stale": False}
    except Exception as e:
        print(f"yf_quote {ticker}: {e}")
        return {"value": None, "change": None, "changePct": None, "stale": True}

def vix_eval(val):
    if val is None: return None
    if val < 15:    return {"label": "低波動", "color": "green"}
    if val < 20:    return {"label": "正常",   "color": "neutral"}
    if val < 30:    return {"label": "偏高",   "color": "orange"}
    return              {"label": "恐慌",   "color": "red"}

def worldpe(url):
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        m_val = re.search(
            r'area-pe-box[\s\S]{0,600}?<font[^>]*>\s*(\d{1,3}\.\d{1,2})\s*</font>', r.text, re.I)
        val = float(m_val.group(1)) if m_val else None
        m_avg = re.search(
            r'average P/E interval is \[(\d+\.\d+)\s*,\s*(\d+\.\d+)\]', r.text, re.I)
        avg5y_mid = avg5y_range = None
        if m_avg:
            lo, hi = float(m_avg.group(1)), float(m_avg.group(2))
            avg5y_mid  = round((lo + hi) / 2, 2)
            avg5y_range = [lo, hi]
        m_cls = re.search(
            r'<font class="[^"]*?(pe-under-2|pe-under-1|pe-in-range|pe-over-1|pe-over-2)[^"]*"', r.text, re.I)
        ev = _EVAL_MAP.get(m_cls.group(1)) if m_cls else None
        return {"value": val, "change": None, "changePct": None,
                "avg5y_mid": avg5y_mid, "avg5y_range": avg5y_range,
                "eval": ev, "stale": val is None}
    except Exception as e:
        print(f"worldpe {url}: {e}")
        return {"value": None, "change": None, "changePct": None,
                "avg5y_mid": None, "avg5y_range": None, "eval": None, "stale": True}

def fetch_breadth(tickers, label):
    """Batch-download 1Y daily; bin each stock into 52w high/mid/low zone."""
    print(f"[breadth {label}] downloading {len(tickers)} tickers ...")
    try:
        raw = yf.download(
            " ".join(tickers), period="1y", interval="1d",
            auto_adjust=True, progress=False
        )
    except Exception as e:
        print(f"[breadth {label}] download error: {e}")
        return None
    if raw is None or raw.empty:
        print(f"[breadth {label}] empty result")
        return None

    try:
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
    except Exception as e:
        print(f"[breadth {label}] column error: {e}")
        return None

    high_n = mid_n = low_n = valid = 0
    for ticker in tickers:
        try:
            if ticker not in closes.columns:
                continue
            series = closes[ticker].dropna()
            if len(series) < 60:
                continue
            w52_high = float(series.max())
            w52_low  = float(series.min())
            current  = float(series.iloc[-1])
            if w52_high <= 0 or w52_low <= 0:
                continue
            valid += 1
            if current >= 0.9 * w52_high:
                high_n += 1
            elif current <= 1.1 * w52_low:
                low_n += 1
            else:
                mid_n += 1
        except Exception:
            continue

    print(f"[breadth {label}] valid={valid} high={high_n} mid={mid_n} low={low_n}")
    if valid < 5:
        return None
    return {
        "high":   round(high_n / valid * 100),
        "mid":    round(mid_n  / valid * 100),
        "low":    round(low_n  / valid * 100),
        "high_n": high_n, "mid_n": mid_n, "low_n": low_n,
        "count":  valid,
    }

# ── Main ──────────────────────────────────────────────────────────────────
hsi   = yf_quote("^HSI", 0)
dxy   = yf_quote("DX-Y.NYB", 2)
vix_d = yf_quote("^VIX", 2)
vix_d["eval"] = vix_eval(vix_d["value"])
hsi_pe = worldpe("https://worldperatio.com/area/hong-kong/")
spx_pe = worldpe("https://worldperatio.com/area/united-states/")

breadth_hk = fetch_breadth(_HK_TICKERS, "HK")
breadth_us = fetch_breadth(_US_TICKERS, "US")

out = {
    "hsi":    hsi,
    "dxy":    dxy,
    "vix":    vix_d,
    "hsi_pe": hsi_pe,
    "spx_pe": spx_pe,
    "breadth": {"hk": breadth_hk, "us": breadth_us},
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
}
print(json.dumps(out, indent=2, ensure_ascii=False))
with open("market.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("market.json saved")
