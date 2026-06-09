"""Check tool schemas for rank_list and market_temperature."""
import subprocess, json, os

def get_token():
    for p in [os.path.expanduser("~/Desktop/automatic/holdings-debug/.env")]:
        p = os.path.normpath(p)
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    if line.startswith("LONGBRIDGE_ACCESS_TOKEN=***                        return line.strip().split("=", 1)[1]
    return ""

TOKEN=*** not TOKEN:
    print("No token")
    exit(1)

body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
r = subprocess.run([
    "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
    "-H", "Content-Type: application/json",
    "-H", "Accept: application/json, text/event-stream",
    "-H", "Authorization: Bearer *** + TOKEN,
    "-d", json.dumps(body),
], capture_output=True, text=True, timeout=15)

raw = r.stdout.strip()
if raw.startswith("data: "):
    raw = raw[6:]
tools = json.loads(raw)["result"]["tools"]

for t in tools:
    if t["name"] in ["rank_list", "market_temperature", "rank_categories"]:
        print(f"\n{'='*50}")
        print(f"TOOL: {t['name']}")
        print(f"DESC: {t.get('description', '')}")
        props = t.get("inputSchema", {}).get("properties", {})
        required = t.get("inputSchema", {}).get("required", [])
        print("PARAMS:")
        for k, v in props.items():
            req = " [REQUIRED]" if k in required else ""
            print(f"  {k}: {v.get('type','?')} — {v.get('description','')}{req}")
