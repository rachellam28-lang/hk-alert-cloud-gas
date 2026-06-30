#!/usr/bin/env python3
"""Sync placement/rights announcements into placements_enriched.json.

rights_analysis.html is generated from placements_enriched.json, while the
dashboard corporate-action badges come from announcements.json. This bridge
keeps both paths on the same daily announcement feed.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parents[1]
ANNOUNCEMENTS = BASE / "data" / "announcements.json"
PLACEMENTS = BASE / "data" / "placements_enriched.json"

RIGHTS = "供股"
PLACEMENT = "配股"
ISSUE = "配售"
TOPUP = "先舊後新"
OTHER = "其他"
ORDINARY_SHARES = "普通股份"
CONVERTIBLE = "可換股債券"

RELEVANT_TYPES = {"rights", "placement"}
RELEVANT_LABELS = {RIGHTS, PLACEMENT}
TITLE_KEYWORDS = (
    "RIGHTS ISSUE",
    "OPEN OFFER",
    "PLACING",
    "PLACEMENT",
    "TOP-UP",
    "SUBSCRIPTION OF NEW SHARES",
    "SUBSCRIPTION OF",
    "SUBSCRIPTION AGREEMENT",
    "配股",
    "供股",
    "配售新股",
    "認購新股",
    "發行新股",
)
NEGATIVE_TITLE_KEYWORDS = (
    "RESTRICTED SHARE",
    "SHARE AWARD",
    "SHARE OPTION",
    "POLL RESULTS",
    "ANNUAL GENERAL MEETING",
    "MONTHLY RETURN",
    "NEXT DAY DISCLOSURE RETURN",
)
CONVERTIBLE_KEYWORDS = ("CONVERTIBLE", "可換股", "可轉換")
TERMINAL_KEYWORDS = (
    "TERMINATION",
    "TERMINATED",
    "CANCELLATION",
    "CANCELLED",
    "LAPSE",
    "LAPSED",
    "WITHDRAW",
    "終止",
    "取消",
    "失效",
)
CARRY_FORWARD_FIELDS = (
    "shares",
    "price",
    "amount",
    "type",
    "pct_shares",
    "amount_num",
    "price_num",
    "pct_num",
    "market_price",
    "discount_pct",
    "latest_price",
    "latest_date",
    "current_return_pct",
    "post_ex_date_return_pct",
    "manual_finished_date",
    "placing_agent",
    "ratio",
)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def code5(value: Any) -> str:
    return str(value or "").strip().lstrip("0").zfill(5)


def parse_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text[:10]):
        return text[:10]
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def display_date(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m/%Y")


def norm_url(value: Any) -> str:
    return str(value or "").strip().lower()


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def ann_url(ann: dict[str, Any]) -> str:
    return str(ann.get("url") or ann.get("link") or ann.get("pdf_url") or "").strip()


def ann_is_relevant(ann: dict[str, Any]) -> bool:
    ann_type = str(ann.get("type") or "").strip().lower()
    labels = {str(v).strip() for v in (ann.get("types") or [])}

    title = str(ann.get("title") or "").upper()
    if any(keyword in title for keyword in NEGATIVE_TITLE_KEYWORDS):
        return False
    title_match = any(keyword.upper() in title for keyword in TITLE_KEYWORDS)
    if ann_type in RELEVANT_TYPES or labels.intersection(RELEVANT_LABELS):
        return title_match
    if ann_type:
        return False
    return title_match


def ann_category(ann: dict[str, Any]) -> str:
    title = str(ann.get("title") or "")
    title_upper = title.upper()
    if ann_is_terminal(ann):
        return OTHER
    labels = {str(v).strip() for v in (ann.get("types") or [])}
    ann_type = str(ann.get("type") or "").strip().lower()
    if RIGHTS in labels or ann_type == "rights" or "RIGHTS ISSUE" in title_upper or "供股" in title:
        return RIGHTS
    if "TOP-UP" in title_upper or "先舊後新" in title:
        return TOPUP
    return ISSUE


def ann_is_terminal(ann: dict[str, Any]) -> bool:
    title = str(ann.get("title") or "")
    title_upper = title.upper()
    return any(keyword in title_upper or keyword in title for keyword in TERMINAL_KEYWORDS)


def ann_share_type(title: str) -> str:
    upper = title.upper()
    if any(keyword in upper or keyword in title for keyword in CONVERTIBLE_KEYWORDS):
        return CONVERTIBLE
    return ORDINARY_SHARES


def build_existing_indexes(rows: list[dict[str, Any]]) -> tuple[set[str], set[tuple[str, str, str]]]:
    urls: set[str] = set()
    keys: set[tuple[str, str, str]] = set()
    for row in rows:
        url = norm_url(row.get("pdf_url") or row.get("url") or row.get("link"))
        if url:
            urls.add(url)
        date = parse_date(row.get("date_parsed") or row.get("date"))
        code = code5(row.get("code"))
        title = row.get("title") or row.get("method") or row.get("purpose") or ""
        if code != "00000" and date:
            keys.add((code, date, norm_text(title)))
    return urls, keys


def build_baselines(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        date = parse_date(row.get("date_parsed") or row.get("date"))
        if not date:
            continue
        row["_sync_date"] = date
        by_code.setdefault(code5(row.get("code")), []).append(row)
    for items in by_code.values():
        items.sort(key=lambda row: row.get("_sync_date", ""))
    return by_code


def has_terms(row: dict[str, Any]) -> bool:
    for field in ("price_num", "amount_num", "pct_num", "discount_pct"):
        try:
            value = row.get(field)
            if value is not None and float(value) != 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def find_baseline(
    baselines: dict[str, list[dict[str, Any]]],
    code: str,
    ann_date: str,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in baselines.get(code, [])
        if row.get("_sync_date", "") <= ann_date and has_terms(row)
    ]
    return candidates[-1] if candidates else None


def row_from_announcement(
    ann: dict[str, Any],
    baselines: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    ann_date = parse_date(ann.get("date") or ann.get("release_time"))
    code = code5(ann.get("code"))
    if not ann_date or code == "00000":
        return None

    title = str(ann.get("title") or "").strip()
    category = ann_category(ann)
    baseline = find_baseline(baselines, code, ann_date)
    row: dict[str, Any] = {
        "date": display_date(ann_date),
        "code": code,
        "name": ann.get("name") or (baseline or {}).get("name") or "",
        "shares": "--",
        "price": "--",
        "amount": "--",
        "type": ann_share_type(title),
        "pct_shares": "--",
        "method": f"{category} ({title})" if title else category,
        "amount_num": 0,
        "price_num": 0,
        "pct_num": 0,
        "category": category,
        "purpose": title[:160],
        "ratio": "",
        "date_parsed": ann_date,
        "market_price": 0,
        "discount_pct": None,
        "latest_price": None,
        "latest_date": None,
        "current_return_pct": None,
        "placing_agent": None,
        "source": "announcement",
        "pdf_url": ann_url(ann),
        "title": title,
        "announcement_types": ann.get("types") or [],
        "announcement_type": ann.get("type"),
    }

    if baseline and not ann_is_terminal(ann):
        for field in CARRY_FORWARD_FIELDS:
            if field in baseline:
                row[field] = baseline[field]
        row["terms_carry_forward"] = True
        row["terms_source_date"] = baseline.get("date_parsed") or baseline.get("date")
        row["terms_source_url"] = baseline.get("pdf_url") or baseline.get("url") or ""
    else:
        row["terms_carry_forward"] = False

    return row


def cleanup_private_fields(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row.pop("_sync_date", None)


def latest_existing_date(rows: list[dict[str, Any]]) -> str:
    dates = [
        parse_date(row.get("date_parsed") or row.get("date"))
        for row in rows
        if parse_date(row.get("date_parsed") or row.get("date"))
    ]
    return max(dates) if dates else ""


def main() -> int:
    announcements = load_json(ANNOUNCEMENTS, [])
    placements = load_json(PLACEMENTS, [])
    if not isinstance(announcements, list):
        raise SystemExit(f"{ANNOUNCEMENTS} must be a list")
    if not isinstance(placements, list):
        raise SystemExit(f"{PLACEMENTS} must be a list")

    existing_urls, existing_keys = build_existing_indexes(placements)
    baselines = build_baselines(placements)
    cutoff_date = latest_existing_date(placements)
    added: list[dict[str, Any]] = []

    for ann in sorted(announcements, key=lambda a: parse_date(a.get("date"))):
        ann_date = parse_date(ann.get("date") or ann.get("release_time"))
        if cutoff_date and ann_date < cutoff_date:
            continue
        if not ann_is_relevant(ann):
            continue
        row = row_from_announcement(ann, baselines)
        if not row:
            continue
        url = norm_url(row.get("pdf_url"))
        key = (row["code"], row["date_parsed"], norm_text(row.get("title") or row.get("method")))
        if (url and url in existing_urls) or key in existing_keys:
            continue
        placements.append(row)
        added.append(row)
        if url:
            existing_urls.add(url)
        existing_keys.add(key)
        row["_sync_date"] = row["date_parsed"]
        baselines.setdefault(row["code"], []).append(row)
        baselines[row["code"]].sort(key=lambda item: item.get("_sync_date", ""))

    cleanup_private_fields(placements)
    placements.sort(key=lambda row: (parse_date(row.get("date_parsed") or row.get("date")), code5(row.get("code"))), reverse=True)
    atomic_write(PLACEMENTS, placements)

    latest = max((parse_date(row.get("date_parsed") or row.get("date")) for row in placements), default="")
    print(
        f"Synced rights/placement announcements: +{len(added)} rows, "
        f"total {len(placements)}, cutoff {cutoff_date or 'none'}, latest {latest}"
    )
    if added:
        sample = ", ".join(f"{row['code']}:{row['date_parsed']}" for row in added[-8:])
        print(f"Added sample: {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
