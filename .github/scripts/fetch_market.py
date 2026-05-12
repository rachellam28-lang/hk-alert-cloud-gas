import json, re, datetime
import yfinance as yf
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Evaluation class → Chinese label + colour key
_EVAL_MAP = {
    "pe-under-2":  {"label": "極平", "color": "green"},
    "pe-under-1":  {"label": "偏平", "color": "green"},
    "pe-in-range": {"label": "合理", "color": "neutral"},
    "pe-over-1":   {"label": "偏貴", "color": "orange"},
    "pe-over-2":   {"label": "貴",   "color": "red"},
}

def yf_quote(ticker, dp=2):
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        val = float(info.last_price)
        prev = float(info.previous_close)
        chg = val - prev
        pct = chg / prev * 100 if prev else None
        return {"value": round(val, dp), "change": round(chg, dp),
                "changePct": round(pct, 2) if pct else None, "stale": False}
    except Exception as e:
        print(f"yf_quote {ticker}: {e}")
        return {"value": None, "change": None, "changePct": None, "stale": True}

def vix_eval(val):
    if val is None: return None
    if val < 15:   return {"label": "低波動", "color": "green"}
    if val < 20:   return {"label": "正常",   "color": "neutral"}
    if val < 30:   return {"label": "偏高",   "color": "orange"}
    return             {"label": "恐慌",   "color": "red"}

def worldpe(url):
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        # Current PE
        m_val = re.search(
            r'area-pe-box[\s\S]{0,600}?<font[^>]*>\s*(\d{1,3}\.\d{1,2})\s*</font>', r.text, re.I)
        val = float(m_val.group(1)) if m_val else None

        # 5Y average range  e.g. "average P/E interval is [14.30 , 16.65]"
        m_avg = re.search(
            r'average P/E interval is \[(\d+\.\d+)\s*,\s*(\d+\.\d+)\]', r.text, re.I)
        avg5y_mid = None
        avg5y_range = None
        if m_avg:
            lo, hi = float(m_avg.group(1)), float(m_avg.group(2))
            avg5y_mid = round((lo + hi) / 2, 2)
            avg5y_range = [lo, hi]

        # Evaluation class
        m_cls = re.search(
            r'<font class="[^"]*?(pe-under-2|pe-under-1|pe-in-range|pe-over-1|pe-over-2)[^"]*"', r.text, re.I)
        ev = _EVAL_MAP.get(m_cls.group(1)) if m_cls else None

        return {
            "value": val, "change": None, "changePct": None,
            "avg5y_mid": avg5y_mid, "avg5y_range": avg5y_range,
            "eval": ev, "stale": val is None
        }
    except Exception as e:
        print(f"worldpe {url}: {e}")
        return {"value": None, "change": None, "changePct": None,
                "avg5y_mid": None, "avg5y_range": None, "eval": None, "stale": True}

hsi    = yf_quote("^HSI", 0)
dxy    = yf_quote("DX-Y.NYB", 2)
vix_d  = yf_quote("^VIX", 2)
vix_d["eval"] = vix_eval(vix_d["value"])
hsi_pe = worldpe("https://worldperatio.com/area/hong-kong/")
spx_pe = worldpe("https://worldperatio.com/area/united-states/")

out = {
    "hsi": hsi, "dxy": dxy, "vix": vix_d,
    "hsi_pe": hsi_pe, "spx_pe": spx_pe,
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
}
print(json.dumps(out, indent=2, ensure_ascii=False))
with open("market.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("market.json saved")
