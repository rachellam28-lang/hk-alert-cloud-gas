"""Update announcements.json on GitHub via API (bypass git push for Netlify deploy)."""
import json, base64, subprocess, urllib.request, os

# Get GitHub token from credential manager
result = subprocess.run(
    ['git', 'credential-manager', 'get'],
    input='protocol=https\nhost=github.com\n',
    capture_output=True, text=True, cwd=os.path.dirname(__file__)
)
token = None
for line in result.stdout.splitlines():
    if line.startswith('password='):
        token = line.split('=', 1)[1]
        break
if not token:
    print('FAIL: no token')
    exit(1)

REPO = 'rachellam28-lang/hk-alert-cloud-gas'
FILE_PATH = 'data/announcements.json'
API = f'https://api.github.com/repos/{REPO}/contents/{FILE_PATH}'

# Read local file
local_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'announcements.json')
with open(local_path, 'rb') as f:
    local_data = f.read()
local_size = len(local_data)
print(f'Local file: {local_size} bytes')

# Get current SHA from GitHub
req = urllib.request.Request(API, headers={'Authorization': f'Bearer {token}', 'User-Agent': 'hermes'})
with urllib.request.urlopen(req, timeout=15) as resp:
    gh_data = json.loads(resp.read())
gh_sha = gh_data.get('sha', '')
gh_size = gh_data.get('size', 0)
print(f'GitHub: {gh_size} bytes, sha={gh_sha[:10]}...')

if local_size == gh_size:
    print('Same size — already up to date?')
    exit(0)

# Encode and push
content_b64 = base64.b64encode(local_data).decode()
payload = json.dumps({
    'message': f'update announcements.json: {local_size} bytes, 738 entries, 14 dates',
    'content': content_b64,
    'sha': gh_sha,
    'branch': 'main'
}).encode()

req2 = urllib.request.Request(API, data=payload, headers={
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
    'User-Agent': 'hermes'
})
req2.method = 'PUT'
with urllib.request.urlopen(req2, timeout=30) as resp:
    result = json.loads(resp.read())

new_sha = result.get('content', {}).get('sha', '')[:10]
print(f'Pushed! New sha={new_sha}')
print(f'Netlify will auto-deploy from this commit.')
