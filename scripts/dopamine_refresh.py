"""
dopamine_refresh.py — Refresh dopamine market state (v5 Futu 100%) → market.json

1. Runs ccass/src/dopamine.py v5 (Futu 港股通 snapshots) to get fresh dopamine
2. Updates market.json with current dopamine, HSI price, and timestamp
3. Merges dopamine.json into market.json for dashboard consumption
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root (where market.json lives)
PROJECT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT / "data"


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
                return line.split("=", 1)[1].strip()
    return None


def _lb_quote(symbols: list[str]) -> list[dict]:
    token = _load_longbridge_token()
    if not token:
        raise RuntimeError("LONGBRIDGE_ACCESS_TOKEN not found")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "quote", "arguments": {"symbols": symbols}},
    }
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
        timeout=30,
        check=False,
    )
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


def _mark_existing_market_stale(market: dict, max_age_hours: int = 18) -> None:
    updated = _parse_dt(market.get("updated_at"))
    if not updated:
        return
    now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if (now - updated).total_seconds() < max_age_hours * 3600:
        return
    for key in ["hsi", "dow", "spx", "dxy", "vix", "hsi_pe", "hsi_m2", "spx_pe", "spx_m2", "fear_greed"]:
        if isinstance(market.get(key), dict):
            market[key]["stale"] = True


def _apply_longbridge_market_fallback(market: dict) -> bool:
    """Refresh market fields that Longbridge can supply without fabricating unavailable data."""
    quotes = _lb_quote(["HSI.HK"])
    by_symbol = {q.get("symbol"): q for q in quotes if isinstance(q, dict)}
    hsi = by_symbol.get("HSI.HK")
    if not hsi:
        return False
    last_done = float(hsi.get("last_done") or 0)
    prev_close = float(hsi.get("prev_close") or 0)
    if not last_done:
        return False
    ts = hsi.get("timestamp") or datetime.now(timezone.utc).isoformat()
    market["hsi"] = {
        "value": last_done,
        "change": round(last_done - prev_close, 2) if prev_close else None,
        "changePct": _pct(last_done, prev_close),
        "stale": False,
        "source": "longbridge:quote",
        "updated": ts,
    }
    market["updated_at"] = ts
    market["market_partial"] = True
    market["market_note"] = "Longbridge refreshed HSI only; other market chips may be stale."
    return True

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
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
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
        print("[dopamine_refresh] Longbridge fallback refreshed HSI quote", file=sys.stderr)
except Exception as e:
    print(f"[dopamine_refresh] Longbridge market fallback failed: {e}", file=sys.stderr)

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
