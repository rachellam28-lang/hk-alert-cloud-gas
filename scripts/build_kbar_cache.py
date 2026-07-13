from __future__ import annotations

import json
import os
import subprocess
import sys
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kbar_cache.json"
SHARD_DIR = ROOT / "data" / "kbar_symbols"
LONGBRIDGE = "longbridge"
_FUTU_CTX = None
_FUTU_CTX_LOCK = threading.Lock()
_CCASS_METRICS = None

def fetch_futu_series(symbol: str, period: str, count: int) -> list[dict]:
    global _FUTU_CTX
    try:
        from futu import OpenQuoteContext, KLType, AuType, RET_OK
        try:
            from scripts.futu_env import load_repo_env, get_futu_host, get_futu_port
        except ModuleNotFoundError:
            from futu_env import load_repo_env, get_futu_host, get_futu_port
        load_repo_env(ROOT)
        if _FUTU_CTX is None:
            with _FUTU_CTX_LOCK:
                if _FUTU_CTX is None:
                    _FUTU_CTX = OpenQuoteContext(host=get_futu_host(), port=get_futu_port())
        code = f"HK.{str(int(symbol.split('.')[0])).zfill(5)}"
        if period == "1d":
            ktype = KLType.K_DAY
            start = (datetime.now() - timedelta(days=max(550, count * 2))).strftime("%Y-%m-%d")
        elif period == "1h":
            ktype = KLType.K_60M
            start = (datetime.now() - timedelta(days=max(120, count))).strftime("%Y-%m-%d")
        else:
            raise ValueError(f"unsupported Futu period: {period}")
        rows = []
        page_req_key = None
        while True:
            ret, data, page_req_key = _FUTU_CTX.request_history_kline(
                code,
                start=start,
                end=datetime.now().strftime("%Y-%m-%d"),
                ktype=ktype,
                autype=AuType.QFQ,
                max_count=1000,
                page_req_key=page_req_key,
            )
            if ret != RET_OK or data is None or data.empty:
                detail = str(data) if data is not None else str(ret)
                raise RuntimeError(f"Futu {period} unavailable: {detail}")
            for _, row in data.iterrows():
                rows.append({"time": str(row.get("time_key", row.get("time", ""))), "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "volume": float(row.get("volume", 0) or 0), "turnover": float(row.get("turnover", 0) or 0)})
            if not page_req_key:
                break
        return rows[-count:]
    except Exception as exc:
        print(f"[futu-{period}] {symbol} failed: {exc}", file=sys.stderr, flush=True)
        return []


def fetch_futu_daily(symbol: str, count: int) -> list[dict]:
    return fetch_futu_series(symbol, "1d", count)

PRESETS = [
    {
        "symbol": "700.HK",
        "label": "騰訊",
        "market": "hk",
        "aliases": ["700", "00700", "HKEX:700", "HKEX:00700", "TENCENT"],
    },
    {
        "symbol": "9988.HK",
        "label": "阿里",
        "market": "hk",
        "aliases": ["9988", "09988", "HKEX:9988", "HKEX:09988", "BABA HK"],
    },
    {
        "symbol": "2800.HK",
        "label": "盈富",
        "market": "hk",
        "aliases": ["2800", "02800", "HKEX:2800", "HKEX:02800", "HSI", "HSI ETF"],
    },
    {
        "symbol": "NVDA.US",
        "label": "NVDA",
        "market": "us",
        "aliases": ["NVDA", "NASDAQ:NVDA"],
    },
    {
        "symbol": "QQQ.US",
        "label": "QQQ",
        "market": "us",
        "aliases": ["QQQ", "NASDAQ:QQQ"],
    },
    {
        "symbol": "SPY.US",
        "label": "SPY",
        "market": "us",
        "aliases": ["SPY", "SPX", "S&P500", "SP500"],
    },
    {
        "symbol": "GLD.US",
        "label": "GLD",
        "market": "us",
        "aliases": ["GLD", "GOLD", "XAU", "XAUUSD"],
    },
    {
        "symbol": "EWJ.US",
        "label": "EWJ",
        "market": "us",
        "aliases": ["EWJ", "NI225", "NIKKEI", "JAPAN"],
    },
    {
        "symbol": "ASHR.US",
        "label": "ASHR",
        "market": "us",
        "aliases": ["ASHR", "CHINA", "CSI300", "SSE:000001", "SH000001"],
    },
]

PERIOD_COUNTS = {
    "1d": 260,
    "1h": 120,
}

DYNAMIC_LIMIT = 32


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def build_universe() -> list[dict]:
    """Keep core cross-market symbols and add the strongest current HK setups."""
    universe = [dict(item) for item in PRESETS]
    seen = {item["symbol"] for item in universe}
    vqc_data = load_json(ROOT / "data" / "vqc_backtest.json", {})
    vqc_events = vqc_data.get("events", []) if isinstance(vqc_data, dict) else []
    latest_vqc = max((str(row.get("signal_date") or "") for row in vqc_events), default="")
    latest_vqc_rows = [row for row in vqc_events if str(row.get("signal_date") or "") == latest_vqc]
    latest_vqc_rows.sort(key=lambda row: float(row.get("volume_ratio") or 0), reverse=True)
    for row in latest_vqc_rows:
        code = str(row.get("code") or "").strip().zfill(5)
        if not code.isdigit():
            continue
        symbol = f"{int(code)}.HK"
        if symbol in seen:
            continue
        universe.append({
            "symbol": symbol,
            "label": str(row.get("name") or code),
            "market": "hk",
            "aliases": [code, str(int(code)), f"HKEX:{code}"],
        })
        seen.add(symbol)
        if len(universe) >= len(PRESETS) + min(12, DYNAMIC_LIMIT):
            break
    rows = load_json(ROOT / "data" / "tradeable.json", [])
    if not isinstance(rows, list):
        rows = []
    rows.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
    for row in rows:
        raw_code = str(row.get("code") or "").strip()
        if not raw_code.isdigit():
            continue
        code = raw_code.zfill(5)
        symbol = f"{int(code)}.HK"
        if symbol in seen:
            continue
        universe.append({
            "symbol": symbol,
            "label": str(row.get("name") or code),
            "market": "hk",
            "aliases": [code, str(int(code)), f"HKEX:{code}"],
        })
        seen.add(symbol)
        if len(universe) >= len(PRESETS) + DYNAMIC_LIMIT:
            break
    return universe


def run_longbridge(args: list[str], timeout: int = 15):
    proc = subprocess.run(
        [LONGBRIDGE, *args, "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"longbridge rc={proc.returncode}")
    return json.loads(proc.stdout)


def normalize_quote(item: dict) -> dict:
    return {
        "symbol": item.get("symbol"),
        "last": to_float(item.get("last")),
        "open": to_float(item.get("open")),
        "high": to_float(item.get("high")),
        "low": to_float(item.get("low")),
        "prev_close": to_float(item.get("prev_close")),
        "change_value": to_float(item.get("change_value")),
        "change_percentage": to_float(item.get("change_percentage")),
        "volume": to_float(item.get("volume")),
        "turnover": to_float(item.get("turnover")),
        "status": item.get("status"),
    }


def normalize_bar(item: dict) -> dict:
    return {
        "time": item.get("time"),
        "open": to_float(item.get("open")),
        "high": to_float(item.get("high")),
        "low": to_float(item.get("low")),
        "close": to_float(item.get("close")),
        "volume": to_float(item.get("volume")),
        "turnover": to_float(item.get("turnover")),
    }


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_ccass_metrics() -> dict[str, dict]:
    data = load_json(ROOT / "holdings.json", {})
    if not isinstance(data, dict):
        return {}
    refs = data.get("trend_reference_dates", {})
    result = {}
    for row in data.get("stocks", []):
        code = str(row.get("c") or "").zfill(5)
        if not code:
            continue
        result[code] = {
            "date": data.get("updated"),
            "previous_date": refs.get("5"),
            "total_shares": row.get("ts"),
            "total_pct": row.get("tp"),
            "shares_delta": row.get("tsd"),
            "pct_delta": row.get("tpd"),
            "shares_delta_5d": row.get("d5s"),
            "pct_delta_5d": row.get("d5p"),
            "shares_delta_20d": row.get("d20s"),
            "pct_delta_20d": row.get("d20p"),
            "increase_days": int(row.get("su") or 0),
        }
    return result


def attach_ccass(payload: dict) -> None:
    metrics = load_ccass_metrics()
    for symbol, entry in payload.get("symbols", {}).items():
        if not symbol.endswith(".HK"):
            entry["ccass"] = None
            continue
        code = str(symbol.split(".", 1)[0]).zfill(5)
        entry["ccass"] = metrics.get(code)


def fetch_quotes(symbols: list[str]) -> tuple[dict[str, dict], list[dict]]:
    quotes: dict[str, dict] = {}
    errors: list[dict] = []
    for start in range(0, len(symbols), 12):
        batch = symbols[start:start + 12]
        try:
            rows = run_longbridge(["quote", *batch], timeout=20)
            for row in rows:
                symbol = row.get("symbol")
                if symbol:
                    quotes[symbol] = normalize_quote(row)
        except Exception as exc:
            errors.append({"scope": "quote", "symbols": batch, "error": str(exc)})
    return quotes, errors


def fetch_series(symbol: str, period: str, count: int) -> list[dict]:
    if symbol.endswith(".HK") and period in {"1d", "1h"}:
        futu_rows = fetch_futu_series(symbol, period, count)
        if futu_rows:
            return futu_rows
    rows = run_longbridge(["kline", symbol, "--period", period, "--count", str(count)], timeout=12)
    return [normalize_bar(row) for row in rows if isinstance(row, dict)]


def hk_entry(code: str) -> dict:
    global _CCASS_METRICS
    normalized = str(int(code)).zfill(5)
    symbol = f"{int(normalized)}.HK"
    series = {
        period: fetch_futu_series(symbol, period, count)
        for period, count in PERIOD_COUNTS.items()
    }
    daily = series.get("1d") or []
    hourly = series.get("1h") or []
    if not daily:
        raise RuntimeError(f"{normalized}: no Futu daily bars")
    last = daily[-1]
    previous = daily[-2] if len(daily) > 1 else last
    prev_close = to_float(previous.get("close"))
    last_close = to_float(last.get("close"))
    change = (last_close - prev_close) if last_close is not None and prev_close is not None else None
    change_pct = (change / prev_close * 100) if change is not None and prev_close else None
    entry = {
        "symbol": symbol,
        "label": normalized,
        "market": "hk",
        "aliases": [normalized, str(int(normalized)), f"HKEX:{normalized}", f"HKEX:{int(normalized)}"],
        "quote": {
            "symbol": symbol,
            "last": last_close,
            "open": to_float(last.get("open")),
            "high": to_float(last.get("high")),
            "low": to_float(last.get("low")),
            "prev_close": prev_close,
            "change_value": change,
            "change_percentage": change_pct,
            "volume": to_float(last.get("volume")),
            "turnover": to_float(last.get("turnover")),
            "status": "cached",
        },
        "series": series,
        "series_meta": {
            "1d": {"count": len(daily), "stale": False, "error": None},
            "1h": {"count": len(hourly), "stale": False, "error": None},
        },
        "ccass": (_CCASS_METRICS if _CCASS_METRICS is not None else load_ccass_metrics()).get(normalized),
    }
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "Futu OpenD real K-line cache",
        "entry": entry,
    }


def build_hk_shards(codes: list[str], resume: bool = False, workers: int = 1, progress_every: int = 1) -> None:
    global _CCASS_METRICS
    _CCASS_METRICS = load_ccass_metrics()
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    jobs = []
    for raw in codes:
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        if not digits:
            failures.append({"code": str(raw), "error": "invalid code"})
            continue
        code = str(int(digits)).zfill(5)
        target = SHARD_DIR / f"{code}.json"
        if resume and target.exists() and target.stat().st_size > 500:
            continue
        jobs.append((code, target))

    def build_one(code: str, target: Path):
        payload = hk_entry(code)
        target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return payload

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {pool.submit(build_one, code, target): code for code, target in jobs}
        for index, future in enumerate(as_completed(future_map), 1):
            code = future_map[future]
            try:
                payload = future.result()
                counts = payload["entry"]["series_meta"]
                if index == 1 or index == len(jobs) or index % max(1, progress_every) == 0:
                    print(f"[kbar-shard] {index}/{len(jobs)} {code} daily={counts['1d']['count']} hourly={counts['1h']['count']}", flush=True)
            except Exception as exc:
                failures.append({"code": code, "error": str(exc)})
                print(f"[kbar-shard] {index}/{len(jobs)} {code} FAIL {exc}", file=sys.stderr, flush=True)
    index_payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "Futu OpenD real K-line cache",
        "available": sorted(path.stem for path in SHARD_DIR.glob("*.json") if path.name != "index.json"),
        "failures": failures,
    }
    (SHARD_DIR / "index.json").write_text(json.dumps(index_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Kbar shards ready={len(index_payload['available'])} failed={len(failures)}", flush=True)


def main():
    universe = build_universe()
    existing = load_json(OUT, {})
    existing_symbols = existing.get("symbols", {}) if isinstance(existing, dict) else {}
    quote_map, errors = fetch_quotes([item["symbol"] for item in universe])

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "Longbridge core + daily signal K-line cache",
        "periods": list(PERIOD_COUNTS.keys()),
        "supported_intervals": ["3m", "3m_flip", "6m", "6m_flip", "1d", "1d_flip"],
        "symbols": {},
        "errors": errors,
    }

    for preset in universe:
        symbol = preset["symbol"]
        previous = existing_symbols.get(symbol, {}) if isinstance(existing_symbols, dict) else {}
        entry = {
            "symbol": symbol,
            "label": preset["label"],
            "market": preset["market"],
            "aliases": preset["aliases"],
            "quote": quote_map.get(symbol) or previous.get("quote"),
            "series": {},
            "series_meta": {},
        }
        previous_series = previous.get("series", {}) if isinstance(previous, dict) else {}

        for period, count in PERIOD_COUNTS.items():
            stale = False
            error_text = None
            try:
                series = fetch_series(symbol, period, count)
                if not series:
                    raise RuntimeError("empty series")
            except Exception as exc:
                series = previous_series.get(period, [])
                stale = True
                error_text = str(exc)
                payload["errors"].append({"symbol": symbol, "period": period, "error": error_text})
            entry["series"][period] = series
            entry["series_meta"][period] = {
                "count": len(series),
                "stale": stale,
                "error": error_text,
            }

        payload["symbols"][symbol] = entry

    missing_daily = [symbol for symbol, entry in payload["symbols"].items() if not entry.get("series", {}).get("1d")]
    payload["daily_chart_ready"] = {
        "ready": len(missing_daily) == 0,
        "symbols": len(payload["symbols"]),
        "missing": missing_daily,
    }
    if missing_daily:
        payload["errors"].append({"scope": "daily_chart", "symbols": missing_daily, "error": "1d year-chart data unavailable"})
        print(f"WARN: {len(missing_daily)} Kbar symbols have no 1d year chart: {', '.join(missing_daily)}", file=sys.stderr)

    attach_ccass(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} with {len(payload['symbols'])} symbols")

def main_daily_only():
    payload = load_json(OUT, {})
    symbols = payload.get("symbols", {}) if isinstance(payload, dict) else {}
    total = len(symbols)
    for idx, (symbol, entry) in enumerate(symbols.items(), 1):
        rows = entry.get("series", {}).get("1d", []) if entry.get("series", {}).get("1d") else []
        if not rows and symbol.endswith(".HK"):
            rows = fetch_futu_daily(symbol, 260)
        if not rows:
            try:
                rows = fetch_series(symbol, "1d", 260)
            except Exception:
                rows = []
        if rows:
            entry.setdefault("series", {})["1d"] = rows
            entry.setdefault("series_meta", {})["1d"] = {"count": len(rows), "stale": False, "error": None}
        print(f"[daily-futu] {idx}/{total} {symbol} rows={len(entry.get('series', {}).get('1d', []))}", flush=True)
    payload["supported_intervals"] = ["3m", "3m_flip", "6m", "6m_flip", "1d", "1d_flip"]
    missing = [symbol for symbol, entry in symbols.items() if not entry.get("series", {}).get("1d")]
    payload["daily_chart_ready"] = {"ready": not missing, "symbols": len(symbols), "missing": missing}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote daily series for {total} cached symbols", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="Build Kbar caches from real market sources")
    parser.add_argument("--ccass-only", action="store_true")
    parser.add_argument("--daily-only", action="store_true")
    parser.add_argument("--symbols", help="Comma-separated HK codes to write as lazy-load shards")
    parser.add_argument("--all-hk", action="store_true", help="Build every code in data/stock_universe.json")
    parser.add_argument("--resume", action="store_true", help="Skip existing non-empty shard files")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent Futu requests for shard builds")
    parser.add_argument("--progress-every", type=int, default=1, help="Print one success line per N completed shards")
    args = parser.parse_args()
    if args.symbols or args.all_hk:
        if args.all_hk:
            universe = load_json(ROOT / "data" / "stock_universe.json", {})
            codes = universe.get("codes", []) if isinstance(universe, dict) else []
        else:
            codes = [item.strip() for item in args.symbols.split(",") if item.strip()]
        build_hk_shards(codes, resume=args.resume, workers=args.workers, progress_every=args.progress_every)
    elif args.ccass_only:
        payload = load_json(OUT, {})
        attach_ccass(payload)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Updated CCASS metrics in {OUT}")
    elif args.daily_only:
        main_daily_only()
    else:
        main()
    if _FUTU_CTX is not None:
        _FUTU_CTX.close()
