#!/usr/bin/env python
"""Build confluence.json: cross-reference announcements.json with history.json.

Dual-direction timing analysis:
  - Pre-signals: within 30 days BEFORE announcement (春江鴨 — insider front-running)
  - Post-signals: within 30 days AFTER announcement (追落後 — market reaction)

Patterns:
  🦆 春江鴨: heavy pre-signals, few post → announcement = distribution
  🚀 追落後: few pre, heavy post → genuine catalyst
  💎 雙向: heavy both sides → strongest momentum

Run: python build_confluence.py [--no-alert]
"""
import json, os, sys
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ = SCRIPT_DIR
DATA = os.path.join(PROJ, "data")

ANN_PATH = os.path.join(DATA, "announcements.json")
HIST_PATH = os.path.join(DATA, "history.json")
CONF_PATH = os.path.join(DATA, "confluence.json")

SIGNAL_WINDOW_DAYS = 30


def classify_pattern(pre_count: int, post_count: int) -> str:
    """Classify confluence pattern based on pre/post signal distribution."""
    total = pre_count + post_count
    if total == 0:
        return "none"
    if pre_count >= 3 and post_count <= 1:
        return "frontrun"  # 🦆 春江鴨
    if post_count >= 3 and pre_count <= 1:
        return "catalyst"  # 🚀 追落後
    if pre_count >= 2 and post_count >= 2:
        return "dual"      # 💎 雙向爆發
    if pre_count > post_count:
        return "frontrun"
    return "catalyst"


def build() -> list[dict]:
    if not os.path.exists(ANN_PATH):
        print("[confluence] announcements.json not found, skip")
        return []

    with open(ANN_PATH, "r") as f:
        announcements = json.load(f)
    with open(HIST_PATH, "r") as f:
        history_data = json.load(f)

    # Build hist: code -> list of (type, date_str)
    hist: dict[str, list[tuple[str, str]]] = {}
    for day in history_data.get("days", []):
        for alert in day.get("alerts", []):
            code = str(alert.get("code", "")).zfill(5)
            signal = alert.get("signal", "")
            if isinstance(signal, dict):
                sig_type = signal.get("type", "?")
                sig_date = signal.get("date", "") or day.get("date", "")
            else:
                sig_type = str(signal)
                sig_date = day.get("date", "")
            if code not in hist:
                hist[code] = []
            hist[code].append((sig_type, sig_date))

    confluence = []
    for a in announcements:
        code = str(a.get("code", "")).zfill(5)
        ann_date_str = a.get("date", "")
        if code not in hist or not ann_date_str:
            continue

        try:
            ann_date = datetime.strptime(ann_date_str, "%Y-%m-%d")
        except ValueError:
            continue

        pre_cutoff = ann_date - timedelta(days=SIGNAL_WINDOW_DAYS)
        post_cutoff = ann_date + timedelta(days=SIGNAL_WINDOW_DAYS)

        pre_signals: list[tuple[str, str, int]] = []   # (type, date, days_before)
        post_signals: list[tuple[str, str, int]] = []  # (type, date, days_after)

        for sig_type, sig_date_str in hist[code]:
            try:
                sig_date = datetime.strptime(sig_date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if sig_date >= pre_cutoff and sig_date < ann_date:
                days_before = (ann_date - sig_date).days
                pre_signals.append((sig_type, sig_date_str, days_before))
            elif sig_date >= ann_date and sig_date <= post_cutoff:
                days_after = (sig_date - ann_date).days
                post_signals.append((sig_type, sig_date_str, days_after))

        total = len(pre_signals) + len(post_signals)
        if total == 0:
            continue

        # Deduplicate types per direction
        def dedup_types(signals, key_fn):
            seen = {}
            for s in signals:
                t = s[0]
                v = key_fn(s)
                if t not in seen or v < key_fn(seen[t]):
                    seen[t] = s
            return seen

        pre_dedup = dedup_types(pre_signals, lambda s: s[2])
        post_dedup = dedup_types(post_signals, lambda s: s[2])

        pre_types = sorted(pre_dedup.keys())
        post_types = sorted(post_dedup.keys())
        first_pre_days = min((s[2] for s in pre_dedup.values()), default=None)
        first_post_days = min((s[2] for s in post_dedup.values()), default=None)

        pattern = classify_pattern(len(pre_signals), len(post_signals))

        a_copy = dict(a)
        a_copy["signal_count"] = total
        a_copy["pre_count"] = len(pre_signals)
        a_copy["post_count"] = len(post_signals)
        a_copy["pre_types"] = pre_types
        a_copy["post_types"] = post_types
        a_copy["signal_types_summary"] = sorted(set(pre_types + post_types))
        a_copy["first_pre_days"] = first_pre_days
        a_copy["first_post_days"] = first_post_days
        a_copy["pattern"] = pattern
        a_copy.pop("signal_types", None)
        confluence.append(a_copy)

    # Sort: frontrun (春江鴨) first (most actionable for avoidance),
    # then dual (最強), then catalyst
    pattern_order = {"frontrun": 0, "dual": 1, "catalyst": 2}
    price_order = {"high": 0, "neutral": 1, "low": 2}
    confluence.sort(key=lambda x: (
        pattern_order.get(x.get("pattern", ""), 3),
        price_order.get(x.get("price_level", ""), 3),
        -x.get("signal_count", 0),
    ))

    with open(CONF_PATH, "w") as f:
        json.dump(confluence, f, ensure_ascii=False, indent=2)
    print(f"[confluence] saved {len(confluence)} records (dual-direction, {SIGNAL_WINDOW_DAYS}d window)")

    # Score tradeability
    try:
        from scripts.score_tradeable import score_confluence as _score
        scored = _score(confluence)
        # Merge scores back into confluence for dashboard
        score_map = {}
        for s in scored:
            key = (s.get("code"), s.get("date"), s.get("type", ""))
            score_map[key] = {"score": s["score"], "label": s["label"], "label_class": s["label_class"]}
        for c in confluence:
            key = (c.get("code"), c.get("date"), c.get("type", ""))
            if key in score_map:
                c.update(score_map[key])
    except Exception as exc:
        print(f"[confluence] scoring failed: {exc}")

    return confluence


def format_alert(confluence: list[dict]) -> str | None:
    """Format Telegram alert."""
    frontrun = [c for c in confluence if c.get("pattern") == "frontrun"]
    dual = [c for c in confluence if c.get("pattern") == "dual"
            and c.get("signal_count", 0) >= 3]
    catalyst_fire = [c for c in confluence if c.get("pattern") == "catalyst"
                     and c.get("price_level") == "high"]

    if not frontrun and not dual and not catalyst_fire:
        return None

    lines = ["<b>🎯 Confluence 雙向分析</b>", ""]
    if frontrun:
        lines.append("<b>🦆 春江鴨警報 (訊號行先，公告=散貨)：</b>")
        for c in frontrun[:5]:
            lines.append(
                f"  {c['code']} {c.get('name','')} | {c.get('typeLabel','')}"
                f" | 前×{c['pre_count']} 後×{c['post_count']}"
                f" | 前: {', '.join(c.get('pre_types',[])[:2])}"
            )
    if dual:
        lines.append(f"\n<b>💎 雙向爆發 (前後都有)：</b>")
        for c in dual[:5]:
            lines.append(
                f"  {c['code']} {c.get('name','')} | {c.get('typeLabel','')}"
                f" | 前×{c['pre_count']} 後×{c['post_count']}"
            )
    if catalyst_fire:
        lines.append(f"\n<b>🔥 高位配 + 追落後：</b>")
        for c in catalyst_fire[:5]:
            disc = c.get("discount_pct", "?")
            fdays = c.get("first_post_days", "?")
            lines.append(
                f"  {c['code']} {c.get('name','')} | disc={disc}%"
                f" | 後×{c['post_count']} T+{fdays}"
            )
    return "\n".join(lines)


def print_summary(confluence: list[dict]) -> None:
    pattern_emoji = {"frontrun": "🦆", "dual": "💎", "catalyst": "🚀"}
    pattern_label = {"frontrun": "春江鴨(訊號行先)", "dual": "雙向爆發", "catalyst": "追落後"}

    for pat in ["frontrun", "dual", "catalyst"]:
        items = [c for c in confluence if c.get("pattern") == pat]
        if not items:
            continue
        print(f"\n=== {pattern_emoji[pat]} {pattern_label[pat]} ({len(items)}) ===")
        for c in items[:8]:
            name = c.get("name", "?")[:20]
            pl = c.get("price_level", "")
            lvl = {"high": "🔥", "neutral": "⚪", "low": "🔻"}.get(pl, "")
            pre = c.get("pre_count", 0)
            post = c.get("post_count", 0)
            pre_t = ", ".join(c.get("pre_types", [])[:2])
            post_t = ", ".join(c.get("post_types", [])[:2])
            print(f"  {lvl} {c['code']} {name} | {c.get('typeLabel','?')} | 前×{pre} 後×{post}")
            if pre:
                print(f"    前訊號: {pre_t}")
            if post:
                print(f"    後訊號: {post_t}")

    print(f"\nTotal: {len(confluence)} confluence stocks")


if __name__ == "__main__":
    c = build()
    print_summary(c)
    alert = format_alert(c)
    if alert and "--no-alert" not in sys.argv:
        try:
            sys.path.insert(0, os.path.join(PROJ, "scanner"))
            from hk_cloud_scanner import send_telegram_message
            send_telegram_message(alert)
            print("\n[confluence] alert sent")
        except Exception as exc:
            print(f"[confluence] alert failed: {exc}")
