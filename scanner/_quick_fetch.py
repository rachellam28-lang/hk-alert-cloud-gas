"""Quick fetch of today's HKEX corp announcements."""
import sys, os, json

# Ensure scanner dir is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hk_cloud_scanner import fetch_corp_action_announcements, hkt_today_str

today_hkt = hkt_today_str()
print(f"TODAY_HKT={today_hkt}")

raw = fetch_corp_action_announcements()
print(f"TOTAL_RAW={len(raw)}")

today_anns = []
for ann in raw:
    if ann.get("release_date") == today_hkt:
        today_anns.append(ann)

print(f"TODAY_ANNS={len(today_anns)}")

for i, ann in enumerate(today_anns):
    print(f"\n=== ANN_{i} ===")
    print(f"CODE={ann.get('code')}")
    print(f"NAME={ann.get('name')}")
    print(f"TYPES={'|'.join(ann.get('types', []))}")
    print(f"TITLE={ann.get('title')}")
    print(f"URL={ann.get('url')}")
    print(f"RELEASE_TIME={ann.get('release_time')}")
    print(f"RELEASE_DATE={ann.get('release_date')}")
