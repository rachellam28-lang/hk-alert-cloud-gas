import json
import urllib.request
import urllib.error

token = ''
try:
    with open(r'C:\Users\Administrator\Desktop\automatic\ccass-debug\.env') as f:
        for line in f:
            line = line.strip()
            if line.startswith('GITHUB_TOKEN=***                token = line.split('=', 1)[1].strip().strip('"').strip("'")
                break
except:
    pass

headers = {'User-Agent': 'Hermes', 'Accept': 'application/vnd.github+json'}
if token:
    headers['Authorization'] = f'Bearer {token}'

# Check Pages
try:
    url = 'https://api.github.com/repos/rachellam28-lang/hk-alert-cloud-gas/pages'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        pages = json.loads(resp.read())
        print(f"Pages: status={pages.get('status')}, url={pages.get('html_url')}")
except urllib.error.HTTPError as e:
    print(f"Pages API: HTTP {e.code}")

# Get content via API
try:
    url = 'https://api.github.com/repos/rachellam28-lang/hk-alert-cloud-gas/contents/holdings.json?ref=main'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        import base64
        content = base64.b64decode(data['content']).decode('utf-8')
        j = json.loads(content)
        print(f"API file: updated={j.get('updated')}, stocks={len(j.get('stocks',[]))}")
except urllib.error.HTTPError as e:
    print(f"Contents API: HTTP {e.code}")
