"""Redeem: test new Longbridge token + update .env"""
import json, subprocess, os

# Read token
token_path = os.path.expandvars(
    r'%USERPROFILE%\.longbridge\openapi\tokens\ff0a3d7d-ca88-42b7-94b0-36f01d773f8c\token.json'
)
with open(token_path) as f:
    data = json.load(f)
token = data['access_token']

# Test API
auth_hdr = f"Authorization: Bearer ***r = subprocess.run([
    'curl', '-s', '-X', 'POST', 'https://mcp.longbridge.com/agent',
    '-H', 'Content-Type: application/json',
    '-H', 'Accept: application/json, text/event-stream',
    '-H', auth_hdr,
    '-d', '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"broker_holding_detail","arguments":{"symbol":"00700.HK"}}}'
], capture_output=True, text=True, timeout=15)

raw = r.stdout.strip()
if raw.startswith('data: '):
    raw = raw[6:]

result = json.loads(raw)
if 'result' in result:
    text = json.loads(result['result']['content'][0]['text'])
    print(f'TEST OK: {len(text["list"])} holdings, updated_at={text["updated_at"]}')
    
    # Update .env - replace old token line
    env_path = r'C:\Users\Administrator\Desktop\automatic\ccass-debug\.env'
    lines = []
    with open(env_path) as f:
        for line in f:
            if line.startswith('LONGBRIDGE_ACCESS_TOKEN=***                continue
            lines.append(line.rstrip())
    lines.append(f'LONGBRIDGE_ACCESS_TOKEN=***    with open(env_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'.env updated ({len(token)} chars)')
    
    # Also write base64 for Linux side
    import base64
    b64 = base64.b64encode(token.encode()).decode()
    b64_path = r'C:\Users\Administrator\Desktop\automatic\ccass-debug\_lb_new_b64.txt'
    with open(b64_path, 'w') as f:
        f.write(b64)
    print(f'B64 saved to _lb_new_b64.txt ({len(b64)} chars)')
else:
    err = result.get('error', {})
    print(f'TEST FAIL: {err.get("message", raw[:200])}')
