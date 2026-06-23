"""Import the actual scanner module and run corp action."""
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

log('[2] importing hk_cloud_scanner module...')
try:
    import hk_cloud_scanner
    log('[2a] module imported ok')
    log(f'  TELEGRAM_TOKEN set: {bool(hk_cloud_scanner.TELEGRAM_TOKEN)}')
    log(f'  _tg_pusher: {hk_cloud_scanner._tg_pusher}')
except Exception as e:
    log(f'[2a] IMPORT FAILED: {e}')
    import traceback
    log(traceback.format_exc())
    LOG.close()
    sys.exit(1)

log('[3] calling fetch_corp_action_announcements()...')
try:
    t0 = time.time()
    raw = hk_cloud_scanner.fetch_corp_action_announcements()
    t1 = time.time()
    log(f'[3a] Got {len(raw)} raw announcements in {t1-t0:.1f}s')
except Exception as e:
    log(f'[3] FAILED: {e}')
    import traceback
    log(traceback.format_exc())

log('[4] calling run_corp_actions()...')
try:
    t0 = time.time()
    hk_cloud_scanner.run_corp_actions()
    t1 = time.time()
    log(f'[4a] run_corp_actions done in {t1-t0:.1f}s')
except Exception as e:
    log(f'[4] FAILED: {e}')
    import traceback
    log(traceback.format_exc())

log('[DONE]')
LOG.close()
