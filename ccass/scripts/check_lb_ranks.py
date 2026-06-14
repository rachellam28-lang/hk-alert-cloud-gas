"""Query Longbridge MCP for HK popularity rankings."""
import subprocess, json, os

def get_token():
    for p in [
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]:
        p = os.path.normpath(p)
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    if "LONGBRIDGE_ACCESS_TOKEN=" in line:
                        return line.strip().split("=", 1)[1]
    return os.environ.get("LONGBRIDGE_ACCESS_TOKEN", "")

TOKEN = get_token()
if not TOKEN:
    print("ERROR: No token found")
    exit(1)

def mcp(method, args=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": method, "arguments": args or {}}}
    r = subprocess.run([
        "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-H", "Authorization: Bearer " + TOKEN,
        "-d", json.dumps(body),
    ], capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    res = json.loads(raw)
    content = res.get("result", {}).get("content", [])
    if content:
        return json.loads(content[0]["text"])
    return res

for key in ["hot_all-hk", "watchlist_heat-hk", "discuss_heat-hk"]:
    print(f"\n=== {key} ===")
    data = mcp("rank_list", {"key": key})
    for item in data.get("items", [])[:10]:
        sym = item.get("symbol", "?")
        name = item.get("name", "")[:25]
        last = item.get("last_done", "")
        chg = item.get("change_rate", "")
        print(f"  {sym:12s} {name:25s} {str(last):>10s} {str(chg):>10s}")

# Market temperature
print("\n=== market_temperature ===")
temp = mcp("market_temperature")
print(json.dumps(temp, ensure_ascii=False, indent=2))
