#!/usr/bin/env python3
"""Shared issuer pressure score logic for rights/placement pages.

Keep the exact same heuristics across generators and front-end exports so the
"發行方有利度" badge stays consistent everywhere.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict


def _num(v: Any):
    try:
        n = float(v)
    except Exception:
        return None
    return n if math.isfinite(n) else None


def issuer_pressure_score(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return normalized issuer score payload.

    Output:
        {
          "score": int 0..100,
          "label": "...",
          "cls": "...",
          "shareholder_pressure": {"score", "label", "cls"},
          "reaction": {"pct", "label", "cls"},
        }
    """

    score = 50
    cat = str(d.get("category") or "")
    purpose = str(d.get("purpose") or "")

    discount = _num(d.get("discount_pct"))
    dilution = _num(d.get("pct_num"))
    amount = _num(d.get("amount_num"))
    reaction_pct = _num(d.get("current_return_pct"))
    if reaction_pct is None:
        latest = _num(d.get("latest_price") or d.get("latestPrice"))
        issue_px = _num(d.get("price_num") or d.get("price"))
        if latest is not None and issue_px not in (None, 0):
            reaction_pct = (latest / issue_px - 1) * 100

    if cat == "先舊後新":
        score += 12
    elif cat == "供股":
        score += 10
    elif cat == "配售":
        score += 6
    elif cat == "代價發行":
        score += 4
    elif "債" in cat:
        score += 14

    if discount is not None:
        if discount <= -30:
            score += 22
        elif discount <= -20:
            score += 18
        elif discount <= -10:
            score += 12
        elif discount <= -5:
            score += 6
        elif discount >= 10:
            score -= 6

    if dilution is not None:
        if dilution >= 50:
            score += 18
        elif dilution >= 20:
            score += 12
        elif dilution >= 10:
            score += 8
        elif dilution <= 3:
            score -= 4

    if amount is not None and dilution is not None and dilution > 0:
        implied_mcap = amount / (dilution / 100)
        issue_to_mcap = amount / implied_mcap if implied_mcap > 0 else None
        if issue_to_mcap is not None:
            if issue_to_mcap >= 0.25:
                score += 16
            elif issue_to_mcap >= 0.10:
                score += 10
            elif issue_to_mcap <= 0.02:
                score -= 4

    if re.search(r"(償還債務|再融資|營運資金|營運需要|working capital|debt repayment|refinanc)", purpose, re.I):
        score += 10
    if re.search(r"(收購|acquisition|併購|投資|業務發展|擴大資本基礎)", purpose, re.I):
        score += 4

    score = max(0, min(100, int(round(score))))
    if score >= 80:
        label = "有利度高"
        cls = "issuer-high"
    elif score >= 60:
        label = "偏發行方"
        cls = "issuer-high"
    elif score >= 40:
        label = "中性"
        cls = "issuer-neutral"
    elif score >= 20:
        label = "偏股東"
        cls = "issuer-low"
    else:
        label = "股東友好"
        cls = "issuer-low"

    if reaction_pct is None:
        reaction_label = "未足夠數據"
        reaction_cls = "issuer-neutral"
    elif reaction_pct >= 15:
        reaction_label = "反應強"
        reaction_cls = "issuer-high"
    elif reaction_pct >= 5:
        reaction_label = "偏正面"
        reaction_cls = "issuer-high"
    elif reaction_pct > -5:
        reaction_label = "中性"
        reaction_cls = "issuer-neutral"
    elif reaction_pct > -15:
        reaction_label = "偏負面"
        reaction_cls = "issuer-low"
    else:
        reaction_label = "反應弱"
        reaction_cls = "issuer-low"

    if score >= 80:
        pressure_label = "壓力高"
    elif score >= 60:
        pressure_label = "偏高"
    elif score >= 40:
        pressure_label = "中性"
    elif score >= 20:
        pressure_label = "偏低"
    else:
        pressure_label = "壓力低"

    pressure = {
        "score": score,
        "label": pressure_label,
        "cls": cls,
    }
    reaction = {
        "pct": None if reaction_pct is None else round(reaction_pct, 1),
        "label": reaction_label,
        "cls": reaction_cls,
    }

    return {
        "score": score,
        "label": label,
        "cls": cls,
        "shareholder_pressure": pressure,
        "reaction": reaction,
    }
