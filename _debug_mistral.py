import sys, os
os.chdir(r'C:\Users\Administrator\Desktop\automatic\ccass-debug')
sys.path.insert(0, 'ccass')

# Debug loader
env_path = os.path.join(os.getcwd(), '.env')
print(f'env_path: {env_path}')
print(f'exists: {os.path.exists(env_path)}')

with open(env_path) as f:
    for line in f:
        line = line.strip()
        if 'MISTRAL' in line and not line.startswith('#'):
            parts = line.split('=', 1)
            val = parts[1]
            print(f'LINE has MISTRAL, val len={len(val)}, prefix={val[:10]}...')

# Now test the module's loader
from src.mistral_ocr import _load_key
key = _load_key()
print(f'Loaded key length: {len(key)}')
print(f'Loaded key prefix: {key[:10]}...')
