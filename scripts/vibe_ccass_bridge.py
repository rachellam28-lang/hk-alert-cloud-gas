#!/usr/bin/env python3
"""Bridge observed HK daily bars into Vibe-Trading's local loader.

This intentionally avoids Vibe-Trading's default HK Yahoo/yfinance route.
Only bars returned by this project's Cloudflare Kbar API are accepted.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
VIBE_ROOT = ROOT / ".tools" / "vibe-trading"
VIBE_HOME = VIBE_ROOT / "home"
DATA_DIR = VIBE_ROOT / "data" / "hk"
CONFIG_PATH = VIBE_HOME / ".vibe-trading" / "data-bridge" / "config.yaml"
DEFAULT_BASE_URL = "https://hk-alert-cloud-gas.pages.dev"
ALLOWED_SOURCE = "Tencent public HK daily K-line (unadjusted)"


def normalize_code(value: str) -> str:
    cleaned = str(value or "").strip().upper()
    cleaned = re.sub(r"^(?:HKEX:|HK\.)", "", cleaned)
    cleaned = re.sub(r"\.HK$", "", cleaned)
    if not re.fullmatch(r"\d{1,5}", cleaned):
        raise ValueError(f"invalid HK stock code: {value!r}")
    return f"{int(cleaned):05d}"


def fetch_payload(code: str, base_url: str, count: int) -> dict:
    query = urlencode({"count": count})
    url = f"{base_url.rstrip('/')}/api/kbar/{code}?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "hk-alert-vibe-bridge/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def validate_payload(payload: dict, code: str) -> tuple[str, list[dict]]:
    if payload.get("source") != ALLOWED_SOURCE:
        raise RuntimeError(f"untrusted Kbar source: {payload.get('source')!r}")
    entry = payload.get("entry") or {}
    expected_symbol = f"{int(code)}.HK"
    if entry.get("symbol") != expected_symbol:
        raise RuntimeError(
            f"symbol mismatch: expected {expected_symbol}, got {entry.get('symbol')!r}"
        )
    bars = ((entry.get("series") or {}).get("1d") or [])
    if len(bars) < 30:
        raise RuntimeError(f"insufficient observed bars: {len(bars)}")

    checked: list[dict] = []
    seen_dates: set[str] = set()
    for raw in bars:
        trade_date = str(raw.get("time") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", trade_date):
            raise RuntimeError(f"invalid bar date: {trade_date!r}")
        values = {key: float(raw[key]) for key in ("open", "high", "low", "close")}
        if min(values.values()) <= 0:
            raise RuntimeError(f"non-positive OHLC on {trade_date}")
        if values["high"] < max(values.values()) or values["low"] > min(values.values()):
            raise RuntimeError(f"invalid OHLC bounds on {trade_date}")
        if trade_date in seen_dates:
            raise RuntimeError(f"duplicate bar date: {trade_date}")
        seen_dates.add(trade_date)
        checked.append(
            {
                "date": trade_date,
                **values,
                "volume": max(0.0, float(raw.get("volume") or 0)),
            }
        )

    checked.sort(key=lambda row: row["date"])
    return expected_symbol, checked


def write_csv(code: str, bars: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = DATA_DIR / f"{code}.csv"
    temp = output.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        writer.writerows(bars)
    temp.replace(output)
    return output


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"sources": []}
    text = CONFIG_PATH.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("existing Vibe data bridge config requires PyYAML") from exc
        parsed = yaml.safe_load(text)
    return parsed if isinstance(parsed, dict) else {"sources": []}


def update_config(symbol: str, csv_path: Path) -> None:
    config = load_config()
    sources = config.get("sources")
    if not isinstance(sources, list):
        sources = []
    entry = {
        "symbol": symbol,
        "type": "csv",
        "path": csv_path.resolve().as_posix(),
        "columns": {
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        },
        "date_format": "%Y-%m-%d",
    }
    sources = [item for item in sources if item.get("symbol") != symbol]
    sources.append(entry)
    sources.sort(key=lambda item: str(item.get("symbol") or ""))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix(".yaml.tmp")
    temp.write_text(
        json.dumps({"sources": sources}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(CONFIG_PATH)


def verify_local_loader(symbol: str, first_date: str, last_date: str) -> int:
    os.environ["HOME"] = str(VIBE_HOME)
    os.environ["USERPROFILE"] = str(VIBE_HOME)
    from backtest.loaders import local_loader

    local_loader._CONFIG_PATH = CONFIG_PATH
    loader = local_loader.DataLoader()
    result = loader.fetch([symbol], first_date, last_date, interval="1D")
    frame = result.get(symbol)
    if frame is None or frame.empty:
        raise RuntimeError("Vibe local loader returned no bars")
    return len(frame)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load observed HK daily Kbars into Vibe-Trading without yfinance."
    )
    parser.add_argument("symbol", help="HK code, e.g. 1733, 01733, or 1733.HK")
    parser.add_argument("--count", type=int, default=260, choices=range(30, 261), metavar="30..260")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--verify", action="store_true", help="Read the bars back through Vibe local loader")
    parser.add_argument("--json", action="store_true", help="Print machine-readable status")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    code = normalize_code(args.symbol)
    payload = fetch_payload(code, args.base_url, args.count)
    symbol, bars = validate_payload(payload, code)
    csv_path = write_csv(code, bars)
    update_config(symbol, csv_path)
    verified_rows = verify_local_loader(symbol, bars[0]["date"], bars[-1]["date"]) if args.verify else None
    result = {
        "ok": True,
        "symbol": symbol,
        "source": ALLOWED_SOURCE,
        "bars": len(bars),
        "first_date": bars[0]["date"],
        "last_date": bars[-1]["date"],
        "csv": str(csv_path),
        "vibe_config": str(CONFIG_PATH),
        "vibe_verified_rows": verified_rows,
        "uses_yfinance": False,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(
            f"Vibe HK bridge OK: {symbol} {len(bars)} observed bars "
            f"({bars[0]['date']} -> {bars[-1]['date']}); loader={verified_rows or 'not checked'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
