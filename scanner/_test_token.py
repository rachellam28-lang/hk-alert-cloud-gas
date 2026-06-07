"""Test Telegram bot token from .env file."""
import os
import sys

# Read .env from parent dir
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
with open(env_path, 'rb') as f:
    raw = f.read()

# Find line with TELEGRAM_TOKEN
lines = raw.split(b'\n')
token = None
chat_id = '-1003009204094'

for line in lines:
    line = line.strip()
    if line.startswith(b'TELEGRAM_TOKEN='):
        token = line.split(b'=', 1)[1].strip().decode()
        break

if not token:
    print('ERROR: Token not found')
    sys.exit(1)

print(f'Token length: {len(token)}')
print(f'Token starts: {token[:10]}...')
print(f'Token ends: ...{token[-10:]}')

import requests

# Test getMe
try:
    r = requests.get(f'https://api.telegram.org/bot{token}/getMe', timeout=10)
    print(f'\ngetMe: HTTP {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'Bot username: @{data["result"]["username"]}')
        print(f'Bot name: {data["result"]["first_name"]}')
        print('✅ Token is VALID')
    else:
        print(f'Error: {r.text[:300]}')
except Exception as e:
    print(f'Exception: {e}')

# Test sendMessage
try:
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': '🧪 *CCASS TelegramPusher 測試*\n\n直接推送通道已建立，無需經過 GAS。\n\n✅ 如果你睇到呢條訊息，代表 TelegramPusher 工作正常。',
        'parse_mode': 'Markdown',
    }
    r = requests.post(url, json=payload, timeout=15)
    print(f'\nsendMessage: HTTP {r.status_code}')
    data = r.json()
    print(f'ok={data.get("ok")}')
    if not data.get('ok'):
        print(f'Error: {data.get("description", "")[:200]}')
    else:
        print(f'message_id={data["result"]["message_id"]}')
        print('✅ Message sent successfully!')
except Exception as e:
    print(f'Exception: {e}')
