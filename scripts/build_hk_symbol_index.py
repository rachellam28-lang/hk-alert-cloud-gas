#!/usr/bin/env python3
"""Build the searchable HK symbol index from the canonical CCASS universe."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "ccass" / "holdings.db"
OUTPUT = ROOT / "data" / "hk_symbols.json"
CODE_RE = re.compile(r"^\d{5}$")


def build() -> dict:
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        raise RuntimeError(f"missing canonical database: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT stock_code, stock_name
            FROM stock_universe
            WHERE is_active = 1
            ORDER BY stock_code
            """
        ).fetchall()
        as_of_row = conn.execute(
            "SELECT MAX(last_seen_at) FROM stock_universe WHERE is_active = 1"
        ).fetchone()

    symbols = []
    for raw_code, raw_name in rows:
        code = str(raw_code or "").strip().zfill(5)
        if not CODE_RE.fullmatch(code):
            continue
        name = str(raw_name or "").strip() or code
        symbols.append({"code": code, "name": name})

    if len(symbols) < 2500:
        raise RuntimeError(f"active HK symbol universe unexpectedly small: {len(symbols)}")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": str(as_of_row[0] or "")[:10] or None,
        "source": "ccass/holdings.db stock_universe",
        "data_kind": "observed_listing_index",
        "is_observed": True,
        "count": len(symbols),
        "symbols": symbols,
    }


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp.replace(OUTPUT)
    print(f"HK symbol index: {payload['count']} -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
