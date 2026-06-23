import os, sys
os.chdir(r'C:\Users\Administrator\Desktop\automatic\ccass-debug')

needle = "MISTRAL_API_KEY"
key = None
with open('.env') as f:
    for l in f:
        if needle in l and not l.startswith('#'):
            key = l.strip().split('=', 1)[1]
            break
if not key:
    print("NO KEY FOUND")
    sys.exit(1)

os.environ[needle] = key

from mistralai.client import Mistral
client = Mistral(api_key=key)

# Find OCR models
models = client.models.list()
ocr_models = [m for m in models.data if 'ocr' in m.id.lower()]
print('OCR models:')
for m in ocr_models:
    print(f'  {m.id}')
print(f'Total: {len(ocr_models)} OCR models')
