"""Minimal test — what's hanging?"""
import os, sys, time

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
print('[1] .env loaded', flush=True)

# Add scanner to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scanner'))
print('[2] path set', flush=True)

# Import scanner module
print('[3] importing hk_cloud_scanner...', flush=True)
import hk_cloud_scanner
print('[4] import done', flush=True)

# Test fetch function
print('[5] calling fetch_corp_action_announcements...', flush=True)
t0 = time.time()
result = hk_cloud_scanner.fetch_corp_action_announcements()
t1 = time.time()
print(f'[6] fetch done: {len(result)} announcements in {t1-t0:.1f}s', flush=True)

# Show first few
for i, ann in enumerate(result[:5]):
    print(f'  [{i}] {ann.get("code")} {ann.get("name")} types={ann.get("types")}', flush=True)

print('[DONE]', flush=True)
