import urllib.request, json, os

token = None
env_path = os.path.join(r"C:\Users\Administrator\Desktop\automatic\ccass-debug", ".env")
with open(env_path) as f:
    for line in f:
        if line.startswith("GITHUB_TOKEN=***            token = line.split('=', 1)[1].strip()
            break
if not token:
    print("NO GITHUB_TOKEN")
    exit(1)

url = "https://api.github.com/repos/rachellam28-lang/hk-alert-cloud-gas/pages"
data = json.dumps({"source": {"branch": "main", "path": "/"}}).encode()
req = urllib.request.Request(url, data=data, method="POST")
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Accept", "application/vnd.github+json")
req.add_header("User-Agent", "Hermes")
try:
    resp = urllib.request.urlopen(req)
    body = json.loads(resp.read())
    print(f"Status: {resp.status}")
    print(f"Pages: {body.get('status')}")
    print(f"URL: {body.get('html_url', '?')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}")
    try:
        err = json.loads(body)
        print(f"Message: {err.get('message', body[:200])}")
        if "errors" in err:
            for error in err["errors"]:
                print(f"  Error: {error}")
    except:
        print(f"Body: {body[:500]}")
