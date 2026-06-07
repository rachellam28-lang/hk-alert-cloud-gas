import requests, json, os

resp = requests.post(
    'https://mcp.longbridge.com/agent',
    headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'},
    json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'authenticate','arguments':{'auth_code':'9zN6kNAuyqKD1Y2zJj16QnrAB719Fao5P9jXoMrbXiy6'}}}
)

text = resp.text
for line in text.split('\n'):
    if line.startswith('data: '):
        data = json.loads(line[6:])
        result = json.loads(data['result']['content'][0]['text'])
        access_token = result['access_token']
        refresh_token = result['refresh_token']
        
        # Save token file
        sdk_dir = os.path.expanduser('~/.longbridge/openapi/tokens/mcp-auth')
        os.makedirs(sdk_dir, exist_ok=True)
        token_data = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_type': 'Bearer',
            'expires_in': result.get('expires_in', 1209600),
            'scope': ' '.join(result.get('scopes', []))
        }
        with open(f'{sdk_dir}/token.json', 'w') as f:
            json.dump(token_data, f)
        
        # Append to .env
        env_path = 'C:/Users/Administrator/Desktop/automatic/ccass-debug/.env'
        with open(env_path, 'a') as f:
            f.write(f'\n# Longbridge OAuth (MCP auth)\n')
            f.write(f'LONGBRIDGE_ACCESS_TOKEN={access_token}\n')
        
        print(f'Token length: {len(access_token)}')
        print(f'Scope: {result["scopes"]}')
        print(f'Account: {result["account_channel"]}')
        print('Token saved to SDK path and .env')
        break
