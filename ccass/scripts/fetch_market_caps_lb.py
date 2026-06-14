"""Fetch stock market caps from Longbridge static_info + quote."""
import subprocess, json, os, sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "market_caps.json"

def get_token():
    for p in [
        Path.home() / "Desktop" / "automatic" / "holdings-debug" / ".env",
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
    auth = "Bearer " + token
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": method, "arguments": args or {}}}
    r = subprocess.run([
        "curl", "-s", "-X", "POST", "https://mcp.longbridge.com",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream",
        "-H", "Authorization: " + auth,
        "-d", json.dumps(body),
    ], capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    if raw.startswith("data: "):
        raw = raw[6:]
    res = json.loads(raw)
    c = res.get("result", {}).get("content", [])
    return json.loads(c[0]["text"]) if c else {}


def get_market_caps(symbols):
    """
    Fetch market caps by combining static_info (total_shares) + quote (last_done).
    symbols: list of 'XXXXX.HK' strings.
    Returns {symbol: {name_cn, total_shares, last_done, market_cap_hkd}}
    """
    result = {}

    # Step 1: static_info for all symbols (batch 50)
    info_map = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i+50]
        data = lb_mcp("static_info", {"symbols": batch})
        items = data if isinstance(data, list) else data.get("items", data.get("lists", []))
        for item in items:
            sym = item.get("symbol", "")
            info_map[sym] = {
                "name_cn": item.get("name_cn", ""),
                "name_en": item.get("name_en", ""),
                "total_shares": float(item.get("total_shares", 0) or 0),
                "exchange": item.get("exchange", ""),
            }
        print("  static_info batch {}: {} stocks".format(i//50 + 1, len(items)))

    # Step 2: quote for prices (batch 500)
    all_syms = list(info_map.keys())
    for i in range(0, len(all_syms), 500):
        batch = all_syms[i:i+500]
        data = lb_mcp("quote", {"symbols": batch})
        items = data if isinstance(data, list) else data.get("items", data.get("lists", []))
        for item in items:
            sym = item.get("symbol", "")
            if sym in info_map:
                last_done = float(item.get("last_done", 0) or 0)
                info_map[sym]["last_done"] = last_done
        print("  quote batch {}: {} stocks".format(i//500 + 1, len(items)))

    # Step 3: compute market cap
    for sym, info in info_map.items():
        shares = info.get("total_shares", 0)
        price = info.get("last_done", 0)
        mc = shares * price if shares and price else 0
        result[sym] = {
            "name_cn": info["name_cn"],
            "name_en": info["name_en"],
            "total_shares": shares,
            "last_done": price,
            "market_cap_hkd": mc,
            "exchange": info["exchange"],
        }

    return result


def fmt_mc(value):
    """Format market cap in HK style 萬/億."""
    if value >= 1e8:
        return "{:.2f}億".format(value / 1e8)
    elif value >= 1e4:
        return "{:.1f}萬".format(value / 1e4)
    else:
        return str(int(value))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--output", default=str(DATA_DIR / "market_caps.json"))
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else []

    if not symbols:
        print("Fetching top watched stocks first...")
        watchlist = lb_mcp("rank_list", {"key": "ib_watchlist_heat-hk", "market": "HK", "size": 30})
        items = watchlist.get("lists", watchlist.get("items", []))
        symbols = [(i.get("code", "") + ".HK") for i in items if i.get("code")]
        print("  Got {} symbols from watchlist".format(len(symbols)))

    cleaned = []
    for s in symbols:
        s = s.strip()
        if not s:
            continue
        if not s.endswith(".HK"):
            s = s + ".HK"
        cleaned.append(s)

    print("Fetching market caps for {} stocks...".format(len(cleaned)))
    caps = get_market_caps(cleaned)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(caps, f, ensure_ascii=False, indent=2)

    # Also update the cache format used by the daily runner:
    # [{"stock_code": "00001", "market_cap": 123.45}, ...]
    cache_rows = []
    for sym, info in caps.items():
        stock_code = sym.replace(".HK", "").zfill(5)
        cache_rows.append({
            "stock_code": stock_code,
            "market_cap": round(float(info.get("market_cap_hkd") or 0) / 1e8, 2) if info.get("market_cap_hkd") else None,
        })
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSaved {} stocks to {}".format(len(caps), out_path))
    print("Saved cache to {}".format(CACHE_PATH))

    # Show top 10 by market cap
    ranked = sorted(caps.items(), key=lambda x: x[1].get("market_cap_hkd", 0), reverse=True)
    print("\nTop 10 by market cap:")
    for sym, info in ranked[:10]:
        mc = fmt_mc(info["market_cap_hkd"])
        name = info["name_cn"] or info["name_en"]
        print("  {} {}  ${}  MC: {}".format(
            sym.replace(".HK",""), name[:20], info["last_done"], mc))
