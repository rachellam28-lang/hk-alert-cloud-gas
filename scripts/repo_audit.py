#!/usr/bin/env python3
"""Repo-native audit helper for page sources, data dates, and DB coverage.

Usage:
  python scripts/repo_audit.py pages
  python scripts/repo_audit.py dates
  python scripts/repo_audit.py db
  python scripts/repo_audit.py export
  python scripts/repo_audit.py pages --json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

BASE = Path(__file__).resolve().parent.parent
CCASS_DIR = BASE / "ccass"
DB_PATH = CCASS_DIR / "holdings.db"
PUBLISH_SCOPE_PATTERNS = ("029%", "04%", "8%")
DATE_KEYS = (
    "updatedAt",
    "updated_at",
    "generated_at",
    "updated",
    "built_at",
    "date",
    "latest_publishable_date",
    "latest_db_date",
    "announcement_date",
    "ann_date",
    "release_date",
    "scan_date",
)
DEFAULT_DATE_FILES = (
    "holdings.json",
    "data/holdings.json",
    "ccass.json",
    "data/ccass.json",
    "market.json",
    "data/market.json",
    "data/signals.json",
    "data/alerts.json",
    "data/announcements.json",
    "data/rights_analysis.json",
    "data/fundflow.json",
    "data/transfers.json",
    "data/participant_anomalies.json",
    "data/history.json",
    "data/publish_bundle.json",
    "data/kbar_cache.json",
    "data/trade_engine.json",
    "data/timesfm.json",
    "data/sector_rotation.json",
    "data/options_levels.json",
    "data/trend_matrix.json",
)
EXPORT_PATH = BASE / "data" / "repo_audit.json"

sys.path.insert(0, str(CCASS_DIR))
from src.trading_calendar import is_trading_day  # noqa: E402


@dataclass
class DateStamp:
    path: str
    key: str | None
    raw: str | None
    normalized_date: str | None
    age_days: int | None
    lag_vs_freshest_days: int | None = None


def normalize_ref(ref: str) -> str:
    ref = ref.strip().strip("\"'`")
    ref = ref.split("?", 1)[0].split("#", 1)[0]
    if ref.startswith("./"):
        ref = ref[2:]
    return ref


def page_files() -> list[Path]:
    files = sorted(BASE.glob("*.html"))
    docs_page = BASE / "docs" / "ccass-warroom.html"
    if docs_page.exists():
        files.append(docs_page)
    return files


def parse_dateish(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None
    text = str(value).strip()
    if not text:
        return None
    candidate = text[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if iso_match:
        return iso_match.group(1)
    return None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_item_date(items: list[Any]) -> tuple[str | None, str | None]:
    best_key = None
    best_date = None
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in DATE_KEYS:
            if key not in item:
                continue
            normalized = parse_dateish(item.get(key))
            if normalized and (best_date is None or normalized > best_date):
                best_date = normalized
                best_key = key
    return best_key, best_date


def inspect_json_date(rel_path: str) -> DateStamp:
    path = BASE / rel_path
    raw = None
    key = None
    normalized = None
    if not path.exists():
        return DateStamp(rel_path, None, None, None, None)
    try:
        payload = load_json(path)
    except Exception:
        return DateStamp(rel_path, "invalid_json", None, None, None)
    if isinstance(payload, dict):
        for candidate in DATE_KEYS:
            if payload.get(candidate):
                key = candidate
                raw = str(payload.get(candidate))
                normalized = parse_dateish(raw)
                if normalized:
                    break
        if rel_path == "data/publish_bundle.json":
            publish_date = (((payload.get("publish") or {}).get("latest_publishable_date")))
            if publish_date:
                key = "publish.latest_publishable_date"
                raw = str(publish_date)
                normalized = parse_dateish(raw)
    elif isinstance(payload, list):
        key, normalized = latest_item_date(payload)
        raw = normalized
    age_days = None
    if normalized:
        age_days = (date.today() - date.fromisoformat(normalized)).days
    return DateStamp(rel_path, key, raw, normalized, age_days)


def build_pages_report(selected: list[str] | None = None) -> dict[str, Any]:
    literal_ref_pattern = re.compile(
        r"(?:\./)?(?:data/[A-Za-z0-9_.\-/]+\.json|holdings\.json|market\.json|ccass\.json)"
    )
    source_label_pattern = re.compile(r"數據來源[:：]\s*([^<\n]+)")
    reports = []
    wanted = {name.lower() for name in selected or []}
    for page in page_files():
        if wanted and page.name.lower() not in wanted:
            continue
        text = page.read_text(encoding="utf-8")
        refs = sorted({normalize_ref(match.group(0)) for match in literal_ref_pattern.finditer(text)})
        missing = [ref for ref in refs if not (BASE / ref).exists()]
        label_match = source_label_pattern.search(text)
        reports.append(
            {
                "page": page.relative_to(BASE).as_posix(),
                "data_refs": refs,
                "missing_refs": missing,
                "uses_publish_bundle": "data/publish_bundle.json" in refs,
                "source_label": label_match.group(1).strip() if label_match else None,
            }
        )
    return {"pages": reports}


def build_dates_report(files: list[str] | None = None) -> dict[str, Any]:
    targets = files or list(DEFAULT_DATE_FILES)
    stamps = [inspect_json_date(rel_path) for rel_path in targets]
    normalized_dates = [stamp.normalized_date for stamp in stamps if stamp.normalized_date]
    freshest = max(normalized_dates) if normalized_dates else None
    oldest = min(normalized_dates) if normalized_dates else None
    for stamp in stamps:
        if freshest and stamp.normalized_date:
            stamp.lag_vs_freshest_days = (
                date.fromisoformat(freshest) - date.fromisoformat(stamp.normalized_date)
            ).days
    alias_pairs = []
    for left, right in (
        ("holdings.json", "data/holdings.json"),
        ("ccass.json", "data/ccass.json"),
        ("market.json", "data/market.json"),
    ):
        left_stamp = next((s for s in stamps if s.path == left), None)
        right_stamp = next((s for s in stamps if s.path == right), None)
        alias_pairs.append(
            {
                "left": left,
                "right": right,
                "match": bool(left_stamp and right_stamp and left_stamp.normalized_date == right_stamp.normalized_date),
                "left_date": left_stamp.normalized_date if left_stamp else None,
                "right_date": right_stamp.normalized_date if right_stamp else None,
            }
        )
    return {
        "freshest_date": freshest,
        "oldest_date": oldest,
        "spread_days": (
            (date.fromisoformat(freshest) - date.fromisoformat(oldest)).days
            if freshest and oldest
            else None
        ),
        "files": [stamp.__dict__ for stamp in stamps],
        "alias_pairs": alias_pairs,
    }


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _publish_scope_sql(alias: str | None = None) -> str:
    col = f"{alias}.stock_code" if alias else "stock_code"
    return " AND ".join(f"{col} NOT LIKE '{pattern}'" for pattern in PUBLISH_SCOPE_PATTERNS)


def business_days_missing(start_iso: str, end_iso: str, present: set[str]) -> list[str]:
    missing: list[str] = []
    cur = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    while cur <= end:
        iso = cur.isoformat()
        if is_trading_day(cur) and iso not in present:
            missing.append(iso)
        cur += timedelta(days=1)
    return missing


def _local_expected_count(counts: list[int], index: int) -> int:
    """Median of the nearest complete dates, excluding obvious partial runs."""
    if not counts:
        return 0
    complete_floor = max(counts) * 0.8
    complete_indexes = [i for i, count in enumerate(counts) if count >= complete_floor]
    before = [i for i in complete_indexes if i <= index][-3:]
    after = [i for i in complete_indexes if i > index][:3]
    reference_counts = [counts[i] for i in before + after]
    return int(round(median(reference_counts))) if reference_counts else 0


def build_db_report(threshold: float, limit: int) -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"db_path": str(DB_PATH), "error": "missing"}
    with db_connect() as conn:
        total_row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM stock_universe
            WHERE is_active = 1
              AND {_publish_scope_sql()}
            """
        ).fetchone()
        expected = int(total_row[0] or 0)
        rows = conn.execute(
            f"""
            SELECT trade_date,
                   COUNT(DISTINCT CASE
                       WHEN total_shares > 0 THEN stock_code
                   END) AS stock_count,
                   COUNT(DISTINCT CASE
                       WHEN total_shares > 0 AND total_pct IS NOT NULL THEN stock_code
                   END) AS pct_count
            FROM ccass_daily
            WHERE validation_failed = 0
              AND {_publish_scope_sql()}
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).fetchall()
        if not rows:
            return {"db_path": str(DB_PATH), "expected_publish_scope_count": expected, "error": "no_rows"}
        aggregate_counts = [int(row["stock_count"] or 0) for row in rows]
        date_rows = []
        for index, row in enumerate(rows):
            trade_date = str(row["trade_date"])
            stock_count = int(row["stock_count"] or 0)
            pct_count = int(row["pct_count"] or 0)
            local_expected = _local_expected_count(aggregate_counts, index)
            coverage_pct = round(min(stock_count / local_expected, 1.0) * 100, 1) if local_expected else None
            pct_availability_pct = round((pct_count / stock_count) * 100, 1) if stock_count else None
            holdings_row = conn.execute(
                """
                SELECT COUNT(*) AS holdings_rows,
                       COUNT(DISTINCT stock_code) AS participant_stock_count
                FROM ccass_holdings
                WHERE trade_date = ?
                  AND stock_code NOT LIKE '029%'
                  AND stock_code NOT LIKE '04%'
                  AND stock_code NOT LIKE '8%'
                """,
                (trade_date,),
            ).fetchone()
            participant_stock_count = int(holdings_row[1] or 0)
            date_rows.append(
                {
                    "trade_date": trade_date,
                    "stock_count": stock_count,
                    "expected_local_count": local_expected,
                    "coverage_pct": coverage_pct,
                    "pct_available_count": pct_count,
                    "pct_availability_pct": pct_availability_pct,
                    "participant_stock_count": participant_stock_count,
                    "participant_coverage_pct": round((participant_stock_count / stock_count) * 100, 1) if stock_count else None,
                    "holdings_rows": int(holdings_row[0] or 0),
                }
            )
        latest = date_rows[-1]
        publishable = None
        for row in reversed(date_rows):
            if row["coverage_pct"] is not None and row["coverage_pct"] >= threshold:
                publishable = row
                break
        present_dates = {row["trade_date"] for row in date_rows}
        missing_days = business_days_missing(date_rows[0]["trade_date"], date_rows[-1]["trade_date"], present_dates)
        low_coverage = [row for row in reversed(date_rows) if (row["coverage_pct"] or 0) < threshold]
        low_participant_coverage = [
            row for row in reversed(date_rows)
            if (row["participant_coverage_pct"] or 0) < threshold
        ]
        return {
            "db_path": str(DB_PATH),
            "expected_publish_scope_count": expected,
            "coverage_basis": "valid total_shares rows against robust nearby-date baseline",
            "pct_availability_is_coverage": False,
            "first_date": date_rows[0]["trade_date"],
            "latest_date": latest,
            "latest_publishable_date": publishable,
            "missing_trading_days": missing_days[:limit],
            "missing_trading_day_count": len(missing_days),
            "low_coverage_dates": low_coverage[:limit],
            "low_coverage_count": len(low_coverage),
            "low_participant_coverage_dates": low_participant_coverage[:limit],
            "low_participant_coverage_count": len(low_participant_coverage),
        }


def build_export_report(threshold: float = 98.0, limit: int = 100) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pages": build_pages_report()["pages"],
        "dates": build_dates_report(),
        "db": build_db_report(threshold=threshold, limit=limit),
    }


def print_pages(report: dict[str, Any]) -> None:
    for page in report["pages"]:
        print(page["page"])
        print(f"  refs: {', '.join(page['data_refs']) or '-'}")
        print(f"  missing: {', '.join(page['missing_refs']) or '-'}")
        print(f"  publish_bundle: {'yes' if page['uses_publish_bundle'] else 'no'}")
        print(f"  label: {page['source_label'] or '-'}")


def print_dates(report: dict[str, Any]) -> None:
    print(f"freshest: {report['freshest_date'] or '-'}")
    print(f"oldest:   {report['oldest_date'] or '-'}")
    print(f"spread:   {report['spread_days'] if report['spread_days'] is not None else '-'} days")
    print()
    for item in report["files"]:
        print(
            f"{item['path']}: {item['normalized_date'] or '-'}"
            f" | key={item['key'] or '-'}"
            f" | age={item['age_days'] if item['age_days'] is not None else '-'}"
            f" | lag={item['lag_vs_freshest_days'] if item['lag_vs_freshest_days'] is not None else '-'}"
        )
    print()
    for pair in report["alias_pairs"]:
        status = "ok" if pair["match"] else "mismatch"
        print(f"alias {pair['left']} <-> {pair['right']}: {status}")


def print_db(report: dict[str, Any]) -> None:
    if report.get("error"):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"db: {report['db_path']}")
    print(f"expected publish-scope stocks: {report['expected_publish_scope_count']}")
    print(f"first date: {report['first_date']}")
    latest = report["latest_date"]
    print(
        f"latest: {latest['trade_date']} | stocks={latest['stock_count']} | "
        f"coverage={latest['coverage_pct']}% | pct_available={latest['pct_availability_pct']}% | "
        f"participant_coverage={latest['participant_coverage_pct']}% | holdings_rows={latest['holdings_rows']}"
    )
    publishable = report.get("latest_publishable_date")
    if publishable:
        print(
            f"publishable: {publishable['trade_date']} | stocks={publishable['stock_count']} | "
            f"coverage={publishable['coverage_pct']}%"
        )
    else:
        print("publishable: -")
    print(f"missing trading days: {report['missing_trading_day_count']}")
    for item in report["missing_trading_days"]:
        print(f"  gap: {item}")
    print(f"low coverage dates: {report['low_coverage_count']}")
    for item in report["low_coverage_dates"]:
        print(
            f"  low: {item['trade_date']} | stocks={item['stock_count']} | "
            f"expected={item['expected_local_count']} | coverage={item['coverage_pct']}% | "
            f"pct_available={item['pct_availability_pct']}% | holdings_rows={item['holdings_rows']}"
        )
    print(f"low participant coverage dates: {report['low_participant_coverage_count']}")
    for item in report["low_participant_coverage_dates"]:
        print(
            f"  participant-low: {item['trade_date']} | stocks={item['participant_stock_count']}/"
            f"{item['stock_count']} | coverage={item['participant_coverage_pct']}%"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit page sources, file dates, and DB coverage.")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pages_parser = subparsers.add_parser("pages", help="Audit page -> data file references")
    pages_parser.add_argument("--pages", nargs="*", help="Optional page filenames to limit scan")

    dates_parser = subparsers.add_parser("dates", help="Audit canonical JSON dates")
    dates_parser.add_argument("--files", nargs="*", help="Optional JSON paths to limit scan")

    db_parser = subparsers.add_parser("db", help="Audit CCASS DB gaps and low coverage dates")
    db_parser.add_argument("--threshold", type=float, default=98.0, help="Trusted Market%% publish coverage threshold")
    db_parser.add_argument("--limit", type=int, default=20, help="Max listed rows per warning bucket")

    export_parser = subparsers.add_parser("export", help="Write combined audit snapshot to data/repo_audit.json")
    export_parser.add_argument("--threshold", type=float, default=98.0, help="Trusted Market%% publish coverage threshold")
    export_parser.add_argument("--limit", type=int, default=100, help="Max listed rows per warning bucket")

    args = parser.parse_args()

    if args.command == "pages":
        report = build_pages_report(args.pages)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_pages(report)
        return 0
    if args.command == "dates":
        report = build_dates_report(args.files)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_dates(report)
        return 0
    if args.command == "db":
        report = build_db_report(args.threshold, args.limit)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_db(report)
        return 0
    if args.command == "export":
        report = build_export_report(threshold=args.threshold, limit=args.limit)
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Wrote {EXPORT_PATH.relative_to(BASE).as_posix()}")
        return 0
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
