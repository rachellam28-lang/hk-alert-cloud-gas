"""CCASS TimesFM Forecaster — Predict broker concentration trends.

Uses Google's TimesFM (Time Series Foundation Model) to forecast
CCASS broker_top5_pct for early warning of concentration changes.

Usage:
    python ccass_timesfm_forecast.py --stock 00700 --horizon 5
"""
import argparse, sqlite3, json, sys, os
import numpy as np

DB_PATH = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass\ccass.db"

def get_ccass_series(stock_code: str, field: str = "broker_top5_pct", min_days: int = 20):
    """Fetch CCASS time series for a stock."""
    db = sqlite3.connect(DB_PATH)
    cur = db.execute(f"""
        SELECT trade_date, {field}
        FROM ccass_daily
        WHERE stock_code = ? AND trade_date >= '2026-01-01'
        ORDER BY trade_date
    """, (stock_code,))
    rows = [(r[0], r[1]) for r in cur if r[1] is not None]
    if len(rows) < min_days:
        print(f"  ⚠️ Only {len(rows)} data points (need {min_days})")
        return None, None
    dates = [r[0] for r in rows]
    values = np.array([r[1] for r in rows], dtype=np.float32)
    return dates, values

def forecast_timesfm(values: np.ndarray, horizon: int = 5):
    """Run TimesFM v2.5 forecast."""
    from timesfm import TimesFM_2p5_200M_torch, ForecastConfig
    import torch
    
    # Download model first time, then cache
    tfm = TimesFM_2p5_200M_torch.from_pretrained(
        "google/timesfm-2.5-200m-pytorch",
    )
    cfg = ForecastConfig(max_context=len(values), max_horizon=horizon)
    tfm.compile(cfg)
    
    # Prepare input: (batch, time) float32
    forecast_input = values.astype(np.float32).reshape(1, -1)
    
    # Forecast
    point_forecast, _ = tfm.forecast(
        horizon,
        [forecast_input[0]],
    )
    return point_forecast[0]  # (horizon,) numpy array

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", default="00700")
    parser.add_argument("--field", default="broker_top5_pct")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--batch", action="store_true", help="Batch forecast multiple stocks")
    args = parser.parse_args()

    if args.batch:
        # Batch: top 10 high-concentration stocks
        db = sqlite3.connect(DB_PATH)
        cur = db.execute("""
            SELECT stock_code FROM ccass_daily
            WHERE trade_date = (SELECT MAX(trade_date) FROM ccass_daily)
              AND broker_top5_pct > 60
            ORDER BY broker_top5_pct DESC LIMIT 10
        """)
        stocks = [r[0] for r in cur]
        print(f"Batch forecast: {len(stocks)} stocks\n")
        for code in stocks:
            dates, vals = get_ccass_series(code, args.field)
            if vals is None:
                continue
            try:
                pred = forecast_timesfm(vals, args.horizon)
                last = vals[-1]
                pred_end = pred[-1]
                delta = pred_end - last
                direction = "⬆" if delta > 0 else "⬇"
                print(f"{direction} {code}: {last:.1f}% → {pred_end:.1f}% ({delta:+.1f}pp over {args.horizon}d)")
            except Exception as e:
                print(f"  ❌ {code}: {e}")
    else:
        dates, vals = get_ccass_series(args.stock, args.field)
        if vals is None:
            sys.exit(1)
        
        print(f"📊 {args.stock} — {args.field}")
        print(f"   History: {len(vals)} days ({dates[0]} → {dates[-1]})")
        print(f"   Latest: {vals[-1]:.2f}%")
        
        pred = forecast_timesfm(vals, args.horizon)
        print(f"\n🔮 {args.horizon}-day forecast:")
        for i, p in enumerate(pred):
            delta = p - vals[-1]
            print(f"   Day +{i+1}: {p:.2f}% ({delta:+.2f}pp)")

if __name__ == "__main__":
    main()
