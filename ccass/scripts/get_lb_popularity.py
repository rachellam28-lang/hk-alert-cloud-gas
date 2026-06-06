"""Get Longbridge HK popularity leaderboard data."""
import subprocess, json, os

env_path = os.path.expanduser("~/Desktop/automatic/ccass-debug/.env")
token = ""
with open(env_path) as f:
    for l in f:
        if "LONGBRIDGE_ACCESS_TOKEN" in l:
            token = l.strip().split("=", 1)[1]
            break
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

boards = [
    ("总热度", "ib_hot_all-hk"),
    ("关注度", "ib_watchlist_heat-hk"),
    ("热议", "ib_discuss_heat-hk"),
]

for label, key in boards:
    data = mcp("rank_list", {"key": key, "market": "HK", "size": 10})
    items = data.get("lists", data.get("items", []))
    print(f"=== {label} ({key}): {len(items)} stocks ===")
    for i in items[:10]:
        code = i.get("code", "?")
        name = i.get("name", "")[:25]
        last = i.get("last_done", "")
        chg = i.get("chg", "")
        print(f"  {code:8s} {name:25s} ${str(last):>10s} chg={str(chg):>10s}")
    print()

# Also market temperature
temp = mcp("market_temperature", {"market": "HK"})
print(f"=== 市場溫度 ===")
print(f"  temperature: {temp.get('temperature')} / 100")
print(f"  sentiment:   {temp.get('sentiment')} / 100")
print(f"  valuation:   {temp.get('valuation')} / 100")
print(f"  desc:        {temp.get('description')}")
