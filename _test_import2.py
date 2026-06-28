"""Minimal test with file logging — what's hanging?"""
import os, sys, time

LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '_corp_run.log'), 'w', encoding='utf-8')

def log(msg):
    LOG.write(f"{msg}\n")
    LOG.flush()
    print(msg, flush=True)

# Load .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val
log('[1] .env loaded')

# Add scanner to path
scanner_dir = os.path.join(os.path.dirname(__file__), 'scanner')
sys.path.insert(0, scanner_dir)
log('[2] path set')

# Import scanner module piece by piece
log('[3] importing tools...')
import requests; log('  requests ok')
import pandas; log('  pandas ok')

log('[4] importing telegram_pusher...')
from telegram_pusher import TelegramPusher
log('  telegram_pusher ok')

log('[5] importing local_alert_store...')
from local_alert_store import store_alert, fetch_watchlist, add_to_watchlist
log('  local_alert_store ok')

log('[6] Done! All imports successful.')
LOG.close()
