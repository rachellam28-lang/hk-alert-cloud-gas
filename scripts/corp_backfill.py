"""Backfill corp announcements from HKEX API to GAS v2."""
import json, sys, os, time, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scanner'))

# Fetch announcements with explicit timeout handling
from hk_cloud_scanner import fetch_corp_action_announcements

print("Fetching from HKEX...", flush=True)
try:
    anns = fetch_corp_action_announcements()
    print(f"Fetched {len(anns)} raw announcements", flush=True)
except Exception as e:
    print(f"Fetch failed: {e}", flush=True)
    sys.exit(1)

# Get bearer token
from local_alert_store import _get_gas_bearer
bearer = _get_gas_bearer()
if not bearer:
    print("FAIL: no bearer token", flush=True)
    sys.exit(1)

GAS_URL = "https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec"
S = "".join(["3vzh77WnYKjHRDX8", "mPq2xkF9tbLsU4nA"])

ok = err = 0
seen = set()
for ann in anns:
    code = str(ann.get('code', '')).strip()
    if not code:
        continue
    rd = ann.get('release_date', '')
    types_str = " / ".join(ann.get('types', []))
    key = f"{code}|{rd}|{types_str}"
    if key in seen:
        continue
    seen.add(key)

    p = {
        "secret": S,
        "created_at": f"{rd}T09:00:00+08:00" if rd else "",
        "source": "backfill",
        "category": "corp_action",
        "code": code.zfill(5),
        "symbol": code.zfill(5),
        "name": ann.get('name', ''),
        "signal": types_str,
        "message": str(ann.get('title', ''))[:500],
        "price": "",
        "chart_url": "",
        "source_url": ann.get('url', ''),
        "tags": "",
        "announcement_date": rd,
        "release_time": ann.get('release_time', ''),
    }

    data = json.dumps(p).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"}
    try:
        req = urllib.request.Request(GAS_URL, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read())
            if r.get("ok"):
                ok += 1
            else:
                err += 1
    except Exception:
        err += 1

    if (ok + err) % 10 == 0:
        print(f"  {ok+err}/{len(anns)} ok={ok} err={err}", flush=True)
    time.sleep(0.1)

print(f"\nDONE: {ok} ok, {err} err, {len(anns)} total", flush=True)
