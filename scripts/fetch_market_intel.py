#!/usr/bin/env python3
"""Fetch compact, observed HK market-intelligence snapshots from Longbridge CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "market_intel.json"
RANK_KEYS = ("hot_all-hk", "hot_up-hk", "trade_heat-hk")


def write_payload(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def run_json(args: list[str], timeout: int) -> dict:
    proc = subprocess.run(
        ["longbridge", *args, "--format", "json"],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(message or f"longbridge exited {proc.returncode}")
    return json.loads(proc.stdout.decode("utf-8", "replace"))


def as_number(value):
    if value in (None, ""):
        return None


def as_percent(value):
    result = as_number(value)
    return result * 100 if result is not None else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def code5(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-5:].zfill(5) if digits else ""


def compact_rank(row: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "code": code5(row.get("code") or row.get("symbol")),
        "last": as_number(row.get("last_done")),
        "change_pct": as_percent(row.get("chg")),
        "five_day_pct": as_percent(row.get("five_day_chg")),
        "twenty_day_pct": as_percent(row.get("twenty_day_chg")),
        "turnover_rate_pct": as_percent(row.get("turnover_rate")),
        "volume_rate": as_number(row.get("volume_rate")),
        "amount": as_number(row.get("total_amount")),
        "inflow": as_number(row.get("inflow")),
        "market_cap": as_number(row.get("market_cap")),
    }


def compact_anomaly(row: dict) -> dict:
    counter_id = str(row.get("counter_id") or "")
    return {
        "code": code5(counter_id.rsplit("/", 1)[-1]),
        "type": row.get("alert_name"),
        "emotion": row.get("emotion"),
        "values": row.get("change_values") or [],
        "observed_at": row.get("alert_time"),
    }


def compact_mover(row: dict) -> dict:
    stock = row.get("stock") if isinstance(row.get("stock"), dict) else {}
    return {
        "code": code5(stock.get("code")),
        "last": as_number(stock.get("last_done")),
        "change_pct": as_percent(stock.get("change")),
        "reason": row.get("alert_reason"),
        "observed_at": row.get("timestamp"),
    }


def load_previous() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--best-effort", action="store_true")
    args = parser.parse_args()

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    errors: list[str] = []
    ranks: dict[str, dict] = {}
    anomalies: list[dict] = []
    movers: list[dict] = []

    for key in RANK_KEYS:
        try:
            raw = run_json(["rank", "--key", key], args.timeout)
            rows = raw.get("lists") or []
            ranks[key] = {
                "updated_at": raw.get("updated_at"),
                "rows": [compact_rank(row, i + 1) for i, row in enumerate(rows) if code5(row.get("code") or row.get("symbol"))],
            }
        except Exception as exc:
            errors.append(f"rank {key}: {exc}")

    try:
        raw = run_json(["anomaly", "--market", "HK", "--count", "100"], args.timeout)
        anomalies = [compact_anomaly(row) for row in (raw.get("changes") or []) if compact_anomaly(row)["code"]]
    except Exception as exc:
        errors.append(f"anomaly: {exc}")

    try:
        raw = run_json(["top-movers", "--market", "HK", "--count", "50"], args.timeout)
        movers = [compact_mover(row) for row in (raw.get("events") or []) if compact_mover(row)["code"]]
        movers_updated = raw.get("updated_at")
    except Exception as exc:
        movers_updated = None
        errors.append(f"top-movers: {exc}")

    if not ranks and not anomalies and not movers:
        previous = load_previous()
        if previous and args.best_effort:
            previous["refresh_attempted_at"] = generated_at
            previous["stale"] = True
            previous["refresh_errors"] = errors
            write_payload(previous)
            print("WARN: Longbridge unavailable; preserved prior market-intel snapshot")
            return 0
        print("ERROR: no Longbridge market-intel source succeeded", file=sys.stderr)
        return 1

    payload = {
        "schema_v": 1,
        "generated_at": generated_at,
        "provider": "Longbridge CLI",
        "data_kind": "observed_provider_snapshot",
        "is_observed": True,
        "stale": False,
        "coverage_note": "Provider ranking and event snapshots; absence is not a zero signal.",
        "ranks": ranks,
        "anomalies": anomalies,
        "top_movers": {"updated_at": movers_updated, "rows": movers},
        "refresh_errors": errors,
    }
    write_payload(payload)
    print(f"Wrote {OUT}: ranks={sum(len(v['rows']) for v in ranks.values())} anomalies={len(anomalies)} movers={len(movers)} errors={len(errors)}")
    return 0 if not errors or args.best_effort else 1


if __name__ == "__main__":
    raise SystemExit(main())
