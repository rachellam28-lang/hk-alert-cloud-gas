#!/usr/bin/env python3
"""Build a compact, source-labelled options key-level snapshot.

The output contains derived aggregates only. Raw chains are not published.
Missing option observations remain unavailable and are never replaced by zero.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "options_levels.json"
ENV_PATH = BASE / ".env"
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "GLD", "NVDA", "AAPL", "TSLA")
LABELS = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "GLD": "Gold ETF",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "TSLA": "Tesla",
}


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def number(value: Any) -> float | None:
    if value in (None, "", "N/A", "NaN"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def iso_day(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


def read_previous() -> dict:
    try:
        payload = json.loads(OUT.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_payload(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def marketdata_token() -> str:
    return (
        os.environ.get("MARKETDATA_API_TOKEN", "").strip()
        or os.environ.get("MARKETDATA_TOKEN", "").strip()
    )


def marketdata_chain(symbol: str, timeout: int) -> tuple[list[dict], dict]:
    today = date.today()
    params = urllib.parse.urlencode(
        {
            "from": today.isoformat(),
            "to": (today + timedelta(days=65)).isoformat(),
            "strikeLimit": "160",
            "dateformat": "timestamp",
        }
    )
    url = f"https://api.marketdata.app/v1/options/chain/{symbol}/?{params}"
    headers = {"User-Agent": "hk-alert-cloud-gas/1.0"}
    token = marketdata_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"MarketData HTTP {exc.code}: {detail}") from exc
    if not isinstance(raw, dict) or raw.get("s") != "ok":
        raise RuntimeError(str(raw.get("errmsg") if isinstance(raw, dict) else "invalid response"))

    fields = (
        "optionSymbol",
        "underlying",
        "expiration",
        "side",
        "strike",
        "updated",
        "openInterest",
        "volume",
        "underlyingPrice",
        "iv",
    )
    count = len(raw.get("optionSymbol") or [])
    rows = []
    for index in range(count):
        row = {}
        for field in fields:
            values = raw.get(field)
            row[field] = values[index] if isinstance(values, list) and index < len(values) else None
        rows.append(
            {
                "contract": row["optionSymbol"],
                "expiry": iso_day(row["expiration"]),
                "side": str(row["side"] or "").lower(),
                "strike": number(row["strike"]),
                "open_interest": integer(row["openInterest"]),
                "volume": integer(row["volume"]),
                "iv": number(row["iv"]),
                "spot": number(row["underlyingPrice"]),
                "observed_at": row["updated"],
            }
        )
    return rows, {
        "provider": "MarketData.app",
        "provider_url": "https://www.marketdata.app/docs/api/options/chain/",
        "delay": "24h delayed" if not token else "account entitlement",
        "authenticated": bool(token),
    }


def futu_ready(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def futu_chains(symbols: list[str]) -> tuple[dict[str, list[dict]], dict, list[str]]:
    """Read Futu option snapshots when OpenD has a healthy quote backend."""
    if os.environ.get("USE_FUTU", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {}, {}, ["Futu disabled"]
    host = os.environ.get("FUTU_HOST", "127.0.0.1")
    port = int(os.environ.get("FUTU_PORT", "11111"))
    if not futu_ready(host, port):
        return {}, {}, ["Futu OpenD unavailable"]
    try:
        from futu import OpenQuoteContext, RET_OK
    except Exception as exc:
        return {}, {}, [f"Futu SDK unavailable: {exc}"]

    output: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    errors: list[str] = []
    start = date.today()
    end = start + timedelta(days=30)
    context = OpenQuoteContext(host=host, port=port)
    try:
        ret, state = context.get_global_state()
        market_us = str(state.get("market_us") or "").upper() if isinstance(state, dict) else ""
        if (
            ret != RET_OK
            or not isinstance(state, dict)
            or not state.get("qot_logined")
            or market_us in {"", "NONE", "UNKNOWN"}
        ):
            return {}, {}, ["Futu quote backend not logged in"]
        for symbol in symbols:
            code = f"US.{symbol}"
            ret, chain = context.get_option_chain(code, start=start.isoformat(), end=end.isoformat())
            if ret != RET_OK or not hasattr(chain, "empty") or chain.empty:
                errors.append(f"{symbol}: Futu option chain unavailable")
                continue
            ret, underlying = context.get_market_snapshot([code])
            if ret != RET_OK or underlying.empty:
                errors.append(f"{symbol}: Futu underlying snapshot unavailable")
                continue
            spot = number(underlying.iloc[0].get("last_price"))
            snapshots = []
            codes = [str(value) for value in chain["code"].tolist() if value]
            for offset in range(0, len(codes), 100):
                ret, frame = context.get_market_snapshot(codes[offset : offset + 100])
                if ret != RET_OK or not hasattr(frame, "iterrows"):
                    errors.append(f"{symbol}: Futu option snapshot batch unavailable")
                    continue
                snapshots.extend(row for _, row in frame.iterrows())
            rows = []
            for row in snapshots:
                if not bool(row.get("option_valid", False)):
                    continue
                side = str(row.get("option_type") or "").lower()
                if "call" in side:
                    side = "call"
                elif "put" in side:
                    side = "put"
                rows.append(
                    {
                        "contract": row.get("code"),
                        "expiry": iso_day(row.get("strike_time")),
                        "side": side,
                        "strike": number(row.get("option_strike_price")),
                        "open_interest": integer(row.get("option_open_interest")),
                        "volume": integer(row.get("volume")),
                        "iv": number(row.get("option_implied_volatility")),
                        "spot": spot,
                        "observed_at": row.get("update_time"),
                    }
                )
            if rows:
                output[symbol] = rows
                meta[symbol] = {
                    "provider": "Futu OpenD",
                    "provider_url": "https://openapi.futunn.com/",
                    "delay": "account quote entitlement",
                    "authenticated": True,
                }
    except Exception as exc:
        errors.append(f"Futu: {exc}")
    finally:
        context.close()
    return output, meta, errors


def observed_max(values: list[int | None]) -> int | None:
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None


def derive_expiry(rows: list[dict], expiry: str, spot: float) -> dict | None:
    selected = [row for row in rows if row.get("expiry") == expiry and row.get("strike") is not None]
    if not selected:
        return None
    strikes: dict[float, dict] = defaultdict(
        lambda: {
            "call_oi": None,
            "put_oi": None,
            "call_volume": None,
            "put_volume": None,
            "call_iv": None,
            "put_iv": None,
        }
    )
    oi_observed = 0
    for row in selected:
        strike = float(row["strike"])
        side = row.get("side")
        if side not in {"call", "put"}:
            continue
        oi = row.get("open_interest")
        volume = row.get("volume")
        if oi is not None:
            oi_observed += 1
        strikes[strike][f"{side}_oi"] = oi
        strikes[strike][f"{side}_volume"] = volume
        strikes[strike][f"{side}_iv"] = row.get("iv")

    call_candidates = [(strike, item["call_oi"]) for strike, item in strikes.items() if (item["call_oi"] or 0) > 0]
    put_candidates = [(strike, item["put_oi"]) for strike, item in strikes.items() if (item["put_oi"] or 0) > 0]
    call_wall = max(call_candidates, key=lambda item: item[1]) if call_candidates else None
    put_wall = max(put_candidates, key=lambda item: item[1]) if put_candidates else None

    coverage = round(100 * oi_observed / len(selected), 1) if selected else 0.0
    max_pain = None
    if coverage >= 80 and call_candidates and put_candidates:
        payouts = []
        for settle in sorted(strikes):
            call_loss = sum((item["call_oi"] or 0) * max(settle - strike, 0) for strike, item in strikes.items())
            put_loss = sum((item["put_oi"] or 0) * max(strike - settle, 0) for strike, item in strikes.items())
            payouts.append((settle, call_loss + put_loss))
        max_pain = min(payouts, key=lambda item: item[1])[0] if payouts else None

    display_rows = []
    for strike, item in strikes.items():
        total_oi = None
        if item["call_oi"] is not None or item["put_oi"] is not None:
            total_oi = (item["call_oi"] or 0) + (item["put_oi"] or 0)
        total_volume = None
        if item["call_volume"] is not None or item["put_volume"] is not None:
            total_volume = (item["call_volume"] or 0) + (item["put_volume"] or 0)
        display_rows.append(
            {
                "strike": strike,
                **item,
                "total_oi": total_oi,
                "total_volume": total_volume,
                "distance_pct": round((strike / spot - 1) * 100, 2) if spot else None,
            }
        )
    display_rows.sort(key=lambda item: item["total_oi"] if item["total_oi"] is not None else -1, reverse=True)
    display_rows = sorted(display_rows[:36], key=lambda item: item["strike"])

    call_oi_total = sum(value for _, value in call_candidates)
    put_oi_total = sum(value for _, value in put_candidates)
    call_volume_total = sum((item["call_volume"] or 0) for item in strikes.values())
    put_volume_total = sum((item["put_volume"] or 0) for item in strikes.values())
    return {
        "expiry": expiry,
        "spot": spot,
        "contracts": len(selected),
        "oi_coverage_pct": coverage,
        "call_wall": {"strike": call_wall[0], "open_interest": call_wall[1]} if call_wall else None,
        "put_wall": {"strike": put_wall[0], "open_interest": put_wall[1]} if put_wall else None,
        "max_pain": max_pain,
        "call_oi": call_oi_total if call_candidates else None,
        "put_oi": put_oi_total if put_candidates else None,
        "put_call_oi_ratio": round(put_oi_total / call_oi_total, 3) if call_oi_total else None,
        "call_volume": call_volume_total,
        "put_volume": put_volume_total,
        "put_call_volume_ratio": round(put_volume_total / call_volume_total, 3) if call_volume_total else None,
        "rows": display_rows,
    }


def derive_symbol(symbol: str, rows: list[dict], meta: dict) -> dict | None:
    clean = [row for row in rows if row.get("expiry") and row.get("side") in {"call", "put"}]
    spots = [row["spot"] for row in clean if row.get("spot") is not None]
    if not clean or not spots:
        return None
    spot = spots[0]
    expiries = sorted({row["expiry"] for row in clean if row["expiry"] >= date.today().isoformat()})[:3]
    derived = [derive_expiry(clean, expiry, spot) for expiry in expiries]
    derived = [item for item in derived if item]
    if not derived:
        return None
    observed_at = max((str(row.get("observed_at")) for row in clean if row.get("observed_at")), default=None)
    return {
        "symbol": symbol,
        "label": LABELS.get(symbol, symbol),
        "spot": spot,
        "observed_at": observed_at,
        "provider": meta.get("provider"),
        "provider_url": meta.get("provider_url"),
        "delay": meta.get("delay"),
        "expiries": derived,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build observed options key levels")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeout", type=int, default=35)
    parser.add_argument("--best-effort", action="store_true")
    parser.add_argument("--skip-futu", action="store_true")
    args = parser.parse_args()
    load_env()
    symbols = list(dict.fromkeys(part.strip().upper() for part in args.symbols.split(",") if part.strip()))
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    errors: list[str] = []
    raw_by_symbol: dict[str, list[dict]] = {}
    meta_by_symbol: dict[str, dict] = {}

    if not args.skip_futu:
        futu_rows, futu_meta, futu_errors = futu_chains(symbols)
        raw_by_symbol.update(futu_rows)
        meta_by_symbol.update(futu_meta)
        errors.extend(futu_errors)

    token = marketdata_token()
    for symbol in symbols:
        if symbol in raw_by_symbol:
            continue
        if not token and symbol != "AAPL":
            errors.append(f"{symbol}: MARKETDATA_API_TOKEN not configured and Futu unavailable")
            continue
        try:
            rows, meta = marketdata_chain(symbol, args.timeout)
            raw_by_symbol[symbol] = rows
            meta_by_symbol[symbol] = meta
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    underlyings = []
    for symbol in symbols:
        if symbol not in raw_by_symbol:
            continue
        item = derive_symbol(symbol, raw_by_symbol[symbol], meta_by_symbol.get(symbol, {}))
        if item:
            underlyings.append(item)
        else:
            errors.append(f"{symbol}: chain had no usable observed OI rows")

    if not underlyings:
        previous = read_previous()
        if previous and args.best_effort:
            previous["stale"] = True
            previous["refresh_attempted_at"] = generated_at
            previous["refresh_errors"] = errors
            write_payload(previous)
            print("WARN: options sources unavailable; preserved prior snapshot")
            return 0
        print("ERROR: no observed options levels available", file=sys.stderr)
        return 1

    observed_days = [iso_day(item.get("observed_at")) for item in underlyings]
    observed_days = [item for item in observed_days if item]
    payload = {
        "schema_v": 1,
        "generated_at": generated_at,
        "observed_date": max(observed_days) if observed_days else None,
        "status": "PASS" if len(underlyings) == len(symbols) else "PARTIAL",
        "stale": False,
        "data_kind": "observed_option_chain_derived_levels",
        "is_observed": True,
        "requested_symbols": symbols,
        "available_symbols": [item["symbol"] for item in underlyings],
        "coverage_note": (
            "OI walls and max pain are derived from observed option chains. "
            "A missing symbol or field is unavailable, never zero."
        ),
        "method": {
            "call_wall": "strike with highest observed call open interest",
            "put_wall": "strike with highest observed put open interest",
            "max_pain": "listed strike minimizing aggregate intrinsic payout weighted by observed open interest",
        },
        "underlyings": underlyings,
        "refresh_errors": errors,
    }
    write_payload(payload)
    print(
        f"Wrote {OUT}: available={len(underlyings)}/{len(symbols)} "
        f"expiries={sum(len(item['expiries']) for item in underlyings)} status={payload['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
