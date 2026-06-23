import sys, os
os.chdir(r'C:\Users\Administrator\Desktop\automatic\ccass-debug')
sys.path.insert(0, 'ccass')

# Force-reproduce the loader logic
import src.mistral_ocr as mo

# Patch in debug prints
import inspect
print(f'mistral_ocr __file__: {mo.__file__}')
d = os.path.dirname(mo.__file__)
print(f'dirname: {d}')

# Walk each path in the loader
from pathlib import Path
p1 = os.path.normpath(os.path.join(os.path.dirname(mo.__file__), "..", "..", ".env"))
p2 = os.path.normpath(os.path.join(os.getcwd(), ".env"))
p3 = os.path.expanduser("~/Desktop/automatic/ccass-debug/.env")

for p in [p1, p2, p3]:
    print(f'Path: {p}  exists={os.path.exists(p)}')
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if 'MISTRAL' in line and not line.startswith('#'):
                    val = line.split('=', 1)[1]
                    print(f'  Found key: len={len(val)}, prefix={val[:10]}...')
                    break
