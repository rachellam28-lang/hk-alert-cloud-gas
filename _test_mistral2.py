import os, sys
os.chdir(r'C:\Users\Administrator\Desktop\automatic\ccass-debug')
sys.path.insert(0, 'ccass')

# Direct test: bypass _load_key, manually read .env and test Mistral
needle = "MISTRAL_API_KEY"
key = None
with open(".env") as f:
    for line in f:
        if needle in line and not line.startswith("#"):
            key = line.strip().split("=", 1)[1]
            break

print(f"Manual key load: len={len(key)}, prefix={key[:10]}...")

from mistralai.client import Mistral
client = Mistral(api_key=key)
models = client.models.list()
ocr = [m for m in models.data if 'ocr' in m.id.lower()]
print(f"✅ Mistral connected! {len(models.data)} models, {len(ocr)} OCR")
for m in ocr:
    print(f"  - {m.id}")

# Now test the OCR module's loader
from src.mistral_ocr import _load_key as mod_load_key
k2 = mod_load_key()
print(f"\nModule loader: len={len(k2)}")

# The bug is clear - let me look at what the module actually does
import inspect
print(inspect.getsource(mod_load_key))
