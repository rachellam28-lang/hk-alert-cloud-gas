"""Daily price fallback via Longbridge quote.

Futu OpenD is the richer source, but it is a local gateway and can be down.
This script updates the core price fields from Longbridge so dashboard prices
do not freeze when Futu is unavailable.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
PRICES = ROOT / "data" / "stock_prices.json"
HOLDINGS = ROOT / "holdings.json"
DATA_HOLDINGS = ROOT / "data" / "holdings.json"
CCASS_JSON = ROOT / "ccass.json"
SUSPENDED = ROOT / "data" / "suspended_stocks.json"


def load_token() -> str:
    token = os.environ.get("LONGBRIDGE_ACCESS_TOKEN")
    if token:
        return token
    for path in [ROOT / ".env", Path.home() / "Desktop" / "automatic" / "holdings-debug" / ".env"]:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("LONGBRIDGE_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    return token
    raise RuntimeError("LONGBRIDGE_ACCESS_TOKEN not found")


def longbridge_cli() -> str | None:
    configured = os.environ.get("LONGBRIDGE_CLI")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("longbridge")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        exe = Path(local) / "Programs" / "longbridge" / "longbridge.exe"
        if exe.exists():
            return str(exe)
    return None


def lb_cli_quote(symbols: list[str]) -> list[dict]:
    exe = longbridge_cli()
    if not exe:
        raise RuntimeError("Longbridge CLI not found")
    try:
        proc = subprocess.run(
            [exe, "quote", *symbols, "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(os.environ.get("LONGBRIDGE_QUOTE_TIMEOUT_SECONDS", "45")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Longbridge CLI quote timeout after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Longbridge CLI quote failed").strip())
    return json.loads(proc.stdout.strip() or "[]")


def lb_mcp(tool: str, args: dict) -> list[dict] | dict:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "-X",
                "POST",
                "https://mcp.longbridge.com",
                "-H",
                "Content-Type: application/json",
                "-H",
                "Accept: application/json, text/event-stream",
                "-H",
                "Authorization: Bearer " + load_token(),
                "-d",
                json.dumps(body),
            ],
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("LONGBRIDGE_QUOTE_TIMEOUT_SECONDS", "45")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Longbridge MCP {tool} timeout after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "Longbridge MCP failed").strip())
    raw = proc.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    res = json.loads(raw)
    if "error" in res:
        raise RuntimeError(res["error"].get("message", str(res["error"])))
    content = res.get("result", {}).get("content", [])
    if not content:
        return []
    return json.loads(content[0]["text"])


def lb_quote(symbols: list[str]) -> list[dict]:
    try:
        return lb_cli_quote(symbols)
    except Exception as cli_exc:
        print(f"  Longbridge CLI quote unavailable: {cli_exc}; trying MCP token", file=sys.stderr)
    data = lb_mcp("quote", {"symbols": symbols})
    return data if isinstance(data, list) else data.get("items", data.get("lists", []))


def to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    prices = json.loads(PRICES.read_text(encoding="utf-8"))
    codes = sorted(k for k in prices.keys() if str(k).isdigit() and len(str(k)) == 5)
    print(f"Daily Longbridge price fallback for {len(codes)} stocks...")

    updated = 0
    suspended: dict[str, str] = {}
    latest_ts = None
    run_ts = datetime.now(timezone.utc).isoformat()
    trade_date = datetime.now().astimezone().strftime("%Y-%m-%d")
    batch_size = int(os.environ.get("LONGBRIDGE_QUOTE_BATCH_SIZE", "100"))

    for i in range(0, len(codes), batch_size):
        batch_codes = codes[i : i + batch_size]
        symbols = [f"{code}.HK" for code in batch_codes]
        try:
            items = lb_quote(symbols)
        except Exception as exc:
            print(f"  batch {i // batch_size + 1} failed: {exc}", file=sys.stderr)
            # Preserve existing prices on transient batch failure. Do not mark the
            # whole batch as suspended; that creates false suspended signals.
            continue

        seen: set[str] = set()
        for item in items:
            symbol = str(item.get("symbol") or "")
            code = symbol.replace(".HK", "").zfill(5)
            if code not in prices:
                continue
            seen.add(code)
            entry = prices.get(code, {})
            changed = False
            lp = to_float(item.get("last_done") or item.get("last"))
            prev = to_float(item.get("prev_close"))
            vol = to_float(item.get("volume"))
            turnover = to_float(item.get("turnover"))
            if lp and lp > 0 and entry.get("lp") != round(lp, 3):
                entry["lp"] = round(lp, 3)
                changed = True
            if prev and prev > 0:
                entry["prev_close"] = round(prev, 3)
                chg = round((lp / prev - 1) * 100, 2) if lp else None
                if chg is not None:
                    entry["chg"] = chg
                changed = True
            if vol is not None:
                entry["vol"] = int(vol)
                changed = True
            if turnover is not None:
                entry["turnover"] = round(turnover, 2)
                changed = True
            if entry.get("lp") and entry.get("hi52") and entry.get("lo52") and entry["hi52"] > entry["lo52"]:
                entry["p52"] = round((entry["lp"] - entry["lo52"]) / (entry["hi52"] - entry["lo52"]) * 100, 1)
            if entry.get("lp") and entry.get("py") and entry["py"] > 0:
                entry["py_pct"] = round((entry["lp"] - entry["py"]) / entry["py"] * 100, 2)
            entry["price_source"] = "longbridge:cli" if "last" in item else "longbridge:mcp"
            ts = item.get("timestamp") or item.get("updated")
            entry["lp_time"] = trade_date
            entry["price_updated_at"] = ts or run_ts
            latest_ts = max(latest_ts or entry["price_updated_at"], entry["price_updated_at"])
            if changed:
                prices[code] = entry
                updated += 1

        for code in batch_codes:
            if code not in seen:
                suspended.setdefault(code, "longbridge_missing_quote")

        print(f"  {min(i + batch_size, len(codes))}/{len(codes)} updated={updated}")
        time.sleep(0.2)

    prices["_meta"] = {
        "source": "longbridge:quote",
        "updated_at": latest_ts or datetime.now(timezone.utc).isoformat(),
        "updated_count": updated,
    }
    atomic_write_json(PRICES, prices)
    atomic_write_json(SUSPENDED, suspended)

    if HOLDINGS.exists():
        holdings = json.loads(HOLDINGS.read_text(encoding="utf-8"))
        for stock in holdings.get("stocks", []):
            code = stock.get("c")
            entry = prices.get(code, {})
            for key in ["lp", "lp_time", "vol", "chg", "p52", "py_pct", "prev_close", "turnover"]:
                if entry.get(key) is not None:
                    stock[key] = entry[key]
            if entry.get("price_source"):
                stock["price_source"] = entry["price_source"]
            if entry.get("price_updated_at"):
                stock["price_updated_at"] = entry["price_updated_at"]
        atomic_write_json(HOLDINGS, holdings)
        atomic_write_json(DATA_HOLDINGS, holdings)
        if CCASS_JSON.exists():
            ccass = json.loads(CCASS_JSON.read_text(encoding="utf-8"))
            ccass["stocks"] = holdings.get("stocks", [])
            for key in ["updated", "stock_count", "coverage", "coverage_total", "coverage_pct", "is_complete"]:
                if key in holdings:
                    ccass[key] = holdings[key]
            atomic_write_json(CCASS_JSON, ccass)

    print(f"Done Longbridge fallback: updated={updated}, suspended={len(suspended)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
