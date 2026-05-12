import json, re, datetime
import yfinance as yf
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

def yf_quote(ticker, dp=2):
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        val = float(info.last_price)
        prev = float(info.previous_close)
        chg = val - prev
        pct = chg / prev * 100 if prev else None
        return {"value": round(val, dp), "change": round(chg, dp), "changePct": round(pct, 2) if pct else None, "stale": False}
    except Exception as e:
        print(f"yf_quote {ticker}: {e}")
        return {"value": None, "change": None, "changePct": None, "stale": True}

def worldpe(url):
    """Parse PE from worldperatio.com individual area page (area-pe-box structure)."""
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        m = re.search(r'area-pe-box[\s\S]{0,600}?<font[^>]*>\s*(\d{1,3}\.\d{1,2})\s*</font>', r.text, re.I)
        val = float(m.group(1)) if m else None
        return {"value": val, "change": None, "changePct": None, "stale": val is None}
    except Exception as e:
        print(f"worldpe {url}: {e}")
        return {"value": None, "change": None, "changePct": None, "stale": True}

hsi    = yf_quote("^HSI", 0)
dxy    = yf_quote("DX-Y.NYB", 2)
vix    = yf_quote("^VIX", 2)
hsi_pe = worldpe("https://worldperatio.com/area/hong-kong/")
spx_pe = worldpe("https://worldperatio.com/area/united-states/")

out = {
    "hsi": hsi, "dxy": dxy, "vix": vix,
    "hsi_pe": hsi_pe, "spx_pe": spx_pe,
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
}
print(json.dumps(out, indent=2, ensure_ascii=False))
with open("market.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("market.json saved")
