"""CCASS TimesFM forecaster for single names, lists, and screens.

Examples:
    python ccass_timesfm_forecast.py --stock 00700
    python ccass_timesfm_forecast.py --codes 00700,00941,09988
    python ccass_timesfm_forecast.py --screen top --limit 20
    python ccass_timesfm_forecast.py --screen rising --field broker_top5_pct
    python ccass_timesfm_forecast.py --screen falling --json-out data/timesfm_forecast.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("CCASS_DB_PATH", ROOT / "ccass" / "holdings.db"))
DEFAULT_JSON_OUT = Path(os.getenv("TIMESFM_JSON_OUT", ROOT / "data" / "timesfm_forecast.json"))
MODEL_NAME = os.getenv("TIMESFM_MODEL", "google/timesfm-2.5-200m-pytorch")
NAME_PATH_CANDIDATES = [ROOT / "holdings.json", ROOT / "data" / "holdings.json"]
ALLOWED_FIELDS = {
    "broker_top5_pct",
    "top5_pct",
    "top10_pct",
    "adj_hhi",
    "top_broker_pct",
    "futu_pct",
    "a00005_pct",
    "adjusted_float",
    "num_participants",
    "total_pct",
}


def require_timesfm():
    try:
        from timesfm import ForecastConfig, TimesFM_2p5_200M_torch
    except ImportError as exc:
        raise RuntimeError(
            "timesfm is not installed in this interpreter. "
            "Run this file with .venv-timesfm\\Scripts\\python.exe."
        ) from exc
    return TimesFM_2p5_200M_torch, ForecastConfig


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=1)
def load_name_map() -> dict[str, str]:
    for path in NAME_PATH_CANDIDATES:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        rows = payload.get("stocks", []) if isinstance(payload, dict) else []
        return {
            str(row.get("c", "")).strip(): str(row.get("n", "")).strip()
            for row in rows
            if isinstance(row, dict) and row.get("c") and row.get("n")
        }
    return {}


def validate_field(field: str) -> str:
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Illegal field: {field}. Allowed: {sorted(ALLOWED_FIELDS)}")
    return field


def fetch_series(conn: sqlite3.Connection, stock_code: str, field: str, min_days: int):
    rows = conn.execute(
        f"""
        SELECT trade_date, {field}
        FROM ccass_daily
        WHERE stock_code = ? AND {field} IS NOT NULL
        ORDER BY trade_date
        """,
        (stock_code,),
    ).fetchall()
    if len(rows) < min_days:
        return None
    dates = [row["trade_date"] for row in rows]
    values = np.array([row[field] for row in rows], dtype=np.float32)
    return {"dates": dates, "values": values}


def fetch_stock_name(conn: sqlite3.Connection, stock_code: str) -> str:
    name_map = load_name_map()
    if stock_code in name_map:
        return name_map[stock_code]
    row = conn.execute(
        "SELECT stock_name FROM stock_universe WHERE stock_code = ?",
        (stock_code,),
    ).fetchone()
    return row["stock_name"] if row and row["stock_name"] else stock_code


def recent_change(conn: sqlite3.Connection, stock_code: str, field: str, lookback: int) -> float | None:
    rows = conn.execute(
        f"""
        SELECT trade_date, {field}
        FROM ccass_daily
        WHERE stock_code = ? AND {field} IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (stock_code, lookback + 1),
    ).fetchall()
    if len(rows) < lookback + 1:
        return None
    return float(rows[0][field]) - float(rows[-1][field])


def select_screen_codes(
    conn: sqlite3.Connection,
    field: str,
    screen: str,
    limit: int,
    min_days: int,
    lookback: int,
):
    candidates = conn.execute(
        f"""
        WITH latest AS (
            SELECT stock_code,
                   trade_date,
                   {field} AS metric,
                   ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) AS rn
            FROM ccass_daily
            WHERE {field} IS NOT NULL
        ),
        counts AS (
            SELECT stock_code,
                   COUNT(*) AS row_count
            FROM ccass_daily
            WHERE {field} IS NOT NULL
            GROUP BY stock_code
            HAVING COUNT(*) >= ?
        )
        SELECT latest.stock_code, latest.metric
        FROM latest
        JOIN counts ON counts.stock_code = latest.stock_code
        WHERE latest.rn = 1
        """,
        (min_days,),
    ).fetchall()

    items = []
    for row in candidates:
        code = row["stock_code"]
        items.append(
            {
                "stock_code": code,
                "latest_value": float(row["metric"]),
                "recent_delta": recent_change(conn, code, field, lookback),
            }
        )

    if screen == "top":
        items.sort(key=lambda item: item["latest_value"], reverse=True)
    elif screen == "rising":
        items = [item for item in items if item["recent_delta"] is not None]
        items.sort(key=lambda item: item["recent_delta"], reverse=True)
    elif screen == "falling":
        items = [item for item in items if item["recent_delta"] is not None]
        items.sort(key=lambda item: item["recent_delta"])
    else:
        raise ValueError(f"Unsupported screen: {screen}")

    return [item["stock_code"] for item in items[:limit]]


def build_model():
    TimesFMModel, ForecastConfig = require_timesfm()
    return TimesFMModel.from_pretrained(MODEL_NAME), ForecastConfig


def run_forecast(model, ForecastConfig, values: np.ndarray, horizon: int):
    model.compile(ForecastConfig(max_context=len(values), max_horizon=horizon))
    point_forecast, _ = model.forecast(horizon, [values.astype(np.float32)])
    return point_forecast[0]


def classify_signal(delta: float) -> str:
    if delta >= 2.0:
        return "crowding_up"
    if delta >= 0.5:
        return "up"
    if delta <= -2.0:
        return "distribution_risk"
    if delta <= -0.5:
        return "down"
    return "flat"


def build_record(
    conn: sqlite3.Connection,
    model,
    ForecastConfig,
    stock_code: str,
    field: str,
    horizon: int,
    min_days: int,
    lookback: int,
):
    series = fetch_series(conn, stock_code, field, min_days)
    if not series:
        return None

    pred = run_forecast(model, ForecastConfig, series["values"], horizon)
    latest = float(series["values"][-1])
    forecast_end = float(pred[-1])
    delta = forecast_end - latest
    recent_delta_value = recent_change(conn, stock_code, field, lookback)

    return {
        "stock_code": stock_code,
        "stock_name": fetch_stock_name(conn, stock_code),
        "field": field,
        "history_days": len(series["values"]),
        "from_date": series["dates"][0],
        "to_date": series["dates"][-1],
        "latest": round(latest, 4),
        "recent_delta": None if recent_delta_value is None else round(float(recent_delta_value), 4),
        "forecast": [round(float(x), 4) for x in pred],
        "forecast_end": round(forecast_end, 4),
        "forecast_delta": round(delta, 4),
        "signal": classify_signal(delta),
    }


def parse_codes(args) -> list[str]:
    if args.codes:
        return [code.strip() for code in args.codes.split(",") if code.strip()]
    if args.stock:
        return [args.stock.strip()]
    return []


def print_table(records: list[dict]):
    if not records:
        print("No forecast records.")
        return
    print("| Code | Name | Latest | Recent | F+1 | F+N | Delta | Signal |")
    print("|------|------|--------|--------|-----|------|-------|--------|")
    for record in records:
        first = record["forecast"][0] if record["forecast"] else record["latest"]
        recent = "--" if record["recent_delta"] is None else f"{record['recent_delta']:+.2f}"
        print(
            f"| {record['stock_code']} | {record['stock_name']} | {record['latest']:.2f} | "
            f"{recent} | {first:.2f} | {record['forecast_end']:.2f} | "
            f"{record['forecast_delta']:+.2f} | {record['signal']} |"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", help="Single stock code, e.g. 00700")
    parser.add_argument("--codes", help="Comma-separated stock list")
    parser.add_argument(
        "--screen",
        choices=["top", "rising", "falling"],
        help="Auto-select stocks from latest CCASS data",
    )
    parser.add_argument("--field", default="broker_top5_pct")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--min-days", type=int, default=20)
    parser.add_argument("--lookback", type=int, default=5)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    field = validate_field(args.field)

    with connect_db() as conn:
        codes = parse_codes(args)
        if args.screen:
            codes = select_screen_codes(
                conn=conn,
                field=field,
                screen=args.screen,
                limit=args.limit,
                min_days=args.min_days,
                lookback=args.lookback,
            )
        if not codes:
            raise SystemExit("Provide --stock, --codes, or --screen.")

        model, ForecastConfig = build_model()
        records = []
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
                records.append({"stock_code": code, "error": str(exc)})
                continue
            if record:
                records.append(record)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(DB_PATH),
        "model": MODEL_NAME,
        "field": field,
        "horizon": args.horizon,
        "min_days": args.min_days,
        "lookback": args.lookback,
        "screen": args.screen,
        "count": len(records),
        "records": records,
    }

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.json_only:
        ok_records = [record for record in records if "error" not in record]
        print_table(ok_records)
        error_records = [record for record in records if "error" in record]
        if error_records:
            print()
            print("Errors:")
            for item in error_records:
                print(f"- {item['stock_code']}: {item['error']}")
        print()
        print(f"JSON written to {out_path}")


if __name__ == "__main__":
    main()
