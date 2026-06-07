"""Check Longbridge MCP tool schemas."""
import subprocess, json, os

# Read token
env_path = os.path.expanduser("~/Desktop/automatic/ccass-debug/.env")
token = ""
with open(env_path) as f:
    for line in f:
        if "LONGBRIDGE_ACCESS_TOKEN" in line:
            token = line.strip().split("=", 1)[1]
            break

if not token:
    print("ERROR: Token not found")
    exit(1)

auth = "Bearer " + token
body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

r = subprocess.run([
    "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
    "-H", "Content-Type: application/json",
    "-H", "Accept: application/json, text/event-stream",
    "-H", "Authorization: " + auth,
    "-d", json.dumps(body),
], capture_output=True, text=True, timeout=15)

raw = r.stdout.strip()
if raw.startswith("data: "):
    raw = raw[6:]
tools = json.loads(raw)["result"]["tools"]

for t in tools:
    if t["name"] in ["rank_list", "market_temperature"]:
        print(f"\n{'='*50}")
        print(f"TOOL: {t['name']}")
        print(f"DESC: {t.get('description', '')}")
        req = t.get("inputSchema", {}).get("required", [])
        props = t.get("inputSchema", {}).get("properties", {})
        for k, v in props.items():
            mark = " [REQUIRED]" if k in req else ""
            print(f"  {k}: {v.get('type','?')} - {v.get('description','')}{mark}")
