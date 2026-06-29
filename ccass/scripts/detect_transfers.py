#!/usr/bin/env python3
"""Generate warehouse-transfer monitor JSON from CCASS participant holdings.

Default target date is the current publishable date in repo-root
``holdings.json``. That keeps ``data/transfers.json`` aligned with the
dashboard's holdings snapshot instead of using a partial latest DB tail day.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


CCASS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CCASS_DIR.parent
DB_PATH = CCASS_DIR / "holdings.db"
CCASS_OUT = CCASS_DIR / "data" / "transfers.json"
REPO_OUT = REPO_ROOT / "data" / "transfers.json"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return bool(row)


def pick_holdings_table(conn: sqlite3.Connection) -> str:
    if table_exists(conn, "ccass_holdings"):
        return "ccass_holdings"
    if table_exists(conn, "holdings_holdings"):
        return "holdings_holdings"
    raise RuntimeError("No ccass_holdings/holdings_holdings table found")


def default_target_date() -> str | None:
    holdings = load_json(REPO_ROOT / "holdings.json", {})
    return holdings.get("updated") if isinstance(holdings, dict) else None


def previous_date(conn: sqlite3.Connection, table: str, target_date: str) -> str | None:
    row = conn.execute(
        f"""
        SELECT MAX(trade_date)
        FROM {table}
        WHERE trade_date < ?
        """,
        (target_date,),
    ).fetchone()
    return row[0] if row and row[0] else None


def has_date(conn: sqlite3.Connection, table: str, trade_date: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE trade_date = ? LIMIT 1",
        (trade_date,),
    ).fetchone()
    return bool(row)


def coverage(conn: sqlite3.Connection, table: str, trade_date: str) -> tuple[int, int, float]:
    active_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM stock_universe
        WHERE is_active=1
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """
    ).fetchone()
    total = int(active_row[0] or 0) if active_row else 0
    count_row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT stock_code)
        FROM {table}
        WHERE trade_date = ?
          AND stock_code NOT LIKE '029%'
          AND stock_code NOT LIKE '04%'
          AND stock_code NOT LIKE '8%'
        """,
        (trade_date,),
    ).fetchone()
    count = int(count_row[0] or 0) if count_row else 0
    pct = count / total if total else 0.0
    return count, total, pct


def unavailable_payload(target_date: str, reason: str, previous: str | None = None) -> dict:
    return {
        "ok": False,
        "status": "backfill_required",
        "updated": f"{target_date} transfer backfill required",
        "date": target_date,
        "previous_date": previous,
        "count": 0,
        "transfers": [],
        "message": reason,
    }


def build_transfers(conn: sqlite3.Connection, table: str, d1: str, d2: str, min_change: int, limit: int) -> dict:
    changes = conn.execute(
        f"""
        SELECT h1.stock_code,
               h1.participant_id,
               h1.participant_name,
               h1.shares - h2.shares AS share_chg,
               ROUND(COALESCE(h1.pct_of_issued, 0) - COALESCE(h2.pct_of_issued, 0), 4) AS pct_chg,
               h1.shares AS today_shares
        FROM {table} h1
        JOIN {table} h2
          ON h1.stock_code = h2.stock_code
         AND h1.participant_id = h2.participant_id
        WHERE h1.trade_date = ?
          AND h2.trade_date = ?
          AND ABS(h1.shares - h2.shares) > ?
        ORDER BY ABS(h1.shares - h2.shares) DESC
        LIMIT 2000
        """,
        (d1, d2, min_change),
    ).fetchall()

    stock_changes: dict[str, list[dict]] = defaultdict(list)
    for code, pid, pname, chg, pct_chg, shares in changes:
        stock_changes[code].append(
            {
                "pid": pid,
                "pname": pname,
                "chg": chg,
                "pct_chg": pct_chg,
                "shares": shares,
            }
        )

    transfers: list[dict] = []
    for code, items in stock_changes.items():
        ins = [item for item in items if item["chg"] > 0]
        outs = [item for item in items if item["chg"] < 0]
        if not ins or not outs:
            continue

        name_row = conn.execute(
            "SELECT stock_name FROM stock_universe WHERE stock_code = ?",
            (code,),
        ).fetchone()
        name = name_row[0] if name_row and name_row[0] else code

        total_row = conn.execute(
            f"SELECT SUM(shares) FROM {table} WHERE stock_code = ? AND trade_date = ?",
            (code, d1),
        ).fetchone()
        total_shares = int(total_row[0] or 0)

        outstanding_shares = total_shares
        daily_row = conn.execute(
            """
            SELECT total_shares, total_pct
            FROM ccass_daily
            WHERE stock_code = ? AND trade_date = ?
            """,
            (code, d1),
        ).fetchone()
        if daily_row and daily_row[0] and daily_row[1] and daily_row[1] > 0:
            outstanding_shares = int(daily_row[0] / (daily_row[1] / 100))

        total_in = int(sum(item["chg"] for item in ins))
        total_out = int(sum(abs(item["chg"]) for item in outs))

        transfers.append(
            {
                "code": code,
                "name": name,
                "total_in": total_in,
                "total_out": total_out,
                "total_shares": total_shares,
                "outstanding_shares": int(outstanding_shares),
                "ins": sorted(ins, key=lambda item: -item["chg"]),
                "outs": sorted(outs, key=lambda item: item["chg"]),
            }
        )

    transfers.sort(key=lambda item: -(item["total_in"] + item["total_out"]))
    return {
        "updated": f"{d1} vs {d2}",
        "date": d1,
        "previous_date": d2,
        "count": len(transfers),
        "transfers": transfers[:limit],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate data/transfers.json")
    parser.add_argument("--date", help="Target trade date. Defaults to holdings.json.updated")
    parser.add_argument("--min-change", type=int, default=100_000, help="Minimum participant share change")
    parser.add_argument("--limit", type=int, default=50, help="Number of transfer records to publish")
    parser.add_argument("--min-coverage", type=float, default=0.95, help="Minimum participant date coverage required")
    parser.add_argument("--allow-unavailable", action="store_true", help="Write an explicit unavailable snapshot instead of failing")
    args = parser.parse_args()

    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        print(f"ERROR: DB missing or empty: {DB_PATH}", file=sys.stderr)
        return 1

    target_date = args.date or default_target_date()
    if not target_date:
        print("ERROR: missing target date and holdings.json.updated unavailable", file=sys.stderr)
        return 1

    with sqlite3.connect(str(DB_PATH)) as conn:
        table = pick_holdings_table(conn)
        if not table_exists(conn, "ccass_daily") or not table_exists(conn, "stock_universe"):
            print("ERROR: DB missing ccass_daily or stock_universe", file=sys.stderr)
            return 1
        if not has_date(conn, table, target_date):
            msg = f"target date {target_date} not found in {table}"
            if args.allow_unavailable:
                output = unavailable_payload(target_date, msg)
                atomic_write_json(CCASS_OUT, output)
                REPO_OUT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(CCASS_OUT, REPO_OUT)
                print(f"Saved unavailable transfer snapshot: {msg}")
                return 0
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1
        prev_date = previous_date(conn, table, target_date)
        if not prev_date:
            msg = f"no previous date before {target_date} in {table}"
            if args.allow_unavailable:
                output = unavailable_payload(target_date, msg)
                atomic_write_json(CCASS_OUT, output)
                REPO_OUT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(CCASS_OUT, REPO_OUT)
                print(f"Saved unavailable transfer snapshot: {msg}")
                return 0
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1

        count, total, pct = coverage(conn, table, target_date)
        if pct < args.min_coverage:
            msg = (
                f"participant holdings coverage {count}/{total} "
                f"({pct * 100:.1f}%) below {args.min_coverage * 100:.1f}%"
            )
            if args.allow_unavailable:
                output = unavailable_payload(target_date, msg, prev_date)
                atomic_write_json(CCASS_OUT, output)
                REPO_OUT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(CCASS_OUT, REPO_OUT)
                print(f"Saved unavailable transfer snapshot: {msg}")
                return 0
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1

        output = build_transfers(conn, table, target_date, prev_date, args.min_change, args.limit)

    atomic_write_json(CCASS_OUT, output)
    REPO_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CCASS_OUT, REPO_OUT)

    print(
        f"Saved {len(output['transfers'])}/{output['count']} transfers "
        f"for {output['updated']} to {REPO_OUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
