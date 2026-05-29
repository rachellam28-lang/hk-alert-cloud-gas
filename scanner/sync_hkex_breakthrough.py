"""Feed HKEXnews announcements into breakthrough detector.
Uses the HKEXnews JSON feed (same as hk_cloud_scanner.py) — NO PDF downloads needed.
Titles already contain prices like "PLACING ... AT HK$0.38 PER SHARE".
"""
import sys, os
from pathlib import Path

PROJ = Path(__file__).parent.parent
sys.path.insert(0, str(PROJ))

from scanner.hk_cloud_scanner import fetch_corp_action_announcements
from scanner.breakthrough_detector import add_prices_from_announcements, export_breakthroughs_json

print("Fetching HKEXnews announcements (last 7 days)...")
anns = fetch_corp_action_announcements()

# Filter to only placement/rights
relevant = [a for a in anns if any(t in a.get('types',[]) for t in ['配股','供股'])]
print(f"Total announcements: {len(anns)}, placement/rights: {len(relevant)}")

if relevant:
    print("\nSample titles:")
    for a in relevant[:5]:
        cn = a.get('title', '')[:100]
        print(f"  {a.get('code','?')} {a.get('types',[])}: {cn}")

print("\nExtracting prices...")
n = add_prices_from_announcements(relevant)
print(f"Added {n} new prices")

print("\nExporting breakthroughs...")
export_breakthroughs_json()
print("Done!")
