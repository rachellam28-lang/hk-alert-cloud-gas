#!/usr/bin/env python
"""Tradeable scoring: rate each confluence entry as BUY / WATCH / AVOID.

Scoring factors:
  - Pattern (春江鴨=avoid, 雙向=strong, 追落後=watch)
  - Price level (高位配/溢價=strong, 低價配=caution)
  - Signal density (more signals = more confirmation)
  - Direction (up=positive, neutral=neutral)
  - Proximity (T+0~3 signals are fresher)
"""
import json, os, sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SCRIPT_DIR)  # parent of scripts/
CONF_PATH = os.path.join(PROJ, "data", "confluence.json")
SCORE_PATH = os.path.join(PROJ, "data", "tradeable.json")


def score_confluence(conf: list[dict]) -> list[dict]:
    """Score each confluence entry and return ranked tradeable list."""
    scored = []
    for c in conf:
        score = 35  # lower base — must earn points
        reasons = []

        pattern = c.get("pattern", "")
        pre = c.get("pre_count", 0)
        post = c.get("post_count", 0)
        price_lvl = c.get("price_level", "")
        direction = c.get("direction", "")
        discount = c.get("discount_pct")
        first_post = c.get("first_post_days")

        # --- Pattern scoring ---
        if pattern == "frontrun":
            score -= 30
            reasons.append("🦆春江鴨:訊號行先→派貨")
            if pre >= 5:
                score -= 15
                reasons.append(f"前訊號密集({pre})→強烈回避")
        elif pattern == "dual":
            score += 25
            reasons.append("💎雙向:前後確認")
            if pre >= 3 and post >= 5:
                score += 15
                reasons.append(f"超強雙向({pre}+{post})")
            elif pre >= 2 and post >= 2:
                score += 8
        elif pattern == "catalyst":
            score += 12
            reasons.append("🚀追落後:公告催化")
            if post >= 5:
                score += 12
                reasons.append(f"後訊號密集({post})")
            elif post >= 3:
                score += 5

        # --- Price level ---
        if price_lvl == "high":
            score += 15
            reasons.append("高位配/溢價")
        elif price_lvl == "low":
            score -= 10
            reasons.append("低價配/折讓")
            if discount is not None and discount > 20:
                score -= 5
                reasons.append(f"大幅折讓{discount}%")

        # --- Direction ---
        if direction == "up":
            score += 5
        elif direction == "down":
            score -= 15
            reasons.append("不利方向")

        # --- Timing proximity ---
        if first_post is not None and first_post <= 2:
            score += 8
            reasons.append(f"T+{first_post}即爆")
        elif first_post is not None and first_post <= 5:
            score += 3

        # --- Signal count bonus ---
        total = pre + post
        if total >= 10:
            score += 8
        elif total >= 5:
            score += 3

        # Clamp
        score = max(0, min(100, score))

        # --- Label ---
        if score >= 70:
            label = "🔥 規則高分"
            label_class = "strong-buy"
        elif score >= 50:
            label = "📈 留意"
            label_class = "buy"
        elif score >= 35:
            label = "👀 觀察"
            label_class = "watch"
        elif score >= 15:
            label = "⚠️ 小心"
            label_class = "caution"
        else:
            label = "🛑 回避"
            label_class = "avoid"

        entry = dict(c)
        entry["score"] = score
        entry["label"] = label
        entry["label_class"] = label_class
        entry["reasons"] = reasons
        entry["data_kind"] = "derived_rule_score"
        entry["is_observed"] = False
        entry["score_method"] = "fixed confluence heuristic v1"
        scored.append(entry)

    # Sort by score descending
    scored.sort(key=lambda x: -x["score"])
    return scored


def print_tradeable(scored: list[dict], top_n: int = 20):
    """Print tradeable summary."""
    print(f"\n{'='*60}")
    print(f"  🎯 規則評分 — Top {min(top_n, len(scored))}")
    print(f"{'='*60}")
    for i, s in enumerate(scored[:top_n]):
        label = s["label"]
        code = s.get("code", "?")
        name = s.get("name", "?")[:18]
        atype = s.get("typeLabel", "?")
        pl = s.get("price_level", "") or "-"
        pre = s.get("pre_count", 0)
        post = s.get("post_count", 0)
        disc = f" {s.get('discount_pct')}%" if s.get("discount_pct") is not None else ""
        reasons = " | ".join(s.get("reasons", [])[:3])
        print(f"  {label:16s} {code} {name:18s} {atype} {pl}{disc} 前×{pre}後×{post}")
        if reasons:
            print(f"  {'':16s} {reasons}")
    print()

    # Summary stats
    buys = [s for s in scored if s["score"] >= 55]
    watches = [s for s in scored if 40 <= s["score"] < 55]
    avoids = [s for s in scored if s["score"] < 40]
    print(f"  🔥 STRONG BUY: {len([s for s in buys if s['score']>=70])}")
    print(f"  📈 BUY: {len([s for s in buys if s['score']<70])}")
    print(f"  👀 WATCH: {len(watches)}")
    print(f"  ⚠️/🛑 AVOID: {len(avoids)}")
    print(f"  Total: {len(scored)}")


if __name__ == "__main__":
    with open(CONF_PATH, encoding="utf-8") as f:
        conf = json.load(f)
    scored = score_confluence(conf)
    print_tradeable(scored, top_n=25)

    with open(SCORE_PATH, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(scored)} to data/tradeable.json")
