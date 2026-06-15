import json, os

snapshots = [
    'C:/Users/Administrator/Desktop/automatic/ccass-debug/raw/prices_20260609.json',
    'C:/Users/Administrator/Desktop/automatic/ccass-debug/raw/prices_20260610.json',
    'C:/Users/Administrator/Desktop/automatic/ccass-debug/raw/prices_20260611.json',
]

targets = ['01323', '00174', '01912', '01277', '02186', '01333', '01803']

for path in snapshots:
    if not os.path.exists(path):
        print(f'MISSING: {path}')
        continue
    with open(path) as f:
        snap = json.load(f)
    dates = sorted(snap.keys())
    fname = os.path.basename(path)
    print(f'\n--- {fname}: {len(dates)} dates ---')
    for d in dates:
        vals = snap[d]
        if not isinstance(vals, dict):
            continue  # skip non-dict values
        found = False
        for code in targets:
            if code in vals:
                v = vals[code]
                if isinstance(v, dict):
                    print(f'  {d} {code}: close={v.get("close")} vol={v.get("vol")} hi52={v.get("hi52","?")}')
                else:
                    print(f'  {d} {code}: close={v} (legacy float)')
                found = True
        if found:
            pass  # already printed
