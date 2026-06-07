"""Test broker_holding_detail API structure"""
import json, subprocess

env = {}
with open(r"C:\Users\Administrator\Desktop\automatic\ccass-debug\.env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v

token = env["LONGBRIDGE_ACCESS_TOKEN"]
BASE = "https://mcp.longbridge.com"
AUTH = "Authorization: " + "Bearer " + token
HEADERS = [
    "-H", "Content-Type: application/json",
    "-H", "Accept: application/json, text/event-stream",
    "-H", AUTH,
]

def mcp(method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        body["params"] = params
    cmd = ["curl", "-s", "-X", "POST", BASE] + HEADERS + ["-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    return json.loads(raw)

subprocess.run(
    ["curl", "-s", "-X", "POST", BASE] + HEADERS +
    ["-d", json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"})],
    capture_output=True, timeout=5
)

# Test with date param
result = mcp("tools/call", {
    "name": "broker_holding_detail",
    "arguments": {"symbol": "00700.HK", "date": "2026-06-03"}
})
inner = json.loads(result["result"]["content"][0]["text"])
items = inner.get("list", [])
print(f"Total brokers: {len(items)}")
print(f"Top-level keys: {list(inner.keys())}")

def sf(v):
    try: return float(v)
    except: return 0

by_shares = sorted(items, key=lambda x: sf(x["shares"]["value"]), reverse=True)
for b in by_shares[:5]:
    print(f"  {b['parti_number']} {b['name'][:35]:35s} shares={b['shares']['value']:>12s} ratio={b['ratio']['value']}")

if items:
    print(f"\nSample item keys: {list(items[0].keys())}")
    print(f"Sample shares keys: {list(items[0]['shares'].keys())}")

# Test without date
result2 = mcp("tools/call", {
    "name": "broker_holding_detail",
    "arguments": {"symbol": "00005.HK"}
})
inner2 = json.loads(result2["result"]["content"][0]["text"])
print(f"\n00005.HK (no date): {len(inner2.get('list',[]))} brokers, keys={list(inner2.keys())}")
