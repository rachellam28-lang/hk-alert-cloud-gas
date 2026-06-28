# -*- coding: utf-8 -*-
"""
build_signals.py — Layer 2 PROCESS
===================================
讀 raw 數據 → 統一 events.json + 修正版 signals.json。
純計算層：冇 network call、冇 LLM、秒級完成。

Inputs:
    data/announcements.json  — 累積 HKEX 公告（534 條，NOT corp_scan_result.json！）
    data/alerts.json         — scanner 輸出（兩套 legacy schema）
    holdings.json            — CCASS + 價格主數據
    events.json              — 上次 run 嘅 events（增量 merge）

Outputs:
    events.json              — 統一 schema event store（append + dedup by id）
    data/signals.json        — 前端用，corpTypes 由 announcements.json 正確生成

用法:
    python scripts/build_signals.py
    python scripts/build_signals.py --corp-window 90 --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

# Import from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import (
    make_event, normalize_legacy_alert, validate_event,
    parse_announcement_date, classify_announcement,
)
from issuer_score import issuer_pressure_score

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATHS = {
    "announcements": os.path.join(BASE, "data", "announcements.json"),
    "alerts":        os.path.join(BASE, "data", "alerts.json"),
    "placements":    os.path.join(BASE, "data", "placements_enriched.json"),
    "rights_analysis": os.path.join(BASE, "data", "rights_analysis.json"),
    "holdings":      os.path.join(BASE, "holdings.json"),
    "events":        os.path.join(BASE, "events.json"),
    "signals_out":   os.path.join(BASE, "data", "signals.json"),
}


def load_json(path, default=None):
    if not os.path.exists(path):
        print(f"  ⚠ missing: {path}")
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path, obj):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def build_corp_map(announcements, window_days=90):
    """announcements.json (plain list) → {code: {placement|rights|increase: {date,link,count}}}"""
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    corp_map = {}
    skipped_nodate = 0

    for ann in (announcements or []):
        code = str(ann.get("code", "")).strip().lstrip("0").zfill(5)
        if not code or code == "00000":
            continue

        date = parse_announcement_date(ann.get("date") or ann.get("release_time"))
        if not date:
            skipped_nodate += 1
            continue
        if date < cutoff:
            continue

        ctype = classify_announcement(ann)
        if not ctype:
            continue

        entry = corp_map.setdefault(code, {})
        cur = entry.get(ctype)
        link = ann.get("url") or ann.get("link") or ""
        if cur is None:
            entry[ctype] = {"date": date, "link": link, "count": 1}
        else:
            cur["count"] += 1
            if date > cur["date"]:
                cur["date"], cur["link"] = date, link

    if skipped_nodate:
        print(f"  ⚠ {skipped_nodate} announcements skipped (unparseable date)")
    return corp_map


def normalize_alerts(alerts_doc):
    """data/alerts.json → list of normalized events."""
    if not alerts_doc:
        return []
    day = (alerts_doc.get("updated") or datetime.now().strftime("%Y-%m-%d"))[:10]
    events, bad = [], 0
    for a in alerts_doc.get("alerts", []):
        try:
            ev = normalize_legacy_alert(a, day)
            problems = validate_event(ev)
            if problems:
                bad += 1
                print(f"  ⚠ invalid event skipped: {problems} | {str(a)[:80]}")
                continue
            events.append(ev)
        except Exception as exc:
            bad += 1
            print(f"  ⚠ normalize error: {exc} | {str(a)[:80]}")
    if bad:
        print(f"  ⚠ {bad} alerts dropped during normalize")
    return events


def merge_events(existing, new):
    """Dedup by event id. Old outcome (already backfilled) takes priority."""
    by_id = {e["id"]: e for e in (existing or [])}
    added = 0
    for e in new:
        if e["id"] not in by_id:
            by_id[e["id"]] = e
            added += 1
    print(f"  events: {len(by_id)} total, +{added} new")
    return sorted(by_id.values(), key=lambda x: (x["alert_date"], x["code"]))


def build_issuer_map(placements, rights_analysis=None):
    """Build {code: issuer_score_payload}; rights_analysis.json is authoritative when present."""
    issuer_map = {}
    def add_payload(row, prefer_existing_payload=False):
        code = str(row.get("code", "")).strip().lstrip("0").zfill(5)
        if not code or code == "00000":
            return
        date = str(row.get("date_parsed") or row.get("date") or "")[:10]
        if not date:
            return
        cur = issuer_map.get(code)
        payload = row.get("issuer") if prefer_existing_payload and isinstance(row.get("issuer"), dict) else None
        if payload:
            payload = dict(payload)
        else:
            payload = issuer_pressure_score(row)
        payload.update({
            "date": date,
            "category": row.get("category"),
            "method": row.get("method"),
        })
        if cur is None or date > cur.get("date", ""):
            issuer_map[code] = payload

    for p in placements or []:
        add_payload(p)
    for r in rights_analysis or []:
        add_payload(r, prefer_existing_payload=True)
    return issuer_map


def build_signals_json(holdings, events, corp_map, issuer_map):
    """Generate frontend signals.json with corpTypes from announcements.json."""
    stocks = holdings.get("stocks", []) if holdings else []

    sig_by_code = {}
    for e in events:
        sig_by_code.setdefault(e["code"], []).append({
            "label": e["signal_type"], "date": e["alert_date"], "category": e["category"]
        })
    for code in sig_by_code:
        sig_by_code[code] = sorted(
            sig_by_code[code], key=lambda s: s["date"], reverse=True
        )[:6]

    groups, with_signals, with_corp = [], 0, 0
    for s in stocks:
        code = str(s.get("c", "")).zfill(5)
        cm = corp_map.get(code, {})
        corp_types = {
            "placement": cm.get("placement", False),
            "rights":    cm.get("rights", False),
            "increase":  cm.get("increase", False),
        }
        hkex_link = next(
            (cm[t]["link"] for t in ("placement", "rights", "increase") if cm.get(t)),
            "",
        )
        sigs = sig_by_code.get(code, [])
        if sigs:
            with_signals += 1
        if any(corp_types.values()):
            with_corp += 1
        groups.append({
            "code": code,
            "name": s.get("n", ""),
            "latestPrice": s.get("lp"),
            "signals": sigs,
            "corpTypes": corp_types,
            "issuer": issuer_map.get(code),
            "hkexLink": hkex_link,
        })

    print(f"  signals.json: {len(groups)} stocks, {with_signals} with signals, "
          f"{with_corp} with corp actions  ← corpTypes fix 生效指標")

    return {
        "ok": True,
        "schema_v": 1,
        "groups": groups,
        "updatedAt": datetime.now().isoformat(),
        "totalStocks": len(groups),
        "totalWithSignals": with_signals,
        "totalWithCorp": with_corp,
    }


def save_price_snapshot(holdings):
    """Save today's price snapshot to raw/prices_YYYYMMDD.json.
    Fields: lp (close), vol, hi52, lo52 — stored per code for zombie detection + future OHLC needs."""
    today = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(BASE, "raw", f"prices_{today}.json")
    
    stocks = holdings.get("stocks", [])
    out = {}
    for s in stocks:
        code = str(s.get("c", "")).zfill(5)
        out[code] = {
            "close": s.get("lp"),
            "vol": s.get("vol"),
            "hi52": s.get("hi52"),
            "lo52": s.get("lo52"),
        }
    
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  price snapshot: {len(out)} stocks → {out_path}")
    return out_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp-window", type=int, default=90,
                    help="corpTypes 計幾多日內嘅公告（default 90）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("[1/4] load inputs")
    announcements = load_json(PATHS["announcements"], default=[])
    alerts_doc = load_json(PATHS["alerts"], default={})
    placements = load_json(PATHS["placements"], default=[])
    rights_analysis = load_json(PATHS["rights_analysis"], default=[])
    holdings = load_json(PATHS["holdings"], default={})
    existing_events = load_json(PATHS["events"], default=[])
    if isinstance(existing_events, dict):
        existing_events = existing_events.get("events", [])

    print("[2/4] build corp map from announcements.json (NOT corp_scan_result.json)")
    corp_map = build_corp_map(announcements, window_days=args.corp_window)
    print(f"  corp_map: {len(corp_map)} stocks with corp actions in {args.corp_window}d")
    if len(corp_map) == 0 and announcements:
        print("  🔴 corp_map 係 0 但 announcements 有料 — classify/date parse 有問題")

    print("[3/4] normalize + merge events")
    new_events = normalize_alerts(alerts_doc)
    all_events = merge_events(existing_events, new_events)

    print("[4/4] build signals.json")
    issuer_map = build_issuer_map(placements, rights_analysis)
    signals = build_signals_json(holdings, all_events, corp_map, issuer_map)

    if args.dry_run:
        print("\nDRY RUN — nothing written")
        return

    atomic_write(PATHS["events"], all_events)
    atomic_write(PATHS["signals_out"], signals)
    print(f"\n✅ written: {PATHS['events']}")
    print(f"✅ written: {PATHS['signals_out']}")
    
    # Step 5: Save daily price snapshot for future backtests
    print("\n[5/5] save daily price snapshot")
    save_price_snapshot(holdings)


if __name__ == "__main__":
    sys.exit(main())
