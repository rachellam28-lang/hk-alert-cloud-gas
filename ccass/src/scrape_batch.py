"""Scrape a small stock batch in one subprocess.

This keeps the OS-level hard timeout protection from scrape_one.py while
reusing one HKEX session/form token across multiple stocks. Per-stock
subprocesses caused one GET-token request per stock, doubling HKEX traffic and
creating a highly mechanical pattern.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _snapshot_to_dict(snap) -> dict:
    from src.scraper import _compute_concentration_metrics

    sorted_shares = sorted(
        [h["shares"] for h in snap.holdings if h.get("shares")],
        reverse=True,
    )
    top5 = sum(sorted_shares[:5])
    top10 = sum(sorted_shares[:10])
    top5_pct = round(top5 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    top10_pct = round(top10 / snap.total_shares * 100, 2) if snap.total_shares > 0 else None
    cm = _compute_concentration_metrics(snap.holdings)

    return {
        "ok": True,
        "stock_code": snap.stock_code,
        "trade_date": snap.trade_date,
        "total_shares": snap.total_shares,
        "total_pct": snap.total_pct,
        "num_participants": snap.num_participants,
        "top5_pct": top5_pct,
        "top10_pct": top10_pct,
        "adj_hhi": cm.get("adj_hhi"),
        "broker_top5_pct": cm.get("broker_top5_pct"),
        "top_broker_id": cm.get("top_broker_id", ""),
        "top_broker_name": cm.get("top_broker_name", ""),
        "top_broker_pct": cm.get("top_broker_pct"),
        "futu_pct": cm.get("futu_pct"),
        "a00005_pct": cm.get("a00005_pct"),
        "adjusted_float": cm.get("adjusted_float"),
        "holdings": snap.holdings,
    }


def main() -> int:
    if len(sys.argv) < 7:
        print(json.dumps({"ok": False, "error": "usage"}))
        return 64

    logging.root.setLevel(logging.WARNING)
    logging.getLogger("scraper").setLevel(logging.WARNING)

    query_date = date.fromisoformat(sys.argv[1])
    user_agent = sys.argv[2]
    delay_min = float(sys.argv[3])
    delay_max = float(sys.argv[4])
    timeout = int(sys.argv[5])
    max_retries = int(sys.argv[6])

    try:
        codes = json.loads(sys.stdin.read() or "[]")
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"bad stdin json: {e}"}))
        return 64

    from src.scraper import HOLDINGSScraper, HKEXBlockedError
    logging.getLogger("scraper").disabled = True

    scraper = HOLDINGSScraper(
        user_agent=user_agent,
        delay_min=delay_min,
        delay_max=delay_max,
        timeout=timeout,
        max_retries=max_retries,
    )

    results: list[dict] = []
    try:
        for code in codes:
            code = str(code).zfill(5)
            try:
                # src.logger writes to stdout in this repo. Keep subprocess
                # stdout machine-readable for runner.py by diverting scraper
                # chatter to stderr while each request runs.
                with redirect_stdout(sys.stderr):
                    snap = scraper.scrape_stock(code, query_date)
                if snap and snap.holdings:
                    results.append(_snapshot_to_dict(snap))
                else:
                    results.append({"ok": False, "stock_code": code, "reason": "no_data"})
            except HKEXBlockedError as e:
                print(json.dumps({
                    "ok": False,
                    "blocked": True,
                    "error": str(e),
                    "results": results,
                }, ensure_ascii=False))
                return 2
            except Exception as e:
                results.append({
                    "ok": False,
                    "stock_code": code,
                    "reason": str(e)[:200],
                })
    finally:
        try:
            scraper.session.close()
        except Exception:
            pass

    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
