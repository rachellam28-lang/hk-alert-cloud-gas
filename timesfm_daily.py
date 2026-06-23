"""TimesFM Daily Forecast — Predict broker concentration trends for high-conc stocks.

Outputs:
  1. data/timesfm.json — structured forecast data for dashboard
  2. Markdown table to stdout — for Telegram cron delivery

Usage:
    python timesfm_daily.py [--horizon 5] [--top 15] [--min-days 25]
"""
import argparse, sqlite3, json, sys, os
import numpy as np

DB_PATH = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\ccass\ccass.db"
OUTPUT_JSON = r"C:\Users\Administrator\Desktop\automatic\ccass-debug\data\timesfm.json"


def get_ccass_series(stock_code: str, field: str = "broker_top5_pct", min_days: int = 25):
    ALLOWED_FIELDS = {"broker_top5_pct", "top5_pct", "total_pct", "adj_hhi",
                      "futu_pct", "a00005_pct", "adjusted_float", "num_participants",
                      "top10_pct", "top_broker_pct"}
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Illegal field: {field}. Allowed: {sorted(ALLOWED_FIELDS)}")
    db = sqlite3.connect(DB_PATH)
    cur = db.execute(f"""
        SELECT trade_date, {field}
        FROM ccass_daily
        WHERE stock_code = ? AND {field} IS NOT NULL
        ORDER BY trade_date
    """, (stock_code,))
    rows = list(cur)
    if len(rows) < min_days:
        return None, None
    dates = [r[0] for r in rows]
    values = np.array([r[1] for r in rows], dtype=np.float32)
    return dates, values


def forecast_timesfm(values, horizon=5):
    from timesfm import TimesFM_2p5_200M_torch, ForecastConfig

    tfm = TimesFM_2p5_200M_torch.from_pretrained(
        "google/timesfm-2.5-200m-pytorch",
    )
    cfg = ForecastConfig(max_context=len(values), max_horizon=horizon)
    tfm.compile(cfg)

    forecast_input = values.astype(np.float32).reshape(1, -1)
    point_forecast, quantile_forecast = tfm.forecast(
        horizon,
        [forecast_input[0]],
    )
    return point_forecast[0], quantile_forecast


def get_top_stocks(db, limit=15, min_days=25):
    """Get stocks with high concentration AND recent movement (not static 99% zombies)."""
    cur = db.execute("""
        WITH latest AS (
            SELECT stock_code, broker_top5_pct, trade_date,
                   ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) as rn
            FROM ccass_daily
            WHERE broker_top5_pct IS NOT NULL
        ),
        stats AS (
            SELECT stock_code,
                   COUNT(DISTINCT trade_date) as days,
                   MAX(broker_top5_pct) as max_conc,
                   MIN(broker_top5_pct) as min_conc
            FROM ccass_daily
            WHERE broker_top5_pct IS NOT NULL
            GROUP BY stock_code
            HAVING COUNT(DISTINCT trade_date) >= ?
        )
        SELECT l.stock_code, s.days, l.broker_top5_pct as latest_conc,
               (s.max_conc - s.min_conc) as conc_range
        FROM latest l
        JOIN stats s ON l.stock_code = s.stock_code
        WHERE l.rn = 1
          AND l.broker_top5_pct BETWEEN 55 AND 95  -- dynamic range, exclude pegged
          AND (s.max_conc - s.min_conc) >= 3        -- at least 3pp movement
        ORDER BY l.broker_top5_pct DESC
        LIMIT ?
    """, (min_days, limit))
    rows = list(cur)
    # Return (code, days, latest_conc) — same shape as before
    return [(r[0], r[1], r[2]) for r in rows]


def get_stock_name(db, code):
    cur = db.execute(
        "SELECT stock_name FROM stock_universe WHERE stock_code = ?", (code,)
    )
    r = cur.fetchone()
    return r[0] if r else code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-days", type=int, default=25)
    parser.add_argument("--field", default="broker_top5_pct")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    db = sqlite3.connect(DB_PATH)
    latest_date = db.execute("SELECT MAX(trade_date) FROM ccass_daily").fetchone()[0]
    top_stocks = get_top_stocks(db, args.top, args.min_days)

    if not top_stocks:
        print("No stocks found with enough data.", file=sys.stderr)
        sys.exit(1)

    print(
        f"🔮 TimesFM Forecast — {len(top_stocks)} stocks, {args.horizon}d horizon"
    )
    print(f"   Data range: {args.min_days}+ days, latest: {latest_date}")
    print()
    print(
        "| Code | Name | Latest | Day+1 | Day+3 | Day+5 | Trend | Signal |"
    )
    print(
        "|------|------|--------|-------|-------|-------|-------|--------|"
    )

    forecasts = []
    errors = 0

    for code, days, latest_conc in top_stocks:
        name = get_stock_name(db, code)
        dates, vals = get_ccass_series(code, args.field, args.min_days)
        if vals is None:
            continue

        try:
            point_fc, quant_fc = forecast_timesfm(vals, args.horizon)
        except Exception as e:
            errors += 1
            print(
                f"| {code} | {name} | {latest_conc:.1f}% | ❌ {str(e)[:40]} | | | | |"
            )
            continue

        pred_end = float(point_fc[-1])
        pred_d1 = float(point_fc[0]) if len(point_fc) > 0 else latest_conc
        pred_d3 = float(point_fc[2]) if len(point_fc) > 2 else pred_end
        delta = pred_end - latest_conc

        if delta > 2.0:
            trend, signal = "⬆️⬆️", "🚨 UP"
        elif delta > 0.5:
            trend, signal = "⬆️", "↗️ rise"
        elif delta < -2.0:
            trend, signal = "⬇️⬇️", "📉 DOWN"
        elif delta < -0.5:
            trend, signal = "⬇️", "↘️ drop"
        else:
            trend, signal = "➡️", "stable"

        print(
            f"| {code} | {name} | {latest_conc:.1f}% | {pred_d1:.1f}% | {pred_d3:.1f}% | {pred_end:.1f}% | {trend} | {signal} |"
        )

        forecasts.append(
            {
                "c": code,
                "n": name,
                "tp": round(float(latest_conc), 1),
                "f1": round(pred_d1, 1),
                "f3": round(pred_d3, 1),
                "f5": round(pred_end, 1),
                "delta": round(float(delta), 1),
                "trend": signal,
                "days": days,
            }
        )

    db.close()

    output = {
        "updated": latest_date,
        "horizon": args.horizon,
        "field": args.field,
        "forecasts": forecasts,
        "errors": errors,
    }
    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    if not args.json_only:
        print()
        print(
            f"📁 JSON: data/timesfm.json ({len(forecasts)} forecasts, {errors} errors)"
        )


if __name__ == "__main__":
    main()
