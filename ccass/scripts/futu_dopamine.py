"""
富途牛牛人氣數據接入 — Futu OpenD gateway.
散戶最愛平台，關注度/熱度數據比長橋更準。
"""
import json, os, socket, sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env()
HOST = os.environ.get("FUTU_HOST", "127.0.0.1")
PORT = int(os.environ.get("FUTU_PORT", "11111"))


def check_opend_running():
    """Check if FutuOpenD is running and accessible."""
    try:
        probe = socket.socket()
        probe.settimeout(float(os.environ.get("FUTU_CONNECT_TIMEOUT", "2")))
        probe.connect((HOST, PORT))
        probe.close()
        from futu import OpenQuoteContext
        ctx = OpenQuoteContext(host=HOST, port=PORT)
        ctx.close()
        return True
    except Exception as e:
        print("[futu] OpenD not accessible at {}:{}: {}".format(HOST, PORT, e), file=sys.stderr)
        return False


def get_market_temperature():
    """
    Get Futu market sentiment via API.
    Uses get_market_state + get_plate_list for heat data.
    """
    try:
        from futu import OpenQuoteContext, SubType, KLType
        ctx = OpenQuoteContext(host=HOST, port=PORT)

        # Get HK market state
        ret, data = ctx.get_market_state(["HK.HSI"])
        market_state = "unknown"
        if ret == 0 and not data.empty:
            market_state = str(data.iloc[0].get("market_state", "unknown"))

        # Get stock plate (industry/concept) heat ranking
        ret2, plate_data = ctx.get_plate_list(
            market=1,  # HK
            plate_class=1,  # Industry
        )
        plate_count = len(plate_data) if ret2 == 0 else 0

        ctx.close()

        return {
            "market_state": market_state,
            "plate_count": plate_count,
            "connected": True,
        }
    except Exception as e:
        return {"error": str(e), "connected": False}


def get_hot_stocks(top_n=20):
    """
    Get hot stocks from Futu.
    Uses get_stock_filter (screener) for popularity ranking.
    """
    try:
        from futu import OpenQuoteContext, SortField, SortDir
        ctx = OpenQuoteContext(host=HOST, port=PORT)

        # Use stock screener to get top stocks by turnover/volume
        # Sort by turnover (most active = most popular)
        ret, data = ctx.get_stock_filter(
            market=1,  # HK
            filter_list=[],  # no filter
            sort_field=SortField.TURNOVER,  # by turnover
            sort_dir=SortDir.DESCEND,
            begin=0,
            num=top_n,
        )

        ctx.close()

        if ret != 0:
            return []

        stocks = []
        for _, row in data.iterrows():
            stocks.append({
                "code": str(row.get("code", ""))[-5:].lstrip("0") or str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "last_price": float(row.get("last_price", 0) or 0),
                "change_rate": float(row.get("change_rate", 0) or 0),
                "turnover": float(row.get("turnover", 0) or 0),
                "volume": float(row.get("volume", 0) or 0),
            })

        return stocks

    except Exception as e:
        print("[futu] get_hot_stocks error: {}".format(e), file=sys.stderr)
        return []


def fetch_futu_sentiment():
    """
    Main entry: fetch Futu sentiment data for dopamine system.
    Returns same shape as Longbridge fetch_longbridge_sentiment().
    """
    result = {
        "source": "futu",
        "connected": False,
        "temperature": 50,
        "hot_stocks_count": 0,
        "top_hot": [],
        "error": None,
    }

    if not check_opend_running():
        result["error"] = "FutuOpenD not running"
        return result

    result["connected"] = True

    # Market state
    market = get_market_temperature()
    if market.get("connected"):
        result["market_state"] = market.get("market_state", "unknown")
        result["plate_count"] = market.get("plate_count", 0)

    # Hot stocks
    hot = get_hot_stocks(30)
    result["hot_stocks_count"] = len(hot)
    result["top_hot"] = hot[:10]

    # Temperature: based on hot stock count (proxy)
    if len(hot) >= 30:
        result["temperature"] = 70
    elif len(hot) >= 15:
        result["temperature"] = 55
    else:
        result["temperature"] = 40

    return result


if __name__ == "__main__":
    print("=== 富途牛牛 OpenD 連接測試 ===")

    if not check_opend_running():
        print("\n❌ FutuOpenD 未運行")
        print(f"目前嘗試連接: {HOST}:{PORT}")
        print("請先下載並啟動 FutuOpenD:")
        print("  https://www.futunn.com/en/download/OpenAPI")
        print("\n啟動後再執行此 script")
        sys.exit(1)

    print("✅ FutuOpenD 已連接\n")

    data = fetch_futu_sentiment()
    print(json.dumps(data, ensure_ascii=False, indent=2))

    # Save
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "futu_sentiment.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("\n→ saved to {}".format(out))
