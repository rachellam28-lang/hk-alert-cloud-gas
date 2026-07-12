#!/usr/bin/env python3
"""Apply the canonical navigation shell to generated root HTML pages."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PAGES = (
    "daily_trade_prompt.html",
    "distribution_day.html",
    "fundflow.html",
    "jieqi_analysis.html",
    "rights_analysis.html",
    "timing_analysis.html",
    "vqc_analysis.html",
)
NAV = '<nav class="site-nav" id="sharedSiteNav" data-base="./"></nav>'
SCRIPT = '<script src="./shared-nav.js"></script>'
NAV_RE = re.compile(r'<nav\s+class="site-nav"[^>]*>.*?</nav>', re.I | re.S)


def apply(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    before = text
    if NAV_RE.search(text):
        text = NAV_RE.sub(NAV, text, count=1)
    elif '<body>' in text:
        text = text.replace('<body>', f'<body>\n{NAV}', 1)
    elif '<body ' in text:
        text = re.sub(r'(<body\b[^>]*>)', rf'\1\n{NAV}', text, count=1, flags=re.I)
    else:
        raise RuntimeError(f"{path.name}: missing body")

    if SCRIPT not in text:
        if '</body>' not in text:
            raise RuntimeError(f"{path.name}: missing closing body")
        text = text.replace('</body>', f'{SCRIPT}\n</body>', 1)

    if text != before:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    changed = []
    for rel in PAGES:
        path = ROOT / rel
        if not path.exists():
            raise RuntimeError(f"missing generated page: {rel}")
        if apply(path):
            changed.append(rel)
    print(f"shared shell: {len(changed)} updated / {len(PAGES)} checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
