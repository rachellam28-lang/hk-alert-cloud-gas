"""Self-contained corp backfill — fetches HKEX announcements directly and forwards to GAS."""
import json, sys, os, time, urllib.request, urllib.parse, html, re

HKEX_BASE = "https://www1.hkexnews.hk"
GAS_URL = "https://script.google.com/macros/s/AKfycbw4ySZih9cXdtPDzkr9QkVAY-UrIdfl1SXcUE64Q_dxk-nytyr7RnnFXEquk_qb_A54DA/exec"
S = "".join(["3vzh77WnYKjHRDX8", "mPq2xkF9tbLsU4nA"])

# --- HKEX fetch (minimal, no heavy imports) ---
def fetch_announcements():
    """Fetch corp action announcements from HKEX 7-day feed."""
    # Get max pages
    url1 = f"{HKEX_BASE}/ncms/json/eds/lcisehk7relsde_1.json"
    try:
        with urllib.request.urlopen(url1, timeout=20) as resp:
            data = json.loads(resp.read())
        max_pages = int(data.get("maxNumOfFile", 1))
    except Exception as e:
        print(f"First page failed: {e}", flush=True)
        return []
    
    all_rows = []
    for page in range(1, max_pages + 1):
        url = f"{HKEX_BASE}/ncms/json/eds/lcisehk7relsde_{page}.json"
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                data = json.loads(resp.read())
            rows = data.get("newsInfoLst", [])
            all_rows.extend(rows)
        except Exception as e:
            print(f"Page {page} failed: {e}", flush=True)
    
    # Parse announcements
    announcements = []
    for row in all_rows:
        if str(row.get("t1Code", "")) != "10000":
            continue
        title = _html_to_text(row.get("title", ""))
        headline = _html_to_text(row.get("lTxt", ""))
        short = _html_to_text(row.get("sTxt", ""))
        combined = f"{headline} {short} {title}"
        
        # Classify corp action
        types_list = _classify(combined)
        if not types_list:
            continue
        
        web_path = str(row.get("webPath", ""))
        doc_url = web_path if web_path.startswith("http") else HKEX_BASE + web_path
        rel_time = row.get("relTime", "")
        release_date = _parse_date(rel_time)
        
        for stock in row.get("stock", []):
            code = str(stock.get("sc", "")).zfill(5)
            name = _html_to_text(stock.get("sn", ""))
            announcements.append({
                "code": code,
                "name": name,
                "types": types_list,
                "title": title or headline,
                "release_time": rel_time,
                "release_date": release_date,
                "url": doc_url,
            })
    
    return announcements

def _html_to_text(s):
    if not s: return ""
    s = html.unescape(str(s))
    s = re.sub(r'<[^>]+>', ' ', s)
    return ' '.join(s.split())

def _parse_date(rel_time):
    """Parse HKEX relTime like '05/06/2026 22:58'."""
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', str(rel_time))
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""

CORP_KEYWORDS = {
    "配股": ["配售", "配股", "PLACING", "PLACEMENT", "TOP-UP"],
    "供股": ["供股", "RIGHTS ISSUE", "RIGHT ISSUE", "OPEN OFFER"],
    "合股": ["合併", "股份合併", "SHARE CONSOLIDATION", "CONSOLIDATION"],
    "拆細": ["拆細", "股份拆細", "SHARE SPLIT", "SUBDIVISION"],
    "增持": ["增持", "ACQUISITION", "ACQUIRE", "增購"],
    "減持": ["減持", "DISPOSAL", "DISPOSE", "出售"],
    "回購": ["回購", "REPURCHASE", "BUY-BACK", "BUYBACK"],
    "私有化": ["私有化", "PRIVATISATION", "PRIVATIZATION"],
    "特別息": ["特別股息", "SPECIAL DIVIDEND", "SPECIALDIVIDEND"],
    "收購": ["收購", "MERGER", "TAKEOVER", "要約", "OFFER"],
    "轉倉": ["轉倉", "TRANSFER", "大手轉倉"],
    "大手上板": ["大手上板", "BLOCK TRADE", "CROSS TRADE"],
    "股息": ["股息", "DIVIDEND", "分紅", "末期息", "中期息"],
    "盈警": ["盈警", "PROFIT WARNING", "虧損", "LOSS"],
    "盈喜": ["盈喜", "PROFIT ALERT", "盈利預喜", "POSITIVE PROFIT"],
    "業績": ["業績", "年報", "年終業績", "中期業績", "ANNUAL RESULTS", "INTERIM RESULTS"],
    "董事變更": ["董事變更", "董事辭任", "委任董事", "DIRECTOR", "RESIGNATION"],
    "其他": ["須予披露", "關連交易", "NOTIFIABLE", "CONNECTED TRANSACTION"],
}

def _classify(text):
    t = text.upper()
    result = []
    for cat, keywords in CORP_KEYWORDS.items():
        for kw in keywords:
            if kw.upper() in t:
                result.append(cat)
                break
    return result if result else []

# --- GAS Bearer ---
def get_bearer():
    rc_path = os.path.expanduser("~/.clasprc.json")
    with open(rc_path) as f:
        rc = json.load(f)
    tok = rc["tokens"]["default"]
    data = urllib.parse.urlencode({
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]

# --- Main ---
print("Fetching HKEX announcements...", flush=True)
anns = fetch_announcements()
print(f"Got {len(anns)} corp announcements", flush=True)

# Show date distribution
from collections import Counter
dates = Counter(a["release_date"] for a in anns)
for d in sorted(dates):
    print(f"  {d}: {dates[d]}", flush=True)

print("\nGetting bearer token...", flush=True)
bearer = get_bearer()
print(f"Bearer: {bearer[:20]}...", flush=True)

ok = err = 0
seen = set()
for ann in anns:
    code = ann["code"]
    rd = ann["release_date"]
    types_str = " / ".join(ann["types"])
    key = f"{code}|{rd}|{types_str}"
    if key in seen:
        continue
    seen.add(key)

    p = {
        "secret": S,
        "created_at": f"{rd}T09:00:00+08:00" if rd else "",
        "source": "backfill",
        "category": "corp_action",
        "code": code,
        "symbol": code,
        "name": ann["name"],
        "signal": types_str,
        "message": str(ann["title"])[:500],
        "price": "",
        "chart_url": "",
        "source_url": ann["url"],
        "tags": "",
        "announcement_date": rd,
        "release_time": ann.get("release_time", ""),
    }

    data = json.dumps(p).encode()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"}
    try:
        req = urllib.request.Request(GAS_URL, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read())
            if r.get("ok"):
                ok += 1
            else:
                err += 1
    except Exception:
        err += 1

    if (ok + err) % 20 == 0:
        print(f"  {ok+err}/{len(anns)} ok={ok} err={err}", flush=True)
    time.sleep(0.1)

print(f"\nDONE: {ok} ok, {err} err, {len(anns)} total", flush=True)

# Save locally for dashboard
try:
    import json as _json, os as _os
    _proj = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _path = _os.path.join(_proj, 'data', 'announcements.json')
    _existing = []
    if _os.path.exists(_path):
        with open(_path, 'r', encoding='utf-8') as _f:
            _existing = _json.load(_f)
    _seen = set()
    for _a in _existing:
        _seen.add((str(_a.get('code','')).zfill(5), _a.get('date',''), ' / '.join(_a.get('types',[]))))
    _type_map = {'配股':'placement','供股':'rights','合股':'consolidation','拆細':'split','增持':'increase','減持':'decrease','回購':'buyback','私有化':'privatisation','特別息':'special_div','收購':'acquisition','轉倉':'transfer','大手上板':'block_trade','股息':'dividend','盈警':'warning','盈喜':'alert','業績':'results','董事變更':'director','其他':'other'}
    _new = 0
    for _ann in anns:
        _code = str(_ann.get('code','')).zfill(5)
        _rd = _ann.get('release_date','')
        _tl = _ann.get('types',[]) if isinstance(_ann.get('types'), list) else [_ann.get('types','')]
        _ts = ' / '.join(_tl)
        if (_code, _rd, _ts) in _seen: continue
        _seen.add((_code, _rd, _ts))
        _ft = _tl[0] if _tl else '其他'
        _existing.append({'code':_code,'name':_ann.get('name',''),'types':_tl,'title':_ann.get('title',''),'date':_rd,'url':_ann.get('url',''),'type':_type_map.get(_ft,'other'),'typeLabel':_ts})
        _new += 1
    _existing.sort(key=lambda x: x.get('date',''), reverse=True)
    _os.makedirs(_os.path.dirname(_path), exist_ok=True)
    with open(_path, 'w', encoding='utf-8') as _f:
        _json.dump(_existing, _f, ensure_ascii=False)
    print(f"Saved {_new} new to {_path} ({len(_existing)} total)", flush=True)
except Exception as _exc:
    print(f"Local save failed: {_exc}", flush=True)
