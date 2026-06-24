#!/usr/bin/env python3
"""Rotate / clean project logs so the workspace does not balloon.

Policy:
- Compress `*.log` / `*.log.*` files older than `compress_after_days`
- Delete `.gz` archives older than `delete_after_days`
- Skip `.venv`, `.git`, and other external dependency trees

Defaults are intentionally conservative:
- compress after 7 days
- delete compressed archives after 30 days
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "ccass" / "config.yaml"
SKIP_DIRS = {".git", ".venv", ".tox", ".mypy_cache", "__pycache__"}


@dataclass
class CleanupStats:
    scanned: int = 0
    compressed: int = 0
    deleted: int = 0
    bytes_freed: int = 0


def _load_config_days(path: Path) -> int:
    if yaml is None or not path.exists():
        return 30
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logging_cfg = data.get("logging", {}) or {}
        days = int(logging_cfg.get("retention_days", 30))
        return max(days, 1)
    except Exception:
        return 30


def _is_log_path(path: Path) -> bool:
    name = path.name
    return name.endswith(".log") or ".log." in name


def _should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def _age_days(path: Path) -> float:
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 86400


def _compress(path: Path) -> Path:
    gz_path = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    size = path.stat().st_size
    path.unlink()
    return gz_path, size


def _delete(path: Path) -> int:
    size = path.stat().st_size
    path.unlink()
    return size


def clean_logs(
    root: Path,
    compress_after_days: int,
    delete_after_days: int,
    dry_run: bool = False,
) -> CleanupStats:
    stats = CleanupStats()
    now = datetime.now()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path):
            continue
        if not _is_log_path(path) and not path.name.endswith(".gz"):
            continue

        stats.scanned += 1
        age = (now - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 86400

        if path.name.endswith(".gz"):
            if age >= delete_after_days:
                stats.deleted += 1
                stats.bytes_freed += path.stat().st_size
                if not dry_run:
                    _delete(path)
            continue

        if age >= delete_after_days:
            stats.deleted += 1
            stats.bytes_freed += path.stat().st_size
            if not dry_run:
                _delete(path)
            continue

        if age >= compress_after_days:
            gz_path = path.with_suffix(path.suffix + ".gz")
            if gz_path.exists():
                continue
            stats.compressed += 1
            stats.bytes_freed += path.stat().st_size
            if not dry_run:
                _compress(path)

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compress / clean project log files.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Project root to scan")
    parser.add_argument("--compress-after-days", type=int, default=7, help="Compress logs older than this many days")
    parser.add_argument("--delete-after-days", type=int, default=None, help="Delete .gz logs older than this many days")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying files")
    args = parser.parse_args(argv)

    config_days = _load_config_days(DEFAULT_CONFIG)
    delete_after_days = args.delete_after_days or config_days

    stats = clean_logs(
        args.root,
        compress_after_days=max(args.compress_after_days, 1),
        delete_after_days=max(delete_after_days, 1),
        dry_run=args.dry_run,
    )

    mode = "DRY RUN" if args.dry_run else "DONE"
    print(
        f"[{mode}] scanned={stats.scanned} compressed={stats.compressed} "
        f"deleted={stats.deleted} freed={stats.bytes_freed / 1024:.1f} KiB "
        f"(compress_after_days={args.compress_after_days}, delete_after_days={delete_after_days})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
