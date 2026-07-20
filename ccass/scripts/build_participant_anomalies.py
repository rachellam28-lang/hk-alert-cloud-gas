#!/usr/bin/env python3
"""Build participant delta/anomaly caches from CCASS participant holdings.

Default target date is repo-root ``holdings.json.updated`` so this output stays
aligned with the publishable dashboard snapshot instead of a partial latest DB
tail day.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


CCASS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CCASS_DIR.parent
DB_PATH = CCASS_DIR / "holdings.db"
CCASS_OUT = CCASS_DIR / "data" / "participant_anomalies.json"
REPO_OUT = REPO_ROOT / "data" / "participant_anomalies.json"

sys.path.insert(0, str(CCASS_DIR))
from src.db import init_db, get_conn  # noqa: E402


MIN_PARTICIPANT_PCT_DELTA = 0.20
MIN_PARTICIPANT_CCASS_IMPACT_PCT = 0.20
MIN_TRANSFER_MATCHED_PCT = 0.30
MIN_CLUSTER_PCT = 0.80


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
        f"SELECT MAX(trade_date) FROM {table} WHERE trade_date < ?",
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
        "updated": f"{target_date} participant backfill required",
        "date": target_date,
        "previous_date": previous,
        "count": 0,
        "published_count": 0,
        "stock_count": 0,
        "summary": {"by_type": {}, "severe_count": 0, "high_count": 0},
        "anomalies": [],
        "message": reason,
    }


def rebuild_deltas(conn: sqlite3.Connection, table: str, target_date: str, prev_date: str) -> int:
    computed_at = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute("DELETE FROM ccass_participant_deltas WHERE trade_date = ?", (target_date,))
    conn.execute(
        f"""
        INSERT INTO ccass_participant_deltas (
            stock_code, trade_date, previous_date, participant_id, participant_name,
            shares_previous, shares_current, shares_delta,
            pct_previous, pct_current, pct_delta,
            is_new, is_exited, abs_shares_delta, abs_pct_delta, computed_at
        )
        WITH
        cur AS (
            SELECT stock_code, participant_id, participant_name, shares, pct_of_issued
            FROM {table}
            WHERE trade_date = ?
        ),
        prev AS (
            SELECT stock_code, participant_id, participant_name, shares, pct_of_issued
            FROM {table}
            WHERE trade_date = ?
        )
        SELECT
            c.stock_code,
            ?,
            ?,
            c.participant_id,
            COALESCE(c.participant_name, p.participant_name),
            COALESCE(p.shares, 0),
            COALESCE(c.shares, 0),
            COALESCE(c.shares, 0) - COALESCE(p.shares, 0),
            p.pct_of_issued,
            c.pct_of_issued,
            ROUND(COALESCE(c.pct_of_issued, 0) - COALESCE(p.pct_of_issued, 0), 4),
            CASE WHEN p.participant_id IS NULL THEN 1 ELSE 0 END,
            0,
            ABS(COALESCE(c.shares, 0) - COALESCE(p.shares, 0)),
            ABS(COALESCE(c.pct_of_issued, 0) - COALESCE(p.pct_of_issued, 0)),
            ?
        FROM cur c
        LEFT JOIN prev p
          ON c.stock_code = p.stock_code
         AND c.participant_id = p.participant_id
        UNION ALL
        SELECT
            p.stock_code,
            ?,
            ?,
            p.participant_id,
            p.participant_name,
            COALESCE(p.shares, 0),
            0,
            -COALESCE(p.shares, 0),
            p.pct_of_issued,
            NULL,
            ROUND(-COALESCE(p.pct_of_issued, 0), 4),
            0,
            1,
            ABS(COALESCE(p.shares, 0)),
            ABS(COALESCE(p.pct_of_issued, 0)),
            ?
        FROM prev p
        LEFT JOIN cur c
          ON c.stock_code = p.stock_code
         AND c.participant_id = p.participant_id
        WHERE c.participant_id IS NULL
        """,
        (
            target_date,
            prev_date,
            target_date,
            prev_date,
            computed_at,
            target_date,
            prev_date,
            computed_at,
        ),
    )
    row = conn.execute(
        "SELECT COUNT(*) FROM ccass_participant_deltas WHERE trade_date = ?",
        (target_date,),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def load_stock_context(conn: sqlite3.Connection, target_date: str, prev_date: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT
            d.stock_code,
            u.stock_name,
            d.total_shares,
            d.total_pct,
            d.num_participants,
            d.top5_pct,
            d.top10_pct,
            p.num_participants AS prev_num_participants,
            p.top5_pct AS prev_top5_pct,
            p.top10_pct AS prev_top10_pct,
            p.total_pct AS prev_total_pct
        FROM ccass_daily d
        LEFT JOIN ccass_daily p
          ON p.stock_code = d.stock_code
         AND p.trade_date = ?
        LEFT JOIN stock_universe u
          ON u.stock_code = d.stock_code
        WHERE d.trade_date = ?
        """
        ,
        (prev_date, target_date),
    ).fetchall()
    out = {}
    for row in rows:
        ctx = dict(row)
        issued = None
        total_shares = row["total_shares"]
        total_pct = row["total_pct"]
        if total_shares and total_pct and total_pct > 0:
            issued = total_shares / (total_pct / 100.0)
        ctx["issued_shares_est"] = issued
        out[row["stock_code"]] = ctx
    return out


def load_delta_aggregates(conn: sqlite3.Connection, target_date: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT
            stock_code,
            SUM(CASE WHEN shares_delta > 0 THEN shares_delta ELSE 0 END) AS gross_in,
            SUM(CASE WHEN shares_delta < 0 THEN -shares_delta ELSE 0 END) AS gross_out,
            SUM(CASE WHEN pct_delta > 0 THEN pct_delta ELSE 0 END) AS gross_in_pct,
            SUM(CASE WHEN pct_delta < 0 THEN -pct_delta ELSE 0 END) AS gross_out_pct,
            SUM(CASE WHEN shares_delta > 0 THEN 1 ELSE 0 END) AS gainers,
            SUM(CASE WHEN shares_delta < 0 THEN 1 ELSE 0 END) AS losers,
            SUM(CASE WHEN is_new = 1 THEN 1 ELSE 0 END) AS new_participants,
            SUM(CASE WHEN is_exited = 1 THEN 1 ELSE 0 END) AS exited_participants
        FROM ccass_participant_deltas
        WHERE trade_date = ?
        GROUP BY stock_code
        """
        ,
        (target_date,),
    ).fetchall()
    return {row["stock_code"]: dict(row) for row in rows}


def severity_for_score(score: float) -> str:
    if score >= 160:
        return "severe"
    if score >= 80:
        return "high"
    return "medium"


def seat_impact_pct(shares_delta: int, total_shares: int | None) -> float:
    if not total_shares:
        return 0.0
    return abs(shares_delta) / float(total_shares) * 100.0


def append_participant_anomalies(conn: sqlite3.Connection, target_date: str, stock_ctx: dict[str, dict], anomalies: list[dict]) -> None:
    rows = conn.execute(
        """
        SELECT
            stock_code,
            participant_id,
            participant_name,
            previous_date,
            shares_previous,
            shares_current,
            shares_delta,
            pct_previous,
            pct_current,
            pct_delta,
            is_new,
            is_exited,
            abs_shares_delta,
            abs_pct_delta
        FROM ccass_participant_deltas
        WHERE trade_date = ?
          AND (abs_pct_delta >= 0.10 OR is_new = 1 OR is_exited = 1)
        ORDER BY abs_pct_delta DESC, abs_shares_delta DESC
        """
        ,
        (target_date,),
    ).fetchall()
    for row in rows:
        ctx = stock_ctx.get(row["stock_code"])
        if not ctx:
            continue
        impact = seat_impact_pct(int(row["shares_delta"] or 0), ctx.get("total_shares"))
        pct_prev = float(row["pct_previous"] or 0.0)
        pct_cur = float(row["pct_current"] or 0.0)
        pct_delta = float(row["pct_delta"] or 0.0)
        if not (
            abs(pct_delta) >= MIN_PARTICIPANT_PCT_DELTA
            or impact >= MIN_PARTICIPANT_CCASS_IMPACT_PCT
            or ((row["is_new"] or row["is_exited"]) and max(pct_prev, pct_cur) >= MIN_PARTICIPANT_PCT_DELTA)
        ):
            continue
        if row["is_new"]:
            anomaly_type = "new_large_seat"
        elif row["is_exited"]:
            anomaly_type = "seat_exit"
        elif row["shares_delta"] > 0:
            anomaly_type = "seat_increase"
        else:
            anomaly_type = "seat_decrease"
        score = abs(pct_delta) * 100.0 + impact * 40.0 + (10.0 if row["is_new"] or row["is_exited"] else 0.0)
        details = {
            "impact_ccass_pct": round(impact, 4),
            "shares_previous": int(row["shares_previous"] or 0),
            "shares_current": int(row["shares_current"] or 0),
            "pct_previous": round(pct_prev, 4),
            "pct_current": round(pct_cur, 4),
        }
        anomalies.append(
            {
                "code": row["stock_code"],
                "name": ctx.get("stock_name") or row["stock_code"],
                "type": anomaly_type,
                "scope": "participant",
                "participant_id": row["participant_id"],
                "participant_name": row["participant_name"] or "",
                "date": target_date,
                "previous_date": row["previous_date"],
                "severity": severity_for_score(score),
                "score": round(score, 2),
                "shares_delta": int(row["shares_delta"] or 0),
                "pct_delta": round(pct_delta, 4),
                "details": details,
                "note": (
                    "新席位進場"
                    if row["is_new"]
                    else "席位完全退出"
                    if row["is_exited"]
                    else "大席位加倉"
                    if row["shares_delta"] > 0
                    else "大席位減倉"
                ),
            }
        )


def maybe_append_stock_anomaly(anomalies: list[dict], ctx: dict, anomaly_type: str, score: float, note: str, details: dict) -> None:
    anomalies.append(
        {
            "code": ctx["stock_code"],
            "name": ctx.get("stock_name") or ctx["stock_code"],
            "type": anomaly_type,
            "scope": "stock",
            "participant_id": "",
            "participant_name": "",
            "date": ctx["trade_date"],
            "previous_date": details.get("previous_date"),
            "severity": severity_for_score(score),
            "score": round(score, 2),
            "shares_delta": details.get("net_shares_delta"),
            "pct_delta": details.get("net_pct_delta"),
            "details": details,
            "note": note,
        }
    )


def append_stock_anomalies(target_date: str, prev_date: str, stock_ctx: dict[str, dict], aggregates: dict[str, dict], anomalies: list[dict]) -> None:
    for code, ctx in stock_ctx.items():
        agg = aggregates.get(code)
        if not agg:
            continue
        total_shares = int(ctx.get("total_shares") or 0)
        issued = float(ctx.get("issued_shares_est") or total_shares or 1.0)
        top5_delta = float((ctx.get("top5_pct") or 0.0) - (ctx.get("prev_top5_pct") or 0.0))
        top10_delta = float((ctx.get("top10_pct") or 0.0) - (ctx.get("prev_top10_pct") or 0.0))
        participants_delta = int((ctx.get("num_participants") or 0) - (ctx.get("prev_num_participants") or 0))
        gross_in = int(agg.get("gross_in") or 0)
        gross_out = int(agg.get("gross_out") or 0)
        gross_in_pct = float(agg.get("gross_in_pct") or 0.0)
        gross_out_pct = float(agg.get("gross_out_pct") or 0.0)
        gainers = int(agg.get("gainers") or 0)
        losers = int(agg.get("losers") or 0)
        new_participants = int(agg.get("new_participants") or 0)
        exited_participants = int(agg.get("exited_participants") or 0)
        gross_matched = min(gross_in, gross_out)
        matched_turnover_pct = gross_matched / issued * 100.0 if issued else 0.0
        net_shares_delta = gross_in - gross_out
        net_pct_delta = gross_in_pct - gross_out_pct
        imbalance_ratio = abs(net_shares_delta) / gross_matched if gross_matched else 99.0
        base_details = {
            "previous_date": prev_date,
            "gross_in": gross_in,
            "gross_out": gross_out,
            "gross_in_pct": round(gross_in_pct, 4),
            "gross_out_pct": round(gross_out_pct, 4),
            "net_shares_delta": int(net_shares_delta),
            "net_pct_delta": round(net_pct_delta, 4),
            "gainers": gainers,
            "losers": losers,
            "new_participants": new_participants,
            "exited_participants": exited_participants,
            "top5_delta": round(top5_delta, 4),
            "top10_delta": round(top10_delta, 4),
            "participants_delta": participants_delta,
            "matched_turnover_pct": round(matched_turnover_pct, 4),
            "imbalance_ratio": round(imbalance_ratio, 4),
            "total_shares": total_shares,
        }
        ctx = {**ctx, "stock_code": code, "trade_date": target_date}
        if (
            matched_turnover_pct >= MIN_TRANSFER_MATCHED_PCT
            and imbalance_ratio <= 0.20
            and abs(top5_delta) <= 1.0
            and abs(top10_delta) <= 1.2
        ):
            score = matched_turnover_pct * 60.0 + (gainers + losers) * 3.0
            maybe_append_stock_anomaly(
                anomalies,
                ctx,
                "suspected_transfer",
                score,
                "大額雙向對敲，較似券商席位轉倉",
                base_details,
            )
        if (
            participants_delta >= max(8, int((ctx.get("prev_num_participants") or 0) * 0.08))
            and top5_delta <= -1.5
        ):
            score = abs(top5_delta) * 35.0 + participants_delta * 2.0 + max(0.0, gross_out_pct) * 12.0
            maybe_append_stock_anomaly(
                anomalies,
                ctx,
                "fragmentation",
                score,
                "持倉碎片化，集中度下降",
                base_details,
            )
        if participants_delta <= -5 and top5_delta >= 1.5 and gross_in_pct >= gross_out_pct:
            score = top5_delta * 35.0 + abs(participants_delta) * 2.0 + gross_in_pct * 15.0
            maybe_append_stock_anomaly(
                anomalies,
                ctx,
                "concentration_up",
                score,
                "集中度上升，席位數減少",
                base_details,
            )
        if gainers >= 3 and gross_in_pct >= MIN_CLUSTER_PCT and gross_in_pct >= gross_out_pct + 0.3 and top5_delta >= 0.8:
            score = gross_in_pct * 40.0 + top5_delta * 25.0 + gainers * 2.0
            maybe_append_stock_anomaly(
                anomalies,
                ctx,
                "accumulation_cluster",
                score,
                "多個席位同步加倉，偏向收集",
                base_details,
            )
        if losers >= 3 and gross_out_pct >= MIN_CLUSTER_PCT and gross_out_pct >= gross_in_pct + 0.3 and top5_delta <= -0.8:
            score = gross_out_pct * 40.0 + abs(top5_delta) * 25.0 + losers * 2.0
            maybe_append_stock_anomaly(
                anomalies,
                ctx,
                "distribution_cluster",
                score,
                "多個席位同步減倉，偏向派發",
                base_details,
            )


def persist_anomalies(conn: sqlite3.Connection, target_date: str, anomalies: list[dict]) -> None:
    detected_at = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute("DELETE FROM ccass_participant_anomalies WHERE trade_date = ?", (target_date,))
    rows = []
    for item in anomalies:
        rows.append(
            (
                item["code"],
                target_date,
                item["type"],
                item.get("participant_id") or "",
                item.get("participant_name") or "",
                item.get("name") or item["code"],
                item.get("previous_date"),
                item.get("severity"),
                float(item.get("score") or 0.0),
                item.get("shares_delta"),
                item.get("pct_delta"),
                json.dumps(item.get("details") or {}, ensure_ascii=False, separators=(",", ":")),
                detected_at,
            )
        )
    conn.executemany(
        """
        INSERT OR REPLACE INTO ccass_participant_anomalies (
            stock_code, trade_date, anomaly_type, participant_id, participant_name,
            stock_name, previous_date, severity, score, shares_delta, pct_delta,
            details_json, detected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def build_output(target_date: str, prev_date: str, count: int, total: int, pct: float, anomalies: list[dict], limit: int) -> dict:
    anomalies.sort(key=lambda item: (-float(item.get("score") or 0.0), item.get("code") or "", item.get("type") or ""))
    published = anomalies[:limit]
    by_type = Counter(item["type"] for item in anomalies)
    severity = Counter(item["severity"] for item in anomalies)
    return {
        "ok": True,
        "status": "ok",
        "updated": f"{target_date} vs {prev_date}",
        "date": target_date,
        "previous_date": prev_date,
        "coverage": {
            "count": count,
            "total": total,
            "pct": round(pct * 100.0, 2),
        },
        "count": len(anomalies),
        "published_count": len(published),
        "stock_count": len({item["code"] for item in anomalies}),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "by_type": dict(sorted(by_type.items())),
            "severe_count": severity.get("severe", 0),
            "high_count": severity.get("high", 0),
            "participant_scope_count": sum(1 for item in anomalies if item.get("scope") == "participant"),
            "stock_scope_count": sum(1 for item in anomalies if item.get("scope") == "stock"),
        },
        "anomalies": published,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate data/participant_anomalies.json")
    parser.add_argument("--date", help="Target trade date. Defaults to holdings.json.updated")
    parser.add_argument("--limit", type=int, default=300, help="Number of anomaly records to publish")
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

    init_db()
    with get_conn() as conn:
        table = pick_holdings_table(conn)
        if not has_date(conn, table, target_date):
            msg = f"target date {target_date} not found in {table}"
            if args.allow_unavailable:
                output = unavailable_payload(target_date, msg)
                atomic_write_json(CCASS_OUT, output)
                REPO_OUT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(CCASS_OUT, REPO_OUT)
                print(f"Saved unavailable participant anomaly snapshot: {msg}")
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
                print(f"Saved unavailable participant anomaly snapshot: {msg}")
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
                print(f"Saved unavailable participant anomaly snapshot: {msg}")
                return 0
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1

        delta_rows = rebuild_deltas(conn, table, target_date, prev_date)
        stock_ctx = load_stock_context(conn, target_date, prev_date)
        aggregates = load_delta_aggregates(conn, target_date)
        anomalies: list[dict] = []
        append_participant_anomalies(conn, target_date, stock_ctx, anomalies)
        append_stock_anomalies(target_date, prev_date, stock_ctx, aggregates, anomalies)
        persist_anomalies(conn, target_date, anomalies)
        output = build_output(target_date, prev_date, count, total, pct, anomalies, args.limit)
        output["delta_rows"] = delta_rows

    atomic_write_json(CCASS_OUT, output)
    REPO_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CCASS_OUT, REPO_OUT)
    print(
        f"Saved {output['published_count']}/{output['count']} participant anomalies "
        f"for {output['updated']} to {REPO_OUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
