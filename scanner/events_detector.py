"""CCASS Deposit (存倉) / Transfer (轉倉) Event Detection.

Compare per-broker CCASS holdings between T and T-1 to detect:

1. **Deposit (存倉)**: Total CCASS shares increase ≥ 1% of issued shares,
   without a matching broker pair offset. New shares entering the system.

2. **Transfer (轉倉)**: Broker A loses ≥ 2% of issued shares, Broker B gains
   a similar amount (ratio 0.8-1.25). Shares moving between brokers.

Usage:
    from scanner.events_detector import detect_events

    events = detect_events(today_brokers, yesterday_brokers, issued_shares)
"""
from __future__ import annotations

from typing import Optional


def detect_events(
    today_brokers: dict[str, int],
    yesterday_brokers: dict[str, int],
    issued_shares: int,
) -> list[dict]:
    """Detect deposit & transfer events.

    Parameters
    ----------
    today_brokers:
        {broker_id: shares} for the current trading day (T).
    yesterday_brokers:
        {broker_id: shares} for the previous trading day (T-1).
    issued_shares:
        Total issued shares of the stock (for percentage calculations).

    Returns
    -------
    list[dict]:
        Each dict has keys:
          - type: "deposit" | "transfer"
          - pct:  percentage of issued shares
          - shares: number of shares
          - source / from / to: broker identifiers
    """
    events: list[dict] = []

    if not issued_shares or issued_shares <= 0:
        return events

    today_total = sum(today_brokers.values())
    yesterday_total = sum(yesterday_brokers.values())
    total_delta = today_total - yesterday_total
    total_delta_pct = (total_delta / issued_shares) * 100.0

    # ── 1. Deposit (存倉) ──────────────────────────────────────────────
    # Total CCASS shares increased >= 1% of issued shares.
    # This means new shares entered CCASS (e.g. stock lending returned,
    # new issuance, or previously unlisted shares deposited).
    if total_delta_pct >= 1.0:
        events.append({
            "type": "deposit",
            "pct": round(total_delta_pct, 2),
            "shares": total_delta,
            "source": "market",  # new shares entered CCASS from outside
        })

    # ── 2. Transfer (轉倉) ─────────────────────────────────────────────
    # One broker's decrease matches another broker's increase.
    # Criteria:
    #   - Gaining broker's increase >= 2% of issued shares
    #   - Losing broker's decrease >= 2% of issued shares
    #   - gain / loss ratio between 0.80 and 1.25
    threshold = 0.02 * issued_shares  # 2% of issued shares

    # Build lookup: gains (positive deltas) and losses (negative deltas)
    gains: dict[str, int] = {}
    losses: dict[str, int] = {}
    for bid, today_shares in today_brokers.items():
        yesterday_shares = yesterday_brokers.get(bid, 0)
        delta = today_shares - yesterday_shares
        if delta >= threshold:
            gains[bid] = delta
        elif delta <= -threshold:
            losses[bid] = -delta  # store as positive magnitude

    # Also check brokers that were in yesterday but disappeared today
    for bid, yesterday_shares in yesterday_brokers.items():
        if bid not in today_brokers:
            delta = -yesterday_shares
            if delta <= -threshold:
                losses[bid] = -delta  # store as positive magnitude

    # Match gains ↔ losses
    matched_losses: set[str] = set()
    for gid, gain in gains.items():
        for lid, loss in losses.items():
            if lid in matched_losses:
                continue
            ratio = gain / loss if loss > 0 else 0
            if 0.80 <= ratio <= 1.25:
                events.append({
                    "type": "transfer",
                    "from": lid,
                    "to": gid,
                    "pct": round(gain / issued_shares * 100, 2),
                    "shares": gain,
                })
                matched_losses.add(lid)
                break  # one gainer matched to at most one loser

    return events
