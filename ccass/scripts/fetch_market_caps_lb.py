"""Get stock market caps from Longbridge static_info."""
import subprocess, json, os, sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def get_token():
    for p in [
        Path.home() / "Desktop" / "automatic" / "ccass-debug" / ".env",
        DATA_DIR.parent / ".env",
    ]:
        if p.exists():
            with open(p) as f:
                for line in f:
                    if "LONGBRIDGE_ACCESS_TOKEN" in line:
                        return line.strip().split("=", 1)[1]
    return ""

def lb_mcp(method, args=None):
    token = get_token()
    if not token:
        return {}
    auth = "Authorization: Bearer " + token
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": method, "arguments": args or {}}}
    r = subprocess.run([
        "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-H", auth,
        "-d", json.dumps(body),
    ], capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    res = json.loads(raw)
    c = res.get("result", {}).get("content", [])
    return json.loads(c[0]["text"]) if c else {}


def get_market_caps(symbols: list[str]) -> dict:
    """
    Fetch market caps for a list of symbols from Longbridge.
    symbols: list of 'XXXXX.HK' format strings.
    Returns {symbol: {"name": ..., "market_cap": ..., "exchange": ...}}
    """
    result = {}
    # static_info can take up to 50 symbols at once
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i+50]
        data = lb_mcp("static_info", {"symbols": batch})
        if not data:
            continue
        items = data.get("items", data.get("lists", []))
        for item in items:
            sym = item.get("symbol", "")
            result[sym] = {
                "name_cn": item.get("name_cn", ""),
                "name_en": item.get("name_en", ""),
                "market_cap": item.get("market_cap", ""),
                "exchange": item.get("exchange", ""),
            }
        print(f"  batch {i//50 + 1}: {len(items)} stocks")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", help="Symbols to fetch (e.g. 00700.HK)")
    parser.add_argument("--from-file", help="File with one symbol per line")
    parser.add_argument("--from-json", help="JSON file with symbol keys")
    parser.add_argument("--output", default=str(DATA_DIR / "market_caps.json"))
    args = parser.parse_args()

    symbols = []
    if args.symbols:
        symbols = args.symbols
    elif args.from_file:
        with open(args.from_file) as f:
            symbols = [l.strip() for l in f if l.strip()]
    elif args.from_json:
        with open(args.from_json) as f:
            data = json.load(f)
            # Try to extract stock codes
            if isinstance(data, list):
                symbols = [s.get("symbol", s.get("code", "")) for s in data if isinstance(s, dict)]
            elif isinstance(data, dict):
                symbols = list(data.keys())

    if not symbols:
        # Default: get top watched stocks from Longbridge
        print("Fetching top watched stocks first...")
        watchlist = lb_mcp("rank_list", {"key": "ib_watchlist_heat-hk", "market": "HK", "size": 30})
        items = watchlist.get("lists", watchlist.get("items", []))
        symbols = [(i.get("code", "") + ".HK") for i in items if i.get("code")]
        print(f"  Got {len(symbols)} symbols from watchlist")

    # Clean symbols
    cleaned = []
    for s in symbols:
        s = s.strip()
        if not s:
            continue
        if not s.endswith(".HK"):
            s = s + ".HK"
        cleaned.append(s)

    print(f"Fetching market caps for {len(cleaned)} stocks...")
    caps = get_market_caps(cleaned)

    # Save
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(caps, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(caps)} stocks to {out_path}")

    # Show sample
    for sym, info in list(caps.items())[:5]:
        mc = info.get("market_cap", "")
        name = info.get("name_cn", info.get("name_en", ""))
        print(f"  {sym} {name}: market_cap={mc}")
