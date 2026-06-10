# -*- coding: utf-8 -*-
"""
schema.py — 統一 Event Schema + 舊格式 converter
================================================
全系統唯一嘅 event 定義。alerts.json / history.json / signals.json
全部由呢個 schema derive。

用法:
    from schema import make_event, normalize_legacy_alert, validate_event
"""

import hashlib
import json
import re
from datetime import datetime

SCHEMA_VERSION = 1

CATEGORIES = {
    "poc", "fvg", "gap", "year_open", "ipo",
    "ccass", "corp", "tech", "unknown",
}

_CATEGORY_RULES = [
    ("POC", "poc"), ("FVG", "fvg"), ("跳空", "gap"),
    ("年開", "year_open"), ("IPO", "ipo"), ("CCASS", "ccass"),
    ("增持", "corp"), ("配股", "corp"), ("配售", "corp"), ("供股", "corp"),
]

CORP_TYPE_KEYWORDS = {
    "placement": ["配售", "配股", "placing", "placement"],
    "rights": ["供股", "rights issue"],
    "increase": ["增持", "increase"],
}


def _pad_code(code):
    return str(code or "").strip().lstrip("0").zfill(5) if code else ""


def infer_category(signal_type, explicit=None):
    if explicit and explicit in CATEGORIES:
        return explicit
    s = str(signal_type or "")
    for kw, cat in _CATEGORY_RULES:
        if kw in s:
            return cat
    return "unknown"


def _event_id(code, signal_type, alert_date, signal_date):
    raw = f"{code}|{signal_type}|{alert_date}|{signal_date}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def make_event(
    code, name="", signal_type="",
    alert_date="", signal_date=None,
    price_at_alert=None, category=None, priority=2,
    meta=None, corp=None,
):
    code = _pad_code(code)
    signal_date = signal_date or alert_date
    return {
        "v": SCHEMA_VERSION,
        "id": _event_id(code, signal_type, alert_date, signal_date),
        "code": code,
        "name": name or "",
        "category": infer_category(signal_type, category),
        "signal_type": signal_type,
        "signal_date": signal_date,
        "alert_date": alert_date,
        "price_at_alert": price_at_alert,
        "priority": priority,
        "meta": meta or {},
        "corp": corp,
        "outcome": {
            "entry_price": price_at_alert,
            "fwd_5d": None, "fwd_20d": None, "fwd_60d": None,
            "max_gain_20d": None, "max_dd_20d": None,
            "benchmark_fwd_20d": None,
            "mc_bucket": None, "suspended": False, "filled_at": None,
        },
    }


def normalize_legacy_alert(a, day_date):
    sig = a.get("signal")
    if isinstance(sig, dict):
        stype = sig.get("type", "")
        return make_event(
            code=a.get("code"), name=a.get("name", ""),
            signal_type=stype,
            alert_date=day_date,
            signal_date=sig.get("date") or day_date,
            price_at_alert=sig.get("current"),
            meta={k: v for k, v in sig.items() if k not in ("type", "date", "current")},
            corp=_corp_from_legacy(a),
        )

    created = (a.get("created_at") or day_date or "")[:10]
    return make_event(
        code=a.get("code"), name=a.get("name", ""),
        signal_type=str(sig or ""),
        alert_date=created or day_date,
        signal_date=created or day_date,
        price_at_alert=a.get("price"),
        category=a.get("category"),
        priority=a.get("priority", 2),
        meta={
            "source": a.get("source", ""),
            "strategy": a.get("strategy", ""),
            "message": a.get("message", ""),
            "tags": a.get("tags", []),
        },
        corp=_corp_from_legacy(a),
    )


def _corp_from_legacy(a):
    ct = (a.get("corp_type") or "").strip()
    if not ct:
        return None
    for norm, kws in CORP_TYPE_KEYWORDS.items():
        if any(kw.lower() in ct.lower() for kw in kws):
            return {"type": norm, "link": a.get("source_url", ""), "date": ""}
    return {"type": "other", "link": a.get("source_url", ""), "date": ""}


def parse_announcement_date(raw):
    """announcements.json 日期: '2026-06-10' 或 '09/06/2026'"""
    if not raw:
        return None
    s = str(raw).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def classify_announcement(ann):
    """announcement → corp type ('placement'/'rights'/'increase') 或 None.
    用 announcements.json 已存在嘅 'type' field (increase/placement/rights),
    fallback 到 'types' list 同 'title'."""
    # Primary: the 'type' field already has "increase", "placement", "rights"
    atype = (ann.get("type") or "").strip().lower()
    if atype in CORP_TYPE_KEYWORDS:
        return atype

    # Fallback: types list
    types_list = ann.get("types") or []
    for t in types_list:
        tl = str(t).lower()
        for norm, kws in CORP_TYPE_KEYWORDS.items():
            if any(kw.lower() in tl for kw in kws):
                return norm

    # Second fallback: title text
    title = (ann.get("title") or "").lower()
    for norm, kws in CORP_TYPE_KEYWORDS.items():
        if any(kw.lower() in title for kw in kws):
            return norm

    return None


def validate_event(e):
    problems = []
    if not e.get("code") or len(e["code"]) != 5:
        problems.append(f"bad code: {e.get('code')}")
    if not e.get("alert_date"):
        problems.append("missing alert_date")
    if e.get("category") not in CATEGORIES:
        problems.append(f"bad category: {e.get('category')}")
    if e.get("signal_date") and e.get("alert_date") and e["signal_date"] > e["alert_date"]:
        problems.append("signal_date after alert_date (clock issue?)")
    return problems


if __name__ == "__main__":
    sample_a = {
        "source": "cloud_scanner", "category": "year_open", "code": "09609",
        "name": "海偉股份", "signal": "年開突破", "price": 8.65,
        "priority": 1, "created_at": "2026-06-10T12:22:17",
    }
    sample_b = {
        "code": "01952", "name": "EVEREST MED",
        "signal": {"type": "向上FVG", "fvg_pct": 2.51, "date": "2026-04-16", "current": 27.3},
        "corp_type": "",
    }
    for s in (sample_a, sample_b):
        ev = normalize_legacy_alert(s, "2026-06-10")
        probs = validate_event(ev)
        print(json.dumps(ev, ensure_ascii=False, indent=2))
        print("validate:", probs or "OK")
