"""
dopamine_refresh.py — Refresh dopamine market state (v5 Futu 100%) → market.json

1. Runs ccass/src/dopamine.py v5 (Futu 港股通 snapshots) to get fresh dopamine
2. Updates market.json with current dopamine, HSI price, and timestamp
3. Merges dopamine.json into market.json for dashboard consumption
"""
from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import sys
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

# Project root (where market.json lives)
PROJECT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT / "data"
MARKET_KEYS = ["hsi", "dow", "spx", "dxy", "vix", "hsi_pe", "hsi_m2", "spx_pe", "spx_m2", "fear_greed"]
LB_QUOTE_SYMBOLS = {
    "hsi": "HSI.HK",
    "dow": ".DJI.US",
    "spx": ".SPX.US",
    "vix": ".VIX.US",
}
PE_SOURCES = {
    "hsi_pe": "https://worldperatio.com/area/hong-kong/",
    "spx_pe": "https://worldperatio.com/index/sp-500/",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_longbridge_token() -> str | None:
    token = os.environ.get("LONGBRIDGE_ACCESS_TOKEN")
    if token:
        return token
    for path in [PROJECT / ".env", Path.home() / "Desktop" / "automatic" / "holdings-debug" / ".env"]:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("LONGBRIDGE_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    return token
    return None


def _longbridge_cli() -> str | None:
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


def _lb_cli_quote(symbols: list[str]) -> list[dict]:
    exe = _longbridge_cli()
    if not exe:
        raise RuntimeError("Longbridge CLI not found")
    try:
        proc = subprocess.run(
            [exe, "quote", *symbols, "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(os.environ.get("LONGBRIDGE_MARKET_TIMEOUT_SECONDS", "30")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Longbridge CLI quote timeout after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Longbridge CLI quote failed").strip())
    return json.loads(proc.stdout.strip() or "[]")


def _lb_cli_market_temp(market: str) -> dict:
    exe = _longbridge_cli()
    if not exe:
        raise RuntimeError("Longbridge CLI not found")
    try:
        proc = subprocess.run(
            [exe, "market-temp", market, "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(os.environ.get("LONGBRIDGE_MARKET_TIMEOUT_SECONDS", "30")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Longbridge CLI market-temp timeout after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Longbridge CLI market-temp failed").strip())
    rows = json.loads(proc.stdout.strip() or "[]")
    out: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("field"):
            out[str(row["field"]).lower()] = row.get("value")
    return out


def _lb_quote(symbols: list[str]) -> list[dict]:
    try:
        return _lb_cli_quote(symbols)
    except Exception as cli_exc:
        print(f"[dopamine_refresh] Longbridge CLI unavailable: {cli_exc}; trying MCP token", file=sys.stderr)
    token = _load_longbridge_token()
    if not token:
        raise RuntimeError("LONGBRIDGE_ACCESS_TOKEN not found")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "quote", "arguments": {"symbols": symbols}},
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
                "Authorization: Bearer " + token,
                "-d",
                json.dumps(body),
            ],
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("LONGBRIDGE_MARKET_TIMEOUT_SECONDS", "30")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Longbridge quote timeout after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "Longbridge quote failed").strip())
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


def _pct(last_done, prev_close) -> float | None:
    try:
        last_v = float(last_done)
        prev_v = float(prev_close)
    except (TypeError, ValueError):
        return None
    if not prev_v:
        return None
    return round((last_v / prev_v - 1) * 100, 2)


def _to_float(value) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _eval_vix(value: float | None) -> dict:
    if value is None:
        return {"label": "未知", "color": "gray"}
    if value >= 30:
        return {"label": "恐慌", "color": "red"}
    if value >= 22:
        return {"label": "偏緊張", "color": "orange"}
    if value <= 12:
        return {"label": "低波動", "color": "green"}
    return {"label": "正常", "color": "neutral"}


def _eval_fear_greed(value: float | None) -> dict:
    if value is None:
        return {"label": "未知", "color": "gray"}
    if value < 25:
        return {"label": "極恐懼", "color": "green"}
    if value < 45:
        return {"label": "恐懼", "color": "green"}
    if value < 55:
        return {"label": "中性", "color": "neutral"}
    if value < 75:
        return {"label": "貪婪", "color": "orange"}
    return {"label": "極貪婪", "color": "red"}


def _eval_pe(value: float | None, range1: list[float] | None, range2: list[float] | None = None) -> dict:
    if value is None:
        return {"label": "未知", "color": "gray"}
    if range2 and len(range2) == 2:
        lo2, hi2 = range2
        if value >= hi2:
            return {"label": "貴", "color": "red"}
        if value <= lo2:
            return {"label": "便宜", "color": "green"}
    if range1 and len(range1) == 2:
        lo1, hi1 = range1
        if value > hi1:
            return {"label": "偏貴", "color": "orange"}
        if value < lo1:
            return {"label": "偏平", "color": "green"}
    return {"label": "合理", "color": "gray"}


def _range_from_text(text: str) -> list[float] | None:
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(nums) >= 2:
        return [round(float(nums[0]), 2), round(float(nums[1]), 2)]
    return None


def _fetch_worldperatio_pe(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=float(os.environ.get("MARKET_PE_TIMEOUT_SECONDS", "20"))) as res:
        text = res.read().decode("utf-8", "replace")

    compact = " ".join(unescape(text).split())
    current = re.search(
        r"The estimated .*?P/E\) Ratio.*? is <b>([0-9]+(?:\.[0-9]+)?)</b>, calculated on <b>([^<]+)</b>",
        compact,
        flags=re.I,
    )
    if not current:
        current = re.search(
            r"([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}).{0,120}?P/E Ratio:\s*<b[^>]*>([0-9]+(?:\.[0-9]+)?)</b>",
            compact,
            flags=re.I,
        )
        if current:
            source_date, value = current.group(1), float(current.group(2))
        else:
            raise RuntimeError(f"could not parse current P/E from {url}")
    else:
        value, source_date = float(current.group(1)), current.group(2).strip()

    avg_block = re.search(
        r"5Y Average:\s*<b[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*</b>.*?"
        r"1 Std Dev range:\s*<b[^>]*>\s*\[([^\]]+)\]\s*</b>.*?"
        r"2 Std Dev range:\s*<b[^>]*>\s*\[([^\]]+)\]\s*</b>",
        compact,
        flags=re.I,
    )
    avg_match = avg_block.group(1) if avg_block else None
    one_range = avg_block.group(2) if avg_block else None
    two_range = avg_block.group(3) if avg_block else None
    avg5y = round(float(avg_match), 2) if avg_match else None
    range1 = _range_from_text(one_range) if one_range else None
    range2 = _range_from_text(two_range) if two_range else None
    return {
        "value": round(value, 2),
        "avg5y_mid": avg5y,
        "avg5y_range": range1,
        "std2_range": range2,
        "source_date": source_date,
        "source_url": url,
    }


def _refresh_market_metadata(market: dict) -> None:
    stale_keys = [key for key in MARKET_KEYS if isinstance(market.get(key), dict) and market[key].get("stale")]
    lb_fields = [
        key for key in MARKET_KEYS
        if isinstance(market.get(key), dict)
        and not market[key].get("stale")
        and str(market[key].get("source") or "").startswith("longbridge:")
    ]
    pe_fields = [
        key for key in MARKET_KEYS
        if isinstance(market.get(key), dict)
        and not market[key].get("stale")
        and market[key].get("source") == "worldperatio"
    ]
    market["market_partial"] = bool(stale_keys)
    market["market_stale_fields"] = stale_keys
    market["market_longbridge_fields"] = lb_fields
    market["market_pe_fields"] = pe_fields
    lb_count = len(lb_fields)
    pe_count = len(pe_fields)
    parts = []
    if lb_count:
        parts.append(f"Longbridge refreshed {lb_count} market fields")
    if pe_count:
        parts.append(f"WorldPERatio refreshed {pe_count} P/E fields")
    if stale_keys:
        parts.append("stale fields remain: " + ", ".join(stale_keys))
    elif parts:
        parts.append("all market card fields are fresh")
    if parts:
        market["market_note"] = "; ".join(parts) + "."


def _mark_existing_market_stale(market: dict, max_age_hours: int = 18) -> None:
    updated = _parse_dt(market.get("updated_at"))
    if not updated:
        return
    now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if (now - updated).total_seconds() < max_age_hours * 3600:
        return
    for key in MARKET_KEYS:
        if isinstance(market.get(key), dict):
            market[key]["stale"] = True


def _apply_longbridge_market_fallback(market: dict) -> bool:
    """Refresh market fields that Longbridge can supply without fabricating unavailable data."""
    refreshed: list[str] = []
    now_ts = datetime.now(timezone.utc).isoformat()
    quotes = _lb_quote(list(LB_QUOTE_SYMBOLS.values()))
    by_symbol = {q.get("symbol"): q for q in quotes if isinstance(q, dict)}

    for key, symbol in LB_QUOTE_SYMBOLS.items():
        item = by_symbol.get(symbol)
        if not item:
            continue
        last_done = _to_float(item.get("last_done") or item.get("last"))
        prev_close = _to_float(item.get("prev_close"))
        if last_done is None or last_done <= 0:
            continue
        change = _to_float(item.get("change_value"))
        change_pct = _to_float(item.get("change_percentage"))
        if change is None and prev_close:
            change = round(last_done - prev_close, 2)
        if change_pct is None:
            change_pct = _pct(last_done, prev_close)
        ts = item.get("timestamp") or item.get("updated") or now_ts
        market[key] = {
            "value": round(last_done, 2),
            "change": round(change, 2) if change is not None else None,
            "changePct": round(change_pct, 2) if change_pct is not None else None,
            "stale": False,
            "source": "longbridge:quote",
            "updated": ts,
        }
        if key == "vix":
            market[key]["eval"] = _eval_vix(last_done)
        refreshed.append(key)

    try:
        temp = _lb_cli_market_temp("US")
        value = _to_float(temp.get("temperature"))
        if value is not None:
            prev = _to_float((market.get("fear_greed") or {}).get("value"))
            market["fear_greed"] = {
                "value": round(value, 1),
                "changePct": round(value - prev, 2) if prev is not None else None,
                "stale": False,
                "source": "longbridge:market-temp",
                "updated": now_ts,
                "eval": _eval_fear_greed(value),
                "sentiment": _to_float(temp.get("sentiment")),
                "valuation": _to_float(temp.get("valuation")),
                "description": temp.get("description"),
            }
            refreshed.append("fear_greed")
    except Exception as exc:
        print(f"[dopamine_refresh] Longbridge market-temp unavailable: {exc}", file=sys.stderr)

    if not refreshed:
        return False

    market["updated_at"] = max(
        [str((market.get(key) or {}).get("updated") or now_ts) for key in refreshed] or [now_ts]
    )
    market["market_longbridge_fields"] = refreshed
    _refresh_market_metadata(market)
    return True


def _apply_worldperatio_pe_fallback(market: dict) -> bool:
    refreshed: list[str] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for key, url in PE_SOURCES.items():
        try:
            data = _fetch_worldperatio_pe(url)
        except Exception as exc:
            print(f"[dopamine_refresh] WorldPERatio {key} unavailable: {exc}", file=sys.stderr)
            continue
        market[key] = {
            "value": data["value"],
            "change": None,
            "changePct": None,
            "avg5y_mid": data.get("avg5y_mid"),
            "avg5y_range": data.get("avg5y_range"),
            "std2_range": data.get("std2_range"),
            "eval": _eval_pe(data.get("value"), data.get("avg5y_range"), data.get("std2_range")),
            "stale": False,
            "source": "worldperatio",
            "source_url": data.get("source_url"),
            "source_date": data.get("source_date"),
            "updated": fetched_at,
        }
        refreshed.append(key)
    if refreshed:
        market["market_pe_fields"] = refreshed
        market["updated_at"] = max(str(market.get("updated_at") or fetched_at), fetched_at)
        _refresh_market_metadata(market)
    return bool(refreshed)

def _load_fallback_dopamine(err: str | None = None) -> dict:
    """Load last known dopamine snapshot or a neutral placeholder."""
    for f in [PROJECT / "ccass" / "data" / "dopamine.json", PROJECT / "data" / "dopamine.json"]:
        if f.exists():
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            print(f"[dopamine_refresh] loaded fallback dopamine from {f}", file=sys.stderr)
            return data
    return {"dopamine": 50.0, "level": "normal", "error": err or "dopamine unavailable"}


def _run_dopamine_subprocess(timeout_s: int | None = None) -> tuple[dict, Path]:
    """Run dopamine computation in a separate process so Futu hangs cannot block daily refresh."""
    if timeout_s is None:
        timeout_s = int(os.environ.get("DOPAMINE_FUTU_TIMEOUT", "120"))
    helper = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {repr(str(PROJECT / 'ccass' / 'src'))})
from dopamine import compute_dopamine, save_dopamine
result = compute_dopamine()
path = save_dopamine(result)
print(json.dumps({{'result': result, 'path': str(path)}}))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", helper],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg"):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        stdout, stderr = proc.communicate()
        raise TimeoutError(f"dopamine subprocess timed out after {timeout_s}s")

    if proc.returncode != 0:
        raise RuntimeError((stderr or stdout or "dopamine subprocess failed").strip())
    stdout = (stdout or "").strip()
    if not stdout:
        raise RuntimeError("dopamine subprocess returned no payload")
    payload = json.loads(stdout.splitlines()[-1])
    result = payload.get("result") or {}
    path = Path(payload.get("path") or (PROJECT / "data" / "dopamine.json"))
    return result, path


# ── Step 1: Run v5 Futu dopamine ──
print("[dopamine_refresh] Running v5 Futu dopamine...", file=sys.stderr)
try:
    dopa_result, dopa_path = _run_dopamine_subprocess()
    dopa_fresh = True
    print(f"[dopamine_refresh] v5 dopamine={dopa_result.get('dopamine', 50.0):.1f} saved to {dopa_path}", file=sys.stderr)
except Exception as e:
    print(f"[dopamine_refresh] v5 dopamine FAILED: {e}", file=sys.stderr)
    dopa_fresh = False
    dopa_result = _load_fallback_dopamine(str(e))

# ── Step 2: Load existing market.json ──
market_path = PROJECT / "market.json"
if market_path.exists():
    with open(market_path, encoding="utf-8") as f:
        market = json.load(f)
    print(f"[dopamine_refresh] Loaded existing market.json (updated: {market.get('updated_at','?')})", file=sys.stderr)
else:
    market = {}
    print("[dopamine_refresh] No existing market.json, creating new", file=sys.stderr)

# ── Step 3: Update market.json ──
_mark_existing_market_stale(market)
lb_market_fresh = False
try:
    lb_market_fresh = _apply_longbridge_market_fallback(market)
    if lb_market_fresh:
        print(
            "[dopamine_refresh] Longbridge fallback refreshed %d market fields"
            % len(market.get("market_longbridge_fields", [])),
            file=sys.stderr,
        )
except Exception as e:
    print(f"[dopamine_refresh] Longbridge market fallback failed: {e}", file=sys.stderr)

pe_market_fresh = False
try:
    pe_market_fresh = _apply_worldperatio_pe_fallback(market)
    if pe_market_fresh:
        print(
            "[dopamine_refresh] WorldPERatio refreshed %d P/E fields"
            % len(market.get("market_pe_fields", [])),
            file=sys.stderr,
        )
except Exception as e:
    print(f"[dopamine_refresh] WorldPERatio P/E fallback failed: {e}", file=sys.stderr)

# Inject dopamine data
market["dopamine"] = {
    "score": dopa_result.get("dopamine", 50.0),
    "level": dopa_result.get("level", "normal"),
    "level_emoji": dopa_result.get("level_emoji", ""),
    "level_desc": dopa_result.get("level_desc", ""),
    "version": dopa_result.get("version", 5),
    "source": dopa_result.get("source", "futu"),
    "updated": datetime.now(timezone.utc).isoformat() if dopa_fresh else market.get("dopamine", {}).get("updated", market.get("updated_at")),
    "stale": not dopa_fresh,
}
if "components" in dopa_result:
    c = dopa_result["components"]
    market["dopamine"]["breadth_pct"] = c.get("breadth_pct")
    market["dopamine"]["stocks_sampled"] = c.get("stocks_sampled")

# Update timestamp
if dopa_fresh:
    market["updated_at"] = datetime.now(timezone.utc).isoformat()
elif not lb_market_fresh:
    market["updated_at"] = market.get("updated_at") or market.get("dopamine", {}).get("updated")

# ── Step 4: Save market.json ──
DATA_DIR.mkdir(parents=True, exist_ok=True)
data_market_path = DATA_DIR / "market.json"
for path in (market_path, data_market_path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(market, f, ensure_ascii=False, indent=2)
    print(f"[dopamine_refresh] market.json written -> {path} ({path.stat().st_size} bytes)", file=sys.stderr)

# ── Summary ──
print(json.dumps({
    "dopamine": market.get("dopamine", {}).get("score"),
    "level": market.get("dopamine", {}).get("level"),
    "hsi": market.get("hsi", {}).get("value"),
    "hsi_m2": market.get("hsi_m2", {}).get("value"),
    "updated": market["updated_at"],
}, ensure_ascii=False))
