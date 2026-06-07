"""Forward saved corp announcements to GAS."""
import json, urllib.request, os, time

GAS_URL = 'https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec'
S = ''.join(['3vzh77WnYKjHRDX8', 'mPq2xkF9tbLsU4nA'])

# Load saved announcements
proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(proj, 'data', 'corp_announcements.json')) as f:
    anns = json.load(f)
print(f'Loaded {len(anns)} announcements', flush=True)

# Get bearer token
rc_path = os.path.expanduser('~/.clasprc.json')
with open(rc_path) as f: rc = json.load(f)
tok = rc['tokens']['default']
data = urllib.parse.urlencode({'client_id':tok['client_id'],'client_secret':tok['client_secret'],'refresh_token':tok['refresh_token'],'grant_type':'refresh_token'}).encode()
req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
with urllib.request.urlopen(req, timeout=15) as resp: bearer = json.loads(resp.read())['access_token']
print(f'Bearer ready', flush=True)

# Forward
ok = err = skip = 0
seen = set()
for i, ann in enumerate(anns):
    code, rd = ann['code'], ann['release_date']
    types_str = ' / '.join(ann['types'])
    key = f'{code}|{rd}|{types_str}'
    if key in seen:
        skip += 1
        continue
    seen.add(key)

    p = {
        'secret': S,
        'created_at': f'{rd}T09:00:00+08:00' if rd else '',
        'source': 'backfill',
        'category': 'corp_action',
        'code': code, 'symbol': code,
        'name': ann['name'],
        'signal': types_str,
        'message': str(ann['title'])[:500],
        'price': '', 'chart_url': '',
        'source_url': ann['url'], 'tags': '',
        'announcement_date': rd,
        'release_time': ann.get('release_time', ''),
    }
    d2 = json.dumps(p).encode()
    hdrs = {'Content-Type': 'application/json', 'Authorization': f'Bearer {bearer}'}
    try:
        req2 = urllib.request.Request(GAS_URL, data=d2, headers=hdrs, method='POST')
        with urllib.request.urlopen(req2, timeout=15) as resp:
            r = json.loads(resp.read())
        if r.get('ok'): ok += 1
        else:
            err += 1
            err_msg = r.get("error", "?")
            if err <= 3: print(f'  ERR: {err_msg} for {code}', flush=True)
    except Exception as e:
        err += 1
        if err <= 3: print(f'  EXC: {e} for {code}', flush=True)

    if (ok + err + skip) % 100 == 0:
        print(f'  {ok+err+skip}/{len(anns)} ok={ok} err={err} skip={skip}', flush=True)
    time.sleep(0.05)

print(f'DONE: {ok} ok, {err} err, {skip} skip, {len(seen)} unique', flush=True)
