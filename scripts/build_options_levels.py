#!/usr/bin/env python3
"""Build a compact, source-labelled options key-level snapshot.

The output contains derived aggregates only. Raw chains are not published.
Missing option observations remain unavailable and are never replaced by zero.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
DEFAULT_SYMBOLS = ("HSI", "SPY", "QQQ", "IWM", "GLD", "NVDA", "AAPL", "TSLA")
LABELS = {
    "HSI": "恒生指數期權",
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "GLD": "Gold ETF",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "TSLA": "Tesla",
}
HKEX_HSI_REPORT = "https://www.hkex.com.hk/chi/stat/dmstat/dayrpt/hsioc{stamp}.htm"
HKEX_ROW = re.compile(r"^\s*(\d{2})\s*年\s*(\d{2})\s*月\s*(\d+)\s*(認購|認沽)\s+(.*)$")


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


def fetch_hkex_hsi_report(report_date: date, timeout: int) -> tuple[str, str]:
    url = HKEX_HSI_REPORT.format(stamp=report_date.strftime("%y%m%d"))
    request = urllib.request.Request(url, headers={"User-Agent": "hk-alert-cloud-gas/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if len(raw) < 10_000:
        raise RuntimeError(f"HKEX report too small: {len(raw)} bytes")
    return raw.decode("big5", "replace"), url


def parse_hkex_hsi_report(text: str, report_date: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        match = HKEX_ROW.match(line)
        if not match:
            continue
        year, month, strike_text, side_text, remainder = match.groups()
        parts = remainder.split("|")
        if len(parts) != 3:
            continue
        fields = [re.findall(r"[+-]?\d+(?:\.\d+)?", part) for part in parts]
        if len(fields[0]) < 5 or len(fields[1]) < 7 or len(fields[2]) < 5:
            continue
        after = [number(value) for value in fields[0][-5:]]
        day_values = [number(value) for value in fields[1][-7:]]
        total = [number(value) for value in fields[2][-5:]]
        if any(value is None for value in after + day_values + total):
            continue
        rows.append(
            {
                "report_date": report_date,
                "contract_month": f"20{year}-{month}",
                "strike": float(strike_text),
                "side": "call" if side_text == "認購" else "put",
                "after_open": after[0],
                "after_high": after[1],
                "after_low": after[2],
                "after_last": after[3],
                "after_volume": int(after[4]),
                "day_open": day_values[0],
                "day_high": day_values[1],
                "day_low": day_values[2],
                "settlement": day_values[3],
                "settlement_change": day_values[4],
                "iv": day_values[5] / 100 if day_values[5] else None,
                "day_volume": int(day_values[6]),
                "contract_high": total[0],
                "contract_low": total[1],
                "total_volume": int(total[2]),
                "open_interest": int(total[3]),
                "open_interest_change": int(total[4]),
            }
        )
    if not rows:
        raise RuntimeError("HKEX HSI report had no parseable option rows")
    return rows


def latest_hkex_hsi_reports(timeout: int) -> tuple[list[dict], list[dict], str, str, str, str]:
    found: list[tuple[date, str, str]] = []
    for offset in range(0, 16):
        candidate = date.today() - timedelta(days=offset)
        try:
            text, url = fetch_hkex_hsi_report(candidate, timeout)
            rows = parse_hkex_hsi_report(text, candidate.isoformat())
        except Exception:
            continue
        found.append((candidate, url, text))
        if len(found) == 2:
            current_date, current_url, current_text = found[0]
            prior_date, prior_url, prior_text = found[1]
            return (
                parse_hkex_hsi_report(current_text, current_date.isoformat()),
                parse_hkex_hsi_report(prior_text, prior_date.isoformat()),
                current_date.isoformat(),
                prior_date.isoformat(),
                current_url,
                prior_url,
            )
    raise RuntimeError("latest and previous HKEX HSI option reports unavailable")


def hsi_spot(report_date: str) -> float | None:
    path = BASE / "data" / "trend_matrix.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["indexes"]["HSI"]["rows"]
    except Exception:
        return None
    eligible = [row for row in rows if row.get("date", "") <= report_date and number(row.get("day", {}).get("close"))]
    return number(eligible[-1]["day"]["close"]) if eligible else None


def derive_hkex_month(current: list[dict], prior: list[dict], contract_month: str, spot: float) -> dict | None:
    selected = [row for row in current if row["contract_month"] == contract_month]
    if not selected:
        return None
    prior_lookup = {(row["contract_month"], row["strike"], row["side"]): row for row in prior}
    strikes: dict[float, dict] = defaultdict(dict)
    for row in selected:
        strike = row["strike"]
        side = row["side"]
        previous = prior_lookup.get((contract_month, strike, side), {})
        current_oi = row["open_interest"]
        oi_change = row["open_interest_change"]
        previous_oi = current_oi - oi_change
        current_volume = row["total_volume"]
        previous_volume = integer(previous.get("total_volume"))
        strikes[strike].update(
            {
                f"{side}_last": row["settlement"],
                f"{side}_settlement_change": row["settlement_change"],
                f"{side}_iv": row["iv"],
                f"{side}_volume": current_volume,
                f"{side}_previous_volume": previous_volume,
                f"{side}_volume_change": current_volume - previous_volume if previous_volume is not None else None,
                f"{side}_after_volume": row["after_volume"],
                f"{side}_day_volume": row["day_volume"],
                f"{side}_oi": current_oi,
                f"{side}_previous_oi": previous_oi,
                f"{side}_oi_change": oi_change,
                f"{side}_premium_estimate": round(row["settlement"] * current_volume * 50, 2),
            }
        )

    call_oi_total = sum(item.get("call_oi", 0) for item in strikes.values())
    put_oi_total = sum(item.get("put_oi", 0) for item in strikes.values())
    call_volume_total = sum(item.get("call_volume", 0) for item in strikes.values())
    put_volume_total = sum(item.get("put_volume", 0) for item in strikes.values())
    call_wall = max(((strike, item.get("call_oi", 0)) for strike, item in strikes.items()), key=lambda item: item[1], default=None)
    put_wall = max(((strike, item.get("put_oi", 0)) for strike, item in strikes.items()), key=lambda item: item[1], default=None)

    payouts = []
    for settle in sorted(strikes):
        call_loss = sum(item.get("call_oi", 0) * max(settle - strike, 0) for strike, item in strikes.items())
        put_loss = sum(item.get("put_oi", 0) * max(strike - settle, 0) for strike, item in strikes.items())
        payouts.append((settle, call_loss + put_loss))
    max_pain = min(payouts, key=lambda item: item[1])[0] if payouts and call_oi_total and put_oi_total else None

    display_rows = []
    for strike, item in strikes.items():
        total_oi = item.get("call_oi", 0) + item.get("put_oi", 0)
        total_volume = item.get("call_volume", 0) + item.get("put_volume", 0)
        if not total_oi and not total_volume:
            continue
        display_rows.append(
            {
                "strike": strike,
                **item,
                "call_oi_share_pct": round(item.get("call_oi", 0) / call_oi_total * 100, 2) if call_oi_total else None,
                "put_oi_share_pct": round(item.get("put_oi", 0) / put_oi_total * 100, 2) if put_oi_total else None,
                "total_oi": total_oi,
                "total_volume": total_volume,
                "distance_pct": round((strike / spot - 1) * 100, 2) if spot else None,
            }
        )
    near = [row for row in display_rows if spot * 0.75 <= row["strike"] <= spot * 1.25]
    ranked = sorted(near or display_rows, key=lambda row: (row["total_oi"], row["total_volume"]), reverse=True)[:54]
    ranked.sort(key=lambda row: row["strike"])
    return {
        "expiry": contract_month,
        "spot": spot,
        "contracts": len(selected),
        "oi_coverage_pct": 100.0,
        "call_wall": {"strike": call_wall[0], "open_interest": call_wall[1]} if call_wall and call_wall[1] else None,
        "put_wall": {"strike": put_wall[0], "open_interest": put_wall[1]} if put_wall and put_wall[1] else None,
        "max_pain": max_pain,
        "call_oi": call_oi_total,
        "put_oi": put_oi_total,
        "put_call_oi_ratio": round(put_oi_total / call_oi_total, 3) if call_oi_total else None,
        "call_volume": call_volume_total,
        "put_volume": put_volume_total,
        "put_call_volume_ratio": round(put_volume_total / call_volume_total, 3) if call_volume_total else None,
        "contract_multiplier": 50,
        "rows": ranked,
    }


def derive_hkex_hsi(
    current: list[dict],
    prior: list[dict],
    report_date: str,
    prior_date: str,
    source_url: str,
    prior_url: str,
) -> dict:
    spot = hsi_spot(report_date)
    if spot is None:
        raise RuntimeError("HSI spot unavailable for HKEX report date")
    months = sorted({row["contract_month"] for row in current if row["contract_month"] >= report_date[:7]})[:3]
    expiries = [derive_hkex_month(current, prior, month, spot) for month in months]
    expiries = [item for item in expiries if item and item["rows"]]
    if not expiries:
        raise RuntimeError("HKEX HSI reports had no usable active month")
    return {
        "symbol": "HSI",
        "label": LABELS["HSI"],
        "spot": spot,
        "observed_at": report_date,
        "previous_observed_at": prior_date,
        "provider": "HKEX Daily Market Report",
        "provider_url": source_url,
        "previous_provider_url": prior_url,
        "delay": "official end-of-day",
        "chain_layout": "split_call_strike_put",
        "expiries": expiries,
    }


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
    for row in display_rows:
        row["call_oi_share_pct"] = round((row.get("call_oi") or 0) / call_oi_total * 100, 2) if call_oi_total else None
        row["put_oi_share_pct"] = round((row.get("put_oi") or 0) / put_oi_total * 100, 2) if put_oi_total else None
        for side in ("call", "put"):
            row.setdefault(f"{side}_last", None)
            row.setdefault(f"{side}_previous_volume", None)
            row.setdefault(f"{side}_volume_change", None)
            row.setdefault(f"{side}_previous_oi", None)
            row.setdefault(f"{side}_oi_change", None)
            row.setdefault(f"{side}_premium_estimate", None)
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
    underlyings: list[dict] = []

    if "HSI" in symbols:
        try:
            current, prior, report_date, prior_date, source_url, prior_url = latest_hkex_hsi_reports(args.timeout)
            underlyings.append(derive_hkex_hsi(current, prior, report_date, prior_date, source_url, prior_url))
        except Exception as exc:
            errors.append(f"HSI: {exc}")

    market_symbols = [symbol for symbol in symbols if symbol != "HSI"]

    if not args.skip_futu and market_symbols:
        futu_rows, futu_meta, futu_errors = futu_chains(market_symbols)
        raw_by_symbol.update(futu_rows)
        meta_by_symbol.update(futu_meta)
        errors.extend(futu_errors)

    token = marketdata_token()
    for symbol in market_symbols:
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

    for symbol in market_symbols:
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
        "schema_v": 2,
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
            "hsi_chain": "HKEX official daily report; prior OI = current OI - official OI change",
            "premium_estimate": "official settlement price × observed total volume × HKD 50 contract multiplier",
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
