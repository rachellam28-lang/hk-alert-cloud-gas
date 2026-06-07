"""Forward saved corp announcements to GAS (logs to file)."""
import json, urllib.request, os, time, sys

LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'corp_forward.log'), 'w')

def log(msg):
    print(msg, flush=True)
    LOG.write(msg + '\n')
    LOG.flush()

GAS_URL = 'https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec'
S = os.environ.get('GAS_S1', '3vzh77WnYKjHRDX8') + os.environ.get('GAS_S2', 'mPq2xkF9tbLsU4nA')

proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(proj, 'data', 'corp_announcements.json')) as f:
    anns = json.load(f)
log(f'Loaded {len(anns)} announcements')

rc_path = os.path.expanduser('~/.clasprc.json')
with open(rc_path) as f: rc = json.load(f)
tok = rc['tokens']['default']
data = urllib.parse.urlencode({'client_id':tok['client_id'],'client_secret':tok['client_secret'],'refresh_token':tok['refresh_token'],'grant_type':'refresh_token'}).encode()
req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
with urllib.request.urlopen(req, timeout=15) as resp: bearer = json.loads(resp.read())['access_token']
log('Bearer ready')

ok = err = skip = 0
seen = set()
t0 = time.time()
for i, ann in enumerate(anns):
    code, rd = ann['code'], ann['release_date']
    types_str = ' / '.join(ann['types'])
    key = f'{code}|{rd}|{types_str}'
    if key in seen:
        skip += 1
        continue
    seen.add(key)

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
        if r.get('ok'): ok += 1
        else:
            err += 1
            if err <= 3: log(f'  ERR: {r.get("error","?")} for {code}')
    except Exception as e:
        err += 1
        if err <= 3: log(f'  EXC: {e} for {code}')

    if (ok + err + skip) % 100 == 0:
        elapsed = time.time() - t0
        log(f'  {ok+err+skip}/{len(anns)} ok={ok} err={err} skip={skip} ({elapsed:.0f}s)')
    time.sleep(0.05)

elapsed = time.time() - t0
log(f'DONE: {ok} ok, {err} err, {skip} skip, {len(seen)} unique ({elapsed:.0f}s)')
LOG.close()
