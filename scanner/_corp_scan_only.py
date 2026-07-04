"""Minimal corp scan — just fetch + export, no extras."""
import sys, os

os.environ.setdefault("CCASS_TELEGRAM_REQUIRE_DEDICATED", "1")

scanner_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(scanner_dir)
sys.path.insert(0, scanner_dir)
sys.path.insert(0, parent_dir)

import hk_cloud_scanner

print("=== Step 1: Fetch corp announcements ===", flush=True)
raw_anns = hk_cloud_scanner.fetch_corp_action_announcements()
print(f"Fetched {len(raw_anns)} announcements", flush=True)

today_hkt = hk_cloud_scanner.hkt_today_str()
anns = [a for a in raw_anns if a.get('release_date') == today_hkt]
print(f"Today ({today_hkt}) matches: {len(anns)}", flush=True)

print("=== Step 2: Export breakthroughs.json ===", flush=True)
try:
    from scanner.breakthrough_detector import export_breakthroughs_json
    export_breakthroughs_json()
    print("[breakthrough] export OK", flush=True)
except Exception as exc:
    print(f"[breakthrough] export failed: {exc}", flush=True)

print("=== Step 3: Update announcements.json ===", flush=True)
try:
    hk_cloud_scanner._update_announcements_json(raw_anns)
    print("[corp] announcements.json update OK", flush=True)
except Exception as exc:
    print(f"[corp] announcements.json update failed: {exc}", flush=True)

print("=== DONE ===", flush=True)
