"""Check static_info + calc_indexes response shape."""
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

auth = "Authorization: Bearer {}".format(token)

def mcp(m, a=None):
    b = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": m, "arguments": a or {}}}
    r = subprocess.run([
        "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-H", auth,
        "-d", json.dumps(b),
    ], capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    res = json.loads(raw)
    c = res.get("result", {}).get("content", [])
    return json.loads(c[0]["text"]) if c else {}

# static_info full keys
d = mcp("static_info", {"symbols": ["00700.HK"]})
if isinstance(d, list) and d:
    item = d[0]
    for k, v in item.items():
        if v is not None and v != "":
            print("  {}: {}".format(k, str(v)[:80]))

print("\n=== calc_indexes ===")
d2 = mcp("calc_indexes", {"symbols": ["00700.HK"], "indexes": ["MarketCap", "LastDone"]})
if isinstance(d2, list):
    for item in d2:
        print(json.dumps(item, ensure_ascii=False, indent=2))
elif isinstance(d2, dict):
    print(list(d2.keys()))
