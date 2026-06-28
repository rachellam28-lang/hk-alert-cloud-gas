#!/usr/bin/env python3
"""Keep dashboard publish aliases aligned with canonical JSON files.

Several pages read root JSON files while others read data/*.json aliases.
This script makes those aliases explicit and verifies their publish metadata
after every refresh.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

ALIASES = [
    ("holdings.json", "data/holdings.json", ("updated", "stock_count", "coverage_pct")),
    ("ccass.json", "data/ccass.json", ("updated", "stock_count", "coverage_pct")),
    ("market.json", "data/market.json", ("updated_at",)),
]


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON file: {path}: {exc}") from exc


def stocks_len(payload: Any) -> int | None:
    if isinstance(payload, dict) and isinstance(payload.get("stocks"), list):
        return len(payload["stocks"])
    return None


def meta(payload: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    out = {key: payload.get(key) for key in keys}
    slen = stocks_len(payload)
    if slen is not None:
        out["stocks_len"] = slen
    return out


def atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp")
    tmp.write_bytes(src.read_bytes())
    os.replace(tmp, dst)


def sync_one(src_rel: str, dst_rel: str, keys: tuple[str, ...]) -> dict[str, Any]:
    src = ROOT / src_rel
    dst = ROOT / dst_rel
    src_data = load_json(src)
    before = load_json(dst) if dst.exists() else None
    copied = not dst.exists() or src.read_bytes() != dst.read_bytes()
    if copied:
        atomic_copy(src, dst)
    after = load_json(dst)
    src_meta = meta(src_data, keys)
    dst_meta = meta(after, keys)
    if src_meta != dst_meta:
        raise RuntimeError(f"{dst_rel} metadata mismatch after sync: {dst_meta} != {src_meta}")
    return {
        "source": src_rel,
        "alias": dst_rel,
        "copied": copied,
        "before": meta(before, keys) if before is not None else None,
        "after": dst_meta,
    }


def main() -> int:
    results = [sync_one(src, dst, keys) for src, dst, keys in ALIASES]
    print(json.dumps({"status": "PASS", "aliases": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
