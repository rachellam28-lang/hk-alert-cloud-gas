"""Forward corp announcements to GAS in resumable batches."""
import json, urllib.request, os, time, sys

GAS_URL = 'https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec'
S = '3vzh77WnYKjHRDX8mPq2xkF9tbLsU4nA'
BATCH_SIZE = 100
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'corp_forward_state.json')

# Load announcements
proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(proj, 'data', 'corp_announcements.json')) as f:
    anns = json.load(f)

# Load or init state
if os.path.exists(STATE_FILE):
    with open(STATE_FILE) as f:
        state = json.load(f)
    processed = set(state.get('done', []))
    offset = state.get('offset', 0)
else:
    processed = set()
    offset = 0

# Get bearer token
rc_path = os.path.expanduser('~/.clasprc.json')
with open(rc_path) as f: rc = json.load(f)
tok = rc['tokens']['default']
data = urllib.parse.urlencode({'client_id':tok['client_id'],'client_secret':tok['client_secret'],'refresh_token':tok['refresh_token'],'grant_type':'refresh_token'}).encode()
req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
with urllib.request.urlopen(req, timeout=15) as resp: bearer = json.loads(resp.read())['access_token']

# Process one batch
ok = err = skip = 0
end = min(offset + BATCH_SIZE, len(anns))
t0 = time.time()

for i in range(offset, end):
    ann = anns[i]
    code, rd = ann['code'], ann['release_date']
    types_str = ' / '.join(ann['types'])
    key = f'{code}|{rd}|{types_str}'
    if key in processed:
        skip += 1
        continue

    p = {
        'secret': S, 'created_at': f'{rd}T09:00:00+08:00' if rd else '',
        'source': 'backfill', 'category': 'corp_action',
        'code': code, 'symbol': code, 'name': ann['name'],
        'signal': types_str, 'message': str(ann['title'])[:500],
        'price': '', 'chart_url': '', 'source_url': ann['url'], 'tags': '',
        'announcement_date': rd, 'release_time': ann.get('release_time', ''),
    }
    d2 = json.dumps(p).encode()
    hdrs = {'Content-Type': 'application/json', 'Authorization': f'Bearer {bearer}'}
    try:
        req2 = urllib.request.Request(GAS_URL, data=d2, headers=hdrs, method='POST')
        with urllib.request.urlopen(req2, timeout=15) as resp:
            r = json.loads(resp.read())
        if r.get('ok'):
            ok += 1
            processed.add(key)
        else:
            err += 1
    except:
        err += 1
    time.sleep(0.05)

# Save state
new_offset = end if err == 0 else offset  # don't advance if errors
state = {'offset': end, 'done': list(processed), 'total': len(anns), 'ok': ok, 'err': err, 'skip': skip}
with open(STATE_FILE, 'w') as f:
    json.dump(state, f)

elapsed = time.time() - t0
remaining = len(anns) - end
print(f'Batch {offset}-{end}: {ok} ok, {err} err, {skip} skip ({elapsed:.0f}s)')
print(f'Remaining: {remaining}, Total done: {len(processed)}')
if remaining > 0:
    print(f'Run again to continue. State saved to {STATE_FILE}')
else:
    print('ALL DONE!')
    os.remove(STATE_FILE)
