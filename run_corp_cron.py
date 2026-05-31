"""
HK Cloud Scanner - Corp Actions Runner (Cron)
Skips breakthrough export to save time.
"""
import sys, os

# ── Load .env ──
env_path = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\.env"
if os.path.exists(env_path):
    from dotenv import load_dotenv
    load_dotenv(env_path)
    print(f"[dotenv] loaded {env_path}")

# ── Add scanner dir to path ──
proj = r"C:\Users\Administrator\Desktop\automatic\ccass-debug"
if proj not in sys.path:
    sys.path.insert(0, proj)

# ── Monkey-patch breakthrough exports to skip (saves ~4 min) ──
import scanner.breakthrough_detector as btd
_orig_export = btd.export_breakthroughs_json
_orig_add = btd.add_prices_from_announcements

btd.export_breakthroughs_json = lambda: print("[breakthrough] export skipped (cron)")
btd.add_prices_from_announcements = lambda anns: 0

# ── Set env vars for copr-only mode ──
os.environ.setdefault("MAX_STOCKS", "0")
os.environ.setdefault("VOLUME_MULTIPLIER", "1.5")
os.environ.setdefault("VOLUME_AVG_DAYS", "20")
os.environ.setdefault("ANNOUNCEMENT_RANGE_DAYS", "7")

# ── Run corp actions ──
from scanner.hk_cloud_scanner import run_corp_actions
run_corp_actions()
