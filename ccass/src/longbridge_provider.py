"""Longbridge MCP provider for HOLDINGS data — drop-in replacement for HKEX scraper.

Provides scrape_stock() with the SAME return shape as HOLDINGSScraper.scrape_stock()
so scrape_one.py can switch between providers via HOLDINGS_PROVIDER env var.

Maps Longbridge broker_holding_detail fields to HOLDINGSSnapshot / holdings format:
  parti_number -> participant_id
  name         -> participant_name
  shares.value -> shares (int)
  ratio.value  -> pct_of_issued (float)
"""

import json, os, sys, time, logging
from datetime import date
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ALLOWED_MCP_HOSTS = {"mcp.longbridge.com", "mcp.longbridge.global", "localhost", "127.0.0.1"}
_raw = os.environ.get("LONGBRIDGE_MCP_URL", "https://mcp.longbridge.com/agent")
from urllib.parse import urlparse as _urlparse
_parsed = _urlparse(_raw)
if _parsed.hostname not in ALLOWED_MCP_HOSTS:
    raise RuntimeError(
        f"LONGBRIDGE_MCP_URL hostname {_parsed.hostname!r} not in allowlist: {ALLOWED_MCP_HOSTS}"
    )
BASE = _raw
MAX_RETRIES = int(os.environ.get("LONGBRIDGE_MCP_MAX_RETRIES", "2"))
RETRY_DELAY = float(os.environ.get("LONGBRIDGE_MCP_RETRY_DELAY_SECONDS", "3.0"))
MCP_TIMEOUT_SECONDS = float(os.environ.get("LONGBRIDGE_MCP_TIMEOUT_SECONDS", "30"))

# --- Token loading ---

def _load_token() -> str:
    """Read LONGBRIDGE_ACCESS_TOKEN from .env in project root."""
    # Try environment first
    token = os.environ.get("LONGBRIDGE_ACCESS_TOKEN")
    if token:
        return token

    # Walk up to find .env
    env_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.expanduser("~/Desktop/automatic/holdings-debug/.env"),
    ]
    for p in env_paths:
        p = os.path.normpath(p)
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LONGBRIDGE_ACCESS_TOKEN="):
                        return line.split("=", 1)[1]
    raise RuntimeError("LONGBRIDGE_ACCESS_TOKEN not found in env or .env files")


# --- MCP client ---

class LongbridgeMCPClient:
    """Lightweight JSON-RPC MCP client for Longbridge."""

    def __init__(self):
        self.token = _load_token()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token,
        }
        self._initialized = False

    def _call(self, method: str, params: dict | None = None) -> dict:
        """Make a JSON-RPC call to the Longbridge MCP endpoint."""
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params:
            body["params"] = params

        for attempt in range(MAX_RETRIES):
            try:
                r = requests.post(BASE, headers=self.headers, json=body, timeout=MCP_TIMEOUT_SECONDS)
                if r.status_code == 401:
                    logger.warning("Longbridge token expired (401), reloading...")
                    self.token = _load_token()
                    self.headers["Authorization"] = "Bearer " + self.token
                    continue
                raw = r.text.strip()
                if raw.startswith("data: "):
                    raw = raw[6:]
                data = json.loads(raw)

                if "error" in data:
                    err_msg = data["error"].get("message", str(data["error"]))
                    if "rate" in err_msg.lower() or "429" in err_msg:
                        delay = RETRY_DELAY * (2 ** attempt)
                        logger.warning("Rate limited, retrying in %.1fs", delay)
                        time.sleep(delay)
                        continue
                    raise RuntimeError(f"MCP error: {err_msg}")

                return data
            except (requests.RequestException, json.JSONDecodeError) as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY * (2 ** attempt)
                    logger.warning("MCP call failed: %s, retrying in %.1fs", e, delay)
                    time.sleep(delay)
                else:
                    raise RuntimeError(f"MCP call failed after {MAX_RETRIES} attempts: {e}")

    def initialize(self):
        """Send initialize + initialized notification."""
        if self._initialized:
            return
        # initialize
        self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "holdings-scanner", "version": "1.0"},
        })
        # initialized notification
        body = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            requests.post(BASE, headers=self.headers, json=body, timeout=5)
        except requests.RequestException:
            logger.debug("Longbridge initialized notification failed", exc_info=True)
        self._initialized = True

    def broker_holding_detail(self, symbol: str, query_date: str | None = None) -> dict:
        """Call broker_holding_detail MCP tool. Returns raw API response."""
        self.initialize()
        args = {"symbol": symbol}
        if query_date:
            args["date"] = query_date
        result = self._call("tools/call", {
            "name": "broker_holding_detail",
            "arguments": args,
        })
        try:
            content = result.get("result", {}).get("content", [])
            if not content:
                return {"list": [], "updated_at": ""}
            return json.loads(content[0]["text"])
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Unexpected MCP response: {e}")


# Module-level client singleton (lazy init)
_client: LongbridgeMCPClient | None = None


def _get_client() -> LongbridgeMCPClient:
    global _client
    if _client is None:
        _client = LongbridgeMCPClient()
    return _client


def _stock_code_to_symbol(stock_code: str) -> str:
    """Convert '00700' or '700' to '00700.HK'."""
    code = stock_code.strip().zfill(5)
    return f"{code}.HK"


def _parse_holding(item: dict) -> dict:
    """Convert Longbridge holding item to HOLDINGS format."""
    shares_val = item.get("shares", {})
    ratio_val = item.get("ratio", {})

    shares_str = (shares_val.get("value") or "0").replace(",", "")
    ratio_str = (ratio_val.get("value") or "0").replace(",", "")

    try:
        shares = int(float(shares_str)) if shares_str else 0
    except (ValueError, TypeError):
        shares = 0

    try:
        pct = float(ratio_str) if ratio_str else 0.0
    except (ValueError, TypeError):
        pct = 0.0

    return {
        "participant_id": item.get("parti_number", ""),
        "participant_name": item.get("name", ""),
        "shares": shares,
        "pct_of_issued": pct,
    }


def scrape_stock(stock_code: str, query_date: date) -> Optional["HOLDINGSSnapshot"]:
    """Scrape a single stock via Longbridge API.

    Returns HOLDINGSSnapshot (same shape as HOLDINGSScraper.scrape_stock) or None.
    """
    from src.scraper import HOLDINGSSnapshot  # local import to avoid circular

    symbol = _stock_code_to_symbol(stock_code)
    date_str = query_date.strftime("%Y-%m-%d") if query_date else None

    try:
        client = _get_client()
        data = client.broker_holding_detail(symbol, date_str)
    except Exception as e:
        logger.error("Longbridge API failed for %s: %s", symbol, e)
        return None

    items = data.get("list", [])
    if not items:
        logger.warning("Longbridge returned empty holdings for %s", symbol)
        return None

    holdings = [_parse_holding(item) for item in items]
    # Filter out entries with zero shares (can happen with empty values)
    holdings = [h for h in holdings if h["shares"] > 0]

    if not holdings:
        return None

    total_shares = sum(h["shares"] for h in holdings)
    total_pct = sum(h["pct_of_issued"] for h in holdings)
    num_participants = len(holdings)

    return HOLDINGSSnapshot(
        stock_code=stock_code,
        trade_date=date_str,
        total_shares=total_shares,
        total_pct=round(total_pct, 2) if total_pct else None,
        num_participants=num_participants,
        holdings=holdings,
    )
