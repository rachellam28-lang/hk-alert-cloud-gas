#!/usr/bin/env python3
"""Fetch the SFC weekly aggregate reportable short-position CSV."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "short_positions.json"
URL = "https://www.sfc.hk/en/Regulatory-functions/Market/Short-position-reporting/Aggregated-reportable-short-positions-of-specified-shares/Latest-CSV"


def write_payload(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def code5(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-5:].zfill(5) if digits else ""


def load_previous() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_date(value: str) -> str:
    raw = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--best-effort", action="store_true")
    args = parser.parse_args()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    previous = load_previous()

    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "hk-alert-cloud-gas/1.0"})
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            raw = response.read()
            resolved_url = response.geturl()
        text = raw.decode("utf-8-sig", "replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for item in reader:
            code = code5(item.get("Stock Code"))
            if not code:
                continue
            rows.append({
                "code": code,
                "name": item.get("Stock Name") or "",
                "short_shares": number(item.get("Aggregated Reportable Short Positions (Shares)")),
                "short_value_hkd": number(item.get("Aggregated Reportable Short Positions (HK$)")),
            })
        report_date = next((normalize_date(item.get("Date")) for item in csv.DictReader(io.StringIO(text)) if item.get("Date")), None)
        if not rows or not report_date:
            raise RuntimeError("SFC CSV contains no usable rows")
    except Exception as exc:
        if previous and args.best_effort:
            previous["refresh_attempted_at"] = now
            previous["stale"] = True
            previous["refresh_error"] = str(exc)
            write_payload(previous)
            print("WARN: SFC unavailable; preserved prior weekly short-position snapshot")
            return 0
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    same_report = normalize_date(previous.get("report_date")) == report_date
    previous_rows = {
        row.get("code"): row for row in (previous.get("rows") or [])
        if isinstance(row, dict)
    }
    previous_date = previous.get("previous_report_date") if same_report else normalize_date(previous.get("report_date"))
    for row in rows:
        old = previous_rows.get(row["code"])
        if same_report and old:
            row["previous_short_shares"] = old.get("previous_short_shares")
            row["change_shares"] = old.get("change_shares")
            row["change_pct"] = old.get("change_pct")
        else:
            old_shares = old.get("short_shares") if old else None
            row["previous_short_shares"] = old_shares
            row["change_shares"] = row["short_shares"] - old_shares if row["short_shares"] is not None and old_shares is not None else None
            row["change_pct"] = ((row["short_shares"] / old_shares) - 1) * 100 if row["short_shares"] is not None and old_shares not in (None, 0) else None

    payload = {
        "schema_v": 1,
        "generated_at": now,
        "provider": "Securities and Futures Commission (Hong Kong)",
        "source_url": resolved_url,
        "report_date": report_date,
        "previous_report_date": previous_date,
        "data_kind": "official_weekly_reportable_short_positions",
        "is_observed": True,
        "stale": False,
        "coverage_note": "Specified shares above the SFC reporting threshold only. Missing code means not covered, not zero short interest.",
        "row_count": len(rows),
        "rows": rows,
    }
    write_payload(payload)
    print(f"Wrote {OUT}: report={report_date} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
