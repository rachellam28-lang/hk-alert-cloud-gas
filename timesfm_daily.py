"""Daily TimesFM forecast generator for CCASS concentration signals.

Outputs:
  1. data/timesfm.json - structured forecast data for dashboard or bot use
  2. Markdown tables to stdout when not using --json-only

Examples:
    python timesfm_daily.py
    python timesfm_daily.py --field broker_top5_pct --field top10_pct
    python timesfm_daily.py --fields broker_top5_pct,adj_hhi,total_pct
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ccass_timesfm_forecast import (
    build_model,
    build_record,
    connect_db,
    select_screen_codes,
    validate_field,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "data" / "timesfm.json"


def resolve_fields(args) -> list[str]:
    fields: list[str] = []
    for value in args.field or []:
        if value:
            fields.append(value.strip())
    if args.fields:
        for value in args.fields.split(","):
            value = value.strip()
            if value:
                fields.append(value)
    if not fields:
        fields = ["broker_top5_pct"]

    ordered: list[str] = []
    seen = set()
    for field in fields:
        normalized = validate_field(field)
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def print_field_table(field: str, records: list[dict]):
    print()
    print(f"## {field}")
    print("| Code | Name | Latest | Recent | F+1 | F+3 | F+N | Delta | Signal |")
    print("|------|------|--------|--------|-----|-----|------|-------|--------|")
    for record in records:
        forecast = record.get("forecast", [])
        first = forecast[0] if forecast else record.get("latest", 0.0)
        third = forecast[2] if len(forecast) > 2 else record.get("forecast_end", first)
        recent = "--" if record.get("recent_delta") is None else f"{record['recent_delta']:+.2f}"
        print(
            f"| {record['stock_code']} | {record['stock_name']} | {record['latest']:.2f} | "
            f"{recent} | {first:.2f} | {third:.2f} | {record['forecast_end']:.2f} | "
            f"{record['forecast_delta']:+.2f} | {record['signal']} |"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--field", action="append", help="Repeatable field selector")
    parser.add_argument("--fields", help="Comma-separated field selector")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-days", type=int, default=25)
    parser.add_argument("--lookback", type=int, default=5)
    parser.add_argument("--json-out", default=str(OUTPUT_JSON))
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    fields = resolve_fields(args)

    with connect_db() as conn:
        latest_date = conn.execute("SELECT MAX(trade_date) FROM ccass_daily").fetchone()[0]
        model, ForecastConfig = build_model()

        by_field: dict[str, list[dict]] = {}
        field_meta: list[dict] = []
        total_errors = 0

        for field in fields:
            codes = select_screen_codes(
                conn=conn,
                field=field,
                screen="top",
                limit=args.top,
                min_days=args.min_days,
                lookback=args.lookback,
            )
            records: list[dict] = []
            error_items: list[dict] = []
            for code in codes:
                try:
                    record = build_record(
                        conn=conn,
                        model=model,
                        ForecastConfig=ForecastConfig,
                        stock_code=code,
                        field=field,
                        horizon=args.horizon,
                        min_days=args.min_days,
                        lookback=args.lookback,
                    )
                except Exception as exc:
                    error_items.append({"stock_code": code, "error": str(exc)})
                    total_errors += 1
                    continue
                if record:
                    records.append(record)

            by_field[field] = records
            field_meta.append(
                {
                    "field": field,
                    "count": len(records),
                    "error_count": len(error_items),
                    "top_codes": [item["stock_code"] for item in records[:5]],
                    "records": records,
                    "errors": error_items,
                }
            )

    payload = {
        "updated": latest_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "TimesFM model over observed CCASS holdings history",
        "data_kind": "model_forecast",
        "is_observed": False,
        "horizon": args.horizon,
        "min_days": args.min_days,
        "lookback": args.lookback,
        "primary_field": fields[0] if fields else None,
        "field_count": len(fields),
        "fields": field_meta,
        "by_field": by_field,
        "forecasts": by_field.get(fields[0], []) if fields else [],
        "errors": total_errors,
    }

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        return

    print(f"TimesFM daily forecast: {len(fields)} field(s), latest {latest_date}, horizon {args.horizon}d")
    for item in field_meta:
        print_field_table(item["field"], item["records"])
        if item["errors"]:
            print("Errors:")
            for err in item["errors"]:
                print(f"- {err['stock_code']}: {err['error']}")
    print()
    print(f"JSON written to {out_path}")


if __name__ == "__main__":
    main()
