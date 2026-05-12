import json, time, re, datetime
import yfinance as yf
import requests

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

def worldpe(url, pattern):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        m = re.search(pattern, r.text, re.I | re.S)
        val = float(m.group(1)) if m else None
        return {"value": val, "change": None, "changePct": None, "stale": val is None}
    except Exception as e:
        print(f"worldpe {url}: {e}")
        return {"value": None, "change": None, "changePct": None, "stale": True}

hsi  = yf_quote("^HSI", 0)
dxy  = yf_quote("DX-Y.NYB", 2)
vix  = yf_quote("^VIX", 2)
hsi_pe = worldpe("https://worldperatio.com/area/hong-kong/",
                 r"P/E Ratio[\s\S]{0,400}?(\d{1,3}\.\d{1,2})")
spx_pe = worldpe("https://worldperatio.com/area/usa/",
                 r"P/E Ratio[\s\S]{0,400}?(\d{1,3}\.\d{1,2})")

out = {
    "hsi": hsi, "dxy": dxy, "vix": vix,
    "hsi_pe": hsi_pe, "spx_pe": spx_pe,
    "updated_at": datetime.datetime.utcnow().isoformat() + "Z"
}
print(json.dumps(out, indent=2, ensure_ascii=False))
with open("market.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("market.json saved")
