"""Fetch + forward HKEX corp announcements to GAS."""
import json, urllib.request, html, re, os, time, sys

HKEX = 'https://www1.hkexnews.hk'
GAS_URL = 'https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec'
S = ''.join(['3vzh77WnYKjHRDX8', 'mPq2xkF9tbLsU4nA'])

def _html_to_text(s):
    if not s: return ''
    s = html.unescape(str(s))
    s = re.sub(r'<[^>]+>', ' ', s)
    return ' '.join(s.split())

def _parse_date(rel_time):
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', str(rel_time))
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''

CORP_KW = {'配股':['配售','配股','PLACING','PLACEMENT','TOP-UP'],'供股':['供股','RIGHTS ISSUE','OPEN OFFER'],'合股':['合併','股份合併','CONSOLIDATION'],'增持':['增持','ACQUISITION','ACQUIRE'],'減持':['減持','DISPOSAL','DISPOSE'],'回購':['回購','REPURCHASE','BUY-BACK','BUYBACK'],'收購':['收購','MERGER','TAKEOVER','要約'],'轉倉':['轉倉','TRANSFER','大手轉倉'],'股息':['股息','DIVIDEND','分紅'],'盈警':['盈警','PROFIT WARNING'],'盈喜':['盈喜','PROFIT ALERT'],'業績':['業績','年報','RESULTS'],'其他':['須予披露','關連交易','NOTIFIABLE','CONNECTED']}

def _classify(text):
    t = text.upper(); result = []
    for cat, kws in CORP_KW.items():
        for kw in kws:
            if kw.upper() in t: result.append(cat); break
    return result

log = open(os.path.join(os.path.dirname(__file__), 'corp_backfill.log'), 'w')

def log_print(msg):
    print(msg, flush=True)
    log.write(msg + '\n')
    log.flush()

log_print('Fetching from HKEX...')
url1 = f'{HKEX}/ncms/json/eds/lcisehk7relsde_1.json'
with urllib.request.urlopen(url1, timeout=20) as resp:
    d = json.loads(resp.read())
max_pages = int(d.get('maxNumOfFile', 1))
log_print(f'Max pages: {max_pages}')

anns = []
for page in range(1, min(max_pages+1, 14)):
    url = f'{HKEX}/ncms/json/eds/lcisehk7relsde_{page}.json'
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read())
    for row in data.get('newsInfoLst', []):
        if str(row.get('t1Code','')) != '10000': continue
        title = _html_to_text(row.get('title',''))
        headline = _html_to_text(row.get('lTxt',''))
        types = _classify(f'{headline} {title}')
        if not types: continue
        web_path = str(row.get('webPath',''))
        doc_url = web_path if web_path.startswith('http') else HKEX + web_path
        rd = _parse_date(row.get('relTime',''))
        for stock in row.get('stock', []):
            anns.append({'code':str(stock.get('sc','')).zfill(5),'name':_html_to_text(stock.get('sn','')),'types':types,'title':title or headline,'release_date':rd,'url':doc_url,'release_time':row.get('relTime','')})
    log_print(f'Page {page}: {len(anns)} total')

log_print(f'Fetched {len(anns)} anns')

# Get bearer token
rc_path = os.path.expanduser('~/.clasprc.json')
with open(rc_path) as f: rc = json.load(f)
tok = rc['tokens']['default']
data = urllib.parse.urlencode({'client_id':tok['client_id'],'client_secret':tok['client_secret'],'refresh_token':tok['refresh_token'],'grant_type':'refresh_token'}).encode()
req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
with urllib.request.urlopen(req, timeout=15) as resp: bearer = json.loads(resp.read())['access_token']
log_print('Bearer ready')

# Forward
ok = err = 0
seen = set()
for ann in anns:
    code, rd = ann['code'], ann['release_date']
    types_str = ' / '.join(ann['types'])
    key = f'{code}|{rd}|{types_str}'
    if key in seen: continue
    seen.add(key)
    p = {'secret':S,'created_at':f'{rd}T09:00:00+08:00' if rd else '','source':'backfill','category':'corp_action','code':code,'symbol':code,'name':ann['name'],'signal':types_str,'message':str(ann['title'])[:500],'price':'','chart_url':'','source_url':ann['url'],'tags':'','announcement_date':rd,'release_time':ann.get('release_time','')}
    d2 = json.dumps(p).encode()
    hdrs = {'Content-Type':'application/json','Authorization':f'Bearer {bearer}'}
    try:
        req2 = urllib.request.Request(GAS_URL, data=d2, headers=hdrs, method='POST')
        with urllib.request.urlopen(req2, timeout=15) as resp: r = json.loads(resp.read())
        if r.get('ok'): ok += 1
        else: err += 1
    except Exception as e: err += 1
    if (ok+err) % 100 == 0: log_print(f'  {ok+err}/{len(seen)} ok={ok} err={err}')
    time.sleep(0.05)

log_print(f'DONE: {ok} ok, {err} err, {len(seen)} unique total')
log.close()
