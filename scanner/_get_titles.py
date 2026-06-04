"""Get full title for announcements."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hk_cloud_scanner import fetch_corp_action_announcements, hkt_today_str

today_hkt = hkt_today_str()
raw = fetch_corp_action_announcements()

for ann in raw:
    if ann.get("release_date") == today_hkt:
        print(f"CODE={ann['code']}")
        print(f"NAME={ann['name']}")
        print(f"FULL_TITLE={ann['title']}")
        print(f"TITLE_EN={ann.get('title_en', '')}")
        print()
