import json, os, datetime, sqlite3
from pathlib import Path

base = Path("C:/Users/Administrator/Desktop/automatic/ccass-debug")

# Current time
now = datetime.datetime.now()
print(f"Current UTC: {now.isoformat()}")
print(f"Current HKT approx: {(now + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')}")
today = datetime.date.today().isoformat()
print(f"Today: {today}")
print()

# Tier 1
print("--- Tier 1: corp_scan_result.json ---")
t1 = base / "scanner" / "corp_scan_result.json"
if t1.exists():
    m = datetime.datetime.fromtimestamp(t1.stat().st_mtime)
    d = json.loads(t1.read_text())
    s = d.get("summary", {})
    print(f"  mtime: {m.isoformat()}")
    print(f"  date_iso: {s.get('date_iso', '?')}")
    print(f"  alerted: {len(d.get('alerted',[]))} watchlisted: {len(d.get('watchlisted',[]))}")
    print(f"  today_count: {s.get('today_count',0)} total_raw: {s.get('total_raw',0)}")
    print(f"  volume_multiplier: {s.get('volume_multiplier',1.5)}")
    # Dump alerted/watched codes
    for a in d.get("alerted", []):
        print(f"  ALERT: {a.get('code','?')} {a.get('name','?')} types={a.get('types',[])} vr={a.get('volume_ratio',0)}")
    for a in d.get("watchlisted", []):
        print(f"  WATCH: {a.get('code','?')} {a.get('name','?')} types={a.get('types',[])} vr={a.get('volume_ratio',0)}")
else:
    print("  NOT FOUND")

# Tier 2
print("\n--- Tier 2: alerts.json ---")
t2a = base / "data" / "alerts.json"
if t2a.exists():
    m = datetime.datetime.fromtimestamp(t2a.stat().st_mtime)
    d = json.loads(t2a.read_text())
    print(f"  mtime: {m.isoformat()} count: {len(d.get('alerts',[]))}")
else:
    print("  NOT FOUND")

print("--- Tier 2: watchlist.json ---")
t2w = base / "data" / "watchlist.json"
if t2w.exists():
    m = datetime.datetime.fromtimestamp(t2w.stat().st_mtime)
    d = json.loads(t2w.read_text())
    print(f"  mtime: {m.isoformat()} count: {len(d.get('watchlist',[]))}")
else:
    print("  NOT FOUND")

# Tier 3
print("\n--- Tier 3: announcements.json ---")
t3 = base / "data" / "announcements.json"
if t3.exists():
    m = datetime.datetime.fromtimestamp(t3.stat().st_mtime)
    d = json.loads(t3.read_text())
    print(f"  mtime: {m.isoformat()} count: {len(d)}")
else:
    print("  NOT FOUND")

print("--- Tier 3: confluence.json ---")
t3c = base / "data" / "confluence.json"
if t3c.exists():
    m = datetime.datetime.fromtimestamp(t3c.stat().st_mtime)
    d = json.loads(t3c.read_text())
    print(f"  mtime: {m.isoformat()} count: {len(d.get('announcements',[]))}")
else:
    print("  NOT FOUND")

# DB check
print("\n--- DB: scanner_alerts ---")
db = base / "ccass" / "ccass.db"
if db.exists():
    con = sqlite3.connect(str(db))
    c = con.cursor()
    c.execute("SELECT COUNT(*) FROM scanner_alerts WHERE category='corp_action' AND created_at LIKE ?", (f"{today}%",))
    ca = c.fetchone()[0]
    print(f"  scanner_alerts (corp_action, today): {ca}")
    c.execute("SELECT COUNT(*) FROM scanner_watchlist WHERE created_at LIKE ?", (f"{today}%",))
    cw = c.fetchone()[0]
    print(f"  scanner_watchlist (today): {cw}")
    con.close()
else:
    print("  ccass.db NOT FOUND")
