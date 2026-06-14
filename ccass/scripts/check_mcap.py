"""Check valuation + company for market cap."""
import subprocess, json, os

def get_token():
    for p in [
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]:
        p = os.path.normpath(p)
        if os.path.exists(p):
            with open(p) as f:
                for l in f:
                    if "LONGBRIDGE_ACCESS_TOKEN=" in l:
                        return l.strip().split("=", 1)[1]
    return os.environ.get("LONGBRIDGE_ACCESS_TOKEN", "")

token = get_token()
if not token:
    raise SystemExit("ERROR: Longbridge token not found")

auth = "Bearer " + token

def mcp(m, a=None):
    b = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": m, "arguments": a or {}}}
    r = subprocess.run([
        "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-H", "Authorization: " + auth,
        "-d", json.dumps(b),
    ], capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    res = json.loads(raw)
    c = res.get("result", {}).get("content", [])
    return json.loads(c[0]["text"]) if c else {}

# Try valuation
print("=== valuation ===")
d = mcp("valuation", {"symbol": "00700.HK"})
if d:
    metrics = d.get("metrics", {})
    for k in ["pe", "pb", "ps", "market_cap", "MarketCap"]:
        v = metrics.get(k, "N/A")
        print("  {}: {}".format(k, v))
    # Check full keys
    print("  all keys:", sorted(metrics.keys())[:15])

# Try company
print("\n=== company ===")
d2 = mcp("company", {"symbol": "00700.HK"})
if d2:
    for k in ["name", "market_cap", "total_shares", "MarketCap"]:
        v = d2.get(k, "N/A")
        print("  {}: {}".format(k, str(v)[:80]))
    print("  all keys:", sorted(d2.keys())[:15])
