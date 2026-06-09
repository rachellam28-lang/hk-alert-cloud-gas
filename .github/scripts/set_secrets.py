"""Set Longbridge tokens as GitHub repo secrets."""
import subprocess, json, os, sys, base64
import urllib.request, urllib.error
from nacl import encoding, public

REPO = 'rachellam28-lang/hk-alert-cloud-gas'
ENV_PATH = r'C:\Users\Administrator\Desktop\automatic\ccass-debug\.env'

def get_gh_token():
    """Get GitHub PAT from git credential helper."""
    proc = subprocess.run(
        ['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n',
        capture_output=True, text=True,
        cwd=r'C:\Users\Administrator\Desktop\automatic\ccass-debug'
    )
    for line in proc.stdout.split('\n'):
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise RuntimeError('Could not get GitHub token from credential helper')

def load_env(path):
    """Load .env file into dict."""
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

def encrypt_secret(public_key: str, secret_value: str) -> str:
    pkey = public.PublicKey(public_key.encode('utf-8'), encoding.Base64Encoder())
    sealed_box = public.SealedBox(pkey)
    encrypted = sealed_box.encrypt(secret_value.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')

def set_secret(gh_token, name, value, key_id, pubkey):
    encrypted = encrypt_secret(pubkey, value)
    payload = json.dumps({
        'encrypted_value': encrypted,
        'key_id': key_id
    }).encode()
    
    req = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/actions/secrets/{name}',
        data=payload,
        method='PUT',
        headers={
            'Authorization': f'Bearer {gh_token}',
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
            'User-Agent': 'hermes-agent'
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return f'OK {resp.status}'
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return f'FAIL {e.code}: {body}'

def main():
    gh_token = get_gh_token()
    env = load_env(ENV_PATH)
    
    # Get repo public key
    req = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/actions/secrets/public-key',
        headers={
            'Authorization': f'Bearer {gh_token}',
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'hermes-agent'
        }
    )
    with urllib.request.urlopen(req) as resp:
        pubkey_data = json.loads(resp.read())
    
    key_id = pubkey_data['key_id']
    pubkey = pubkey_data['key']
    print(f'Public key: key_id={key_id}')
    
    # Set each Longbridge secret
    secrets = [
        ('LONGBRIDGE_ACCESS_TOKEN', 'LONGBRIDGE_ACCESS_TOKEN'),
        ('LONGBRIDGE_REFRESH_TOKEN', 'LONGBRIDGE_REFRESH_TOKEN'),
        ('LONGBRIDGE_ACCOUNT', 'LONGBRIDGE_ACCOUNT'),
    ]
    
    for secret_name, env_key in secrets:
        value = env.get(env_key, '')
        if not value:
            print(f'SKIP {secret_name}: not in .env')
            continue
        result = set_secret(gh_token, secret_name, value, key_id, pubkey)
        print(f'{secret_name}: {result}')

if __name__ == '__main__':
    main()
