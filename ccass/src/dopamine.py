"""
多巴胺系統 v5 — 富途 100%，真實散戶交易數據。

Data source: Futu OpenD gateway (127.0.0.1:11111)

Metrics (all from Futu market snapshots of 港股通 stocks):
  1. Market breadth — % of stocks with positive daily change (weight 35%)
  2. Volume enthusiasm — average volume ratio vs normal (weight 25%)
  3. Momentum strength — average absolute change rate (weight 20%)
  4. Turnover heat — average turnover ratio (weight 20%)

Output: dopamine 0-100
  0-30  → 低多巴胺（凍市+散戶離場）：收緊門檻
  30-60 → 正常
  60-100 → 高多巴胺（熱市+散戶湧入）：放鬆門檻

Threshold mapping:
  spike_threshold_pct = 8.0 / 5.0 / 3.0  (低/正常/高)
  consecutive_days     = 5   / 3   / 2    (低/正常/高)
"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROOT = Path(__file__).resolve().parent.parent.parent

# ── Futu connection ──
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
_FUTU_HOST = os.environ.get("FUTU_HOST", "127.0.0.1")
_FUTU_PORT = int(os.environ.get("FUTU_PORT", "11111"))


def _get_quote_ctx():
    """Get a fresh OpenQuoteContext. Caller must close it."""
    probe = socket.socket()
    probe.settimeout(float(os.environ.get("FUTU_CONNECT_TIMEOUT", "2")))
    try:
        probe.connect((_FUTU_HOST, _FUTU_PORT))
    finally:
        probe.close()
    from futu import OpenQuoteContext
    return OpenQuoteContext(_FUTU_HOST, _FUTU_PORT)


# ═══════════════════════════════════════════════════════════════════
# Data fetching
# ═══════════════════════════════════════════════════════════════════

def fetch_ganggu_stocks() -> list[str]:
    """Get all 港股通 stock codes."""
    q = _get_quote_ctx()
    try:
        from futu import RET_OK, Market, Plate
        ret, data = q.get_plate_stock("HK.GangGuTong")
        if ret != RET_OK:
            print(f"[dopamine] get_plate_stock failed: {data}", file=sys.stderr)
            return []
        return data["code"].tolist()
    finally:
        q.close()


def fetch_market_snapshots(codes: list[str]) -> dict:
    """
    Fetch market snapshots in batches (max 200 per call).
    Returns aggregated metrics dict.
    """
    from futu import RET_OK

    BATCH = 200
    all_change_rates = []
    all_volume_ratios = []
    all_turnover_ratios = []
    up_count = 0
    down_count = 0
    flat_count = 0
    total = 0
    total_turnover = 0.0
    total_volume = 0.0

    q = _get_quote_ctx()
    data = {}
    try:
        for i in range(0, len(codes), BATCH):
            batch = codes[i:i + BATCH]
            ret, snap = q.get_market_snapshot(batch)
            if ret != RET_OK:
                print(f"[dopamine] snapshot batch {i} failed: {snap}", file=sys.stderr)
                continue

            total += len(snap)

            # Change rate: compute from last_price / prev_close_price
            if "last_price" in snap.columns and "prev_close_price" in snap.columns:
                lp = snap["last_price"]
                pc = snap["prev_close_price"]
                mask = pc > 0
                changes = np.where(mask, (lp - pc) / pc * 100, 0.0)
                all_change_rates.extend(changes.tolist())
                up_count += int((changes > 0).sum())
                down_count += int((changes < 0).sum())
                flat_count += int((changes == 0).sum())

            # Volume ratio
            if "volume_ratio" in snap.columns:
                vr = snap["volume_ratio"].dropna().values
                all_volume_ratios.extend(vr.tolist())

            # Turnover
            if "turnover" in snap.columns:
                to = snap["turnover"].dropna().values
                all_turnover_ratios.extend(to.tolist())
                total_turnover += float(to.sum())

            # Volume
            if "volume" in snap.columns:
                total_volume += float(snap["volume"].dropna().sum())

            # Market date from update_time
            if "update_time" in snap.columns:
                ut = snap["update_time"].dropna()
                if len(ut) > 0:
                    data["market_date"] = str(ut.iloc[0])[:10]

    finally:
        q.close()

    if total == 0:
        return {"error": "No snapshot data"}

    breadth_pct = up_count / total * 100 if total > 0 else 50
    avg_change = float(np.mean(all_change_rates)) if all_change_rates else 0.0
    abs_change = float(np.mean(np.abs(all_change_rates))) if all_change_rates else 0.0
    avg_vr = float(np.mean(all_volume_ratios)) if all_volume_ratios else 0.5
    avg_turnover = float(np.mean(all_turnover_ratios)) if all_turnover_ratios else 0.0
    median_vr = float(np.median(all_volume_ratios)) if all_volume_ratios else 0.5

    # High activity threshold: volume ratio > 1.5
    high_vr_count = int((np.array(all_volume_ratios) > 1.5).sum()) if all_volume_ratios else 0

    # Significant movers: |change| > 3%
    sig_movers = int((np.abs(all_change_rates) > 3).sum()) if all_change_rates else 0

    return {
        "stocks_sampled": total,
        "breadth_pct": round(breadth_pct, 1),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "avg_change_pct": round(avg_change, 2),
        "abs_avg_change_pct": round(abs_change, 2),
        "avg_volume_ratio": round(avg_vr, 3),
        "median_volume_ratio": round(median_vr, 3),
        "avg_turnover": round(avg_turnover, 2),
        "total_turnover": round(total_turnover, 2),
        "high_volume_ratio_count": high_vr_count,
        "significant_movers_count": sig_movers,
    }


# ═══════════════════════════════════════════════════════════════════
# Score computation
# ═══════════════════════════════════════════════════════════════════

def compute_dopamine_score(data: dict) -> tuple[float, dict]:
    """
    Convert market snapshot data to 0-100 dopamine score.

    Four components:
      1. Breadth (35%): % of stocks positive today
      2. Volume enthusiasm (25%): avg volume ratio vs baseline 1.0
      3. Momentum (20%): avg absolute change rate
      4. Turnover heat (20%): normalized from avg turnover
    """
    if "error" in data:
        return 50.0, {"error": data["error"]}

    # ── 1. Breadth score (35%) ──
    breadth = data["breadth_pct"]
    if breadth >= 70:
        breadth_score = 80 + min(20, (breadth - 70) / 30 * 20)
    elif breadth >= 55:
        breadth_score = 50 + (breadth - 55) / 15 * 30
    elif breadth >= 40:
        breadth_score = 20 + (breadth - 40) / 15 * 30
    else:
        breadth_score = max(0, breadth / 40 * 20)

    # ── 2. Volume enthusiasm (25%) ──
    vr = data["avg_volume_ratio"]
    if vr >= 1.5:
        vr_score = 80 + min(20, (vr - 1.5) / 1.0 * 20)
    elif vr >= 1.0:
        vr_score = 50 + (vr - 1.0) / 0.5 * 30
    elif vr >= 0.7:
        vr_score = 20 + (vr - 0.7) / 0.3 * 30
    else:
        vr_score = max(0, vr / 0.7 * 20)

    # ── 3. Momentum (20%) ──
    abs_chg = data["abs_avg_change_pct"]
    if abs_chg >= 3.0:
        mom_score = 80 + min(20, (abs_chg - 3.0) / 3.0 * 20)
    elif abs_chg >= 1.5:
        mom_score = 50 + (abs_chg - 1.5) / 1.5 * 30
    elif abs_chg >= 0.5:
        mom_score = 20 + (abs_chg - 0.5) / 1.0 * 30
    else:
        mom_score = max(0, abs_chg / 0.5 * 20)

    # ── 4. Turnover heat (20%) ──
    # Raw avg turnover is usually very large, normalize relative to stock count
    avg_to_per_stock = data["avg_turnover"] if data["avg_turnover"] > 0 else 0
    # Typical range: 0 to billions. Use log scale.
    if avg_to_per_stock > 0:
        log_to = np.log10(avg_to_per_stock)
        # log10(1e6)=6 -> score 20, log10(1e8)=8 -> score 60, log10(1e9)=9 -> score 90
        turnover_score = max(0, min(100, (log_to - 4) / 5 * 100))
    else:
        turnover_score = 20

    # ── Combined ──
    dopamine = (
        breadth_score * 0.35
        + vr_score * 0.25
        + mom_score * 0.20
        + turnover_score * 0.20
    )

    scores = {
        "breadth_score": round(breadth_score, 1),
        "volume_enthusiasm_score": round(vr_score, 1),
        "momentum_score": round(mom_score, 1),
        "turnover_heat_score": round(turnover_score, 1),
    }

    return round(dopamine, 1), scores


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def compute_dopamine() -> dict:
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": 5,
        "source": "futu",
        "dopamine": 50.0,
        "level": "normal",
        "spike_threshold_pct": 5.0,
        "consecutive_days": 3,
        "components": {},
        "error": None,
    }

    print("[dopamine v5] Fetching 港股通 stock list...", file=sys.stderr)
    codes = fetch_ganggu_stocks()
    if not codes:
        result["error"] = "Failed to fetch stock list from Futu"
        return result
    print(f"[dopamine v5] {len(codes)} stocks, fetching snapshots...", file=sys.stderr)

    data = fetch_market_snapshots(codes)
    if "error" in data:
        result["error"] = data["error"]
        return result

    print(f"[dopamine v5] {data['stocks_sampled']} sampled, computing score...", file=sys.stderr)

    dopamine, scores = compute_dopamine_score(data)

    # Level & thresholds
    if dopamine >= 60:
        level = "high"
        spike_threshold_pct = 3.0
        consecutive_days = 2
        level_emoji = "🔥"
        desc = "熱市+散戶活躍 — 門檻放鬆"
    elif dopamine >= 30:
        level = "normal"
        spike_threshold_pct = 5.0
        consecutive_days = 3
        level_emoji = "⚖️"
        desc = "正常市況 — 標準門檻"
    else:
        level = "low"
        spike_threshold_pct = 8.0
        consecutive_days = 5
        level_emoji = "😴"
        desc = "凍市+散戶離場 — 門檻收緊"

    result.update({
        "dopamine": dopamine,
        "level": level,
        "level_emoji": level_emoji,
        "level_desc": desc,
        "spike_threshold_pct": spike_threshold_pct,
        "consecutive_days": consecutive_days,
        "components": {
            **data,
            **scores,
            "weight_breadth": 35,
            "weight_volume": 25,
            "weight_momentum": 20,
            "weight_turnover": 20,
        },
    })

    return result


def save_dopamine(result: dict) -> Path:
    """Save to JSON file AND holdings.db dopamine_history table."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "dopamine.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Also write to DB
    try:
        import sqlite3
        db_path = DATA_DIR.parent / "holdings.db"
        db = sqlite3.connect(str(db_path))
        c = result.get("components", {})
        db.execute(
            """INSERT INTO dopamine_history
            (date, score, level, breadth_pct, up_count, down_count,
             avg_change_pct, avg_volume_ratio, high_vr_count, sig_movers_count,
             spike_threshold_pct, consecutive_days, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result["date"], result["dopamine"], result["level"],
                c.get("breadth_pct"), c.get("up_count"), c.get("down_count"),
                c.get("avg_change_pct"), c.get("avg_volume_ratio"),
                c.get("high_volume_ratio_count"), c.get("significant_movers_count"),
                result["spike_threshold_pct"], result["consecutive_days"],
                json.dumps(result, ensure_ascii=False),
            ),
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"  [warn] DB write failed: {e}", file=sys.stderr)

    return out


if __name__ == "__main__":
    result = compute_dopamine()
    path = save_dopamine(result)

    d = result["dopamine"]
    lvl = result["level"]
    emoji = result.get("level_emoji", "")
    desc = result.get("level_desc", "")
    spike = result["spike_threshold_pct"]
    cons = result["consecutive_days"]

    print(f"\n{emoji} 多巴胺 v5 (富途100%): {d:.1f} ({lvl})")
    print(f"   {desc}")
    print(f"   spike≥{spike:.1f}% | consecutive≥{cons}d")
    print(f"   → saved to {path}\n")

    c = result["components"]
    print(f"── 富途市場掃描 ({c.get('stocks_sampled', 0)} stocks via 港股通) ──")
    print(f"   漲跌比: {c.get('up_count', 0)}↑ / {c.get('down_count', 0)}↓ / {c.get('flat_count', 0)}─")
    print(f"   廣度:   {c.get('breadth_pct', 0)}%")
    print(f"   平均漲跌幅: {c.get('avg_change_pct', 0):+.2f}% (abs: {c.get('abs_avg_change_pct', 0):.2f}%)")
    print(f"   平均量比:   {c.get('avg_volume_ratio', 0):.2f} (median: {c.get('median_volume_ratio', 0):.2f})")
    print(f"   高量比(>1.5): {c.get('high_volume_ratio_count', 0)}隻")
    print(f"   顯著波動(>3%): {c.get('significant_movers_count', 0)}隻")

    print(f"\n── 評分細項 ──")
    print(f"   廣度分:       {c.get('breadth_score', 0):.1f} (×35%)")
    print(f"   量能分:       {c.get('volume_enthusiasm_score', 0):.1f} (×25%)")
    print(f"   動量分:       {c.get('momentum_score', 0):.1f} (×20%)")
    print(f"   成交熱度分:   {c.get('turnover_heat_score', 0):.1f} (×20%)")
    print(f"   ───────────────────────")
    print(f"   總分:         {d:.1f}")
