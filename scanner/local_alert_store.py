"""
Local alert store — replaces GAS for alert + watchlist persistence.

SQLite (ccass/ccass.db) + JSON dashboard files.
Drop-in replacement for post_gas_alert / fetch_watchlist_from_gas / post_watchlist_to_gas.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HKT = timezone(timedelta(hours=8))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "ccass" / "ccass.db"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

WATCHLIST_EXPIRY_DAYS = int(os.getenv("WATCHLIST_EXPIRY_DAYS", "365"))


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_tables() -> None:
    """Create scanner tables if they don't exist."""
    db = get_db()
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS scanner_watchlist (
                code        TEXT NOT NULL,
                market      TEXT NOT NULL DEFAULT 'HK',
                name        TEXT,
                types_json  TEXT NOT NULL,
                ann_date    TEXT,
                source_url  TEXT,
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1,
                raw_json    TEXT,
                PRIMARY KEY (market, code, ann_date)
            );

            CREATE TABLE IF NOT EXISTS scanner_alerts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key     TEXT UNIQUE,
                market        TEXT DEFAULT 'HK',
                code          TEXT NOT NULL,
                category      TEXT,
                signal        TEXT,
                price         REAL,
                priority      INTEGER DEFAULT 1,
                message       TEXT,
                source_url    TEXT,
                chart_url     TEXT,
                payload_json  TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                sent_telegram INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_watchlist_active
                ON scanner_watchlist(active, expires_at);

            CREATE INDEX IF NOT EXISTS idx_alerts_created
                ON scanner_alerts(created_at);
        """
        )
        db.commit()
    finally:
        db.close()


# ── Alert Store ────────────────────────────────────────────────────────────────

def store_alert(payload: dict[str, Any]) -> bool:
    """
    Store alert in SQLite + export JSON for dashboard.

    Returns True if this is a new alert (not a duplicate).
    Mimics post_gas_alert() return semantics.
    """
    now = datetime.now(HKT).isoformat(timespec="seconds")
    code = str(payload.get("code", "")).zfill(5)
    category = payload.get("category", payload.get("source", "scanner"))
    signal = payload.get("signal", "")
    dedup_key = f"{code}|{category}|{signal}|{now[:10]}"

    db = get_db()
    try:
        db.execute(
            """
            INSERT OR IGNORE INTO scanner_alerts
                (dedup_key, market, code, category, signal, price, priority,
                 message, source_url, chart_url, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dedup_key,
                payload.get("market", "HK"),
                code,
                category,
                signal,
                payload.get("price"),
                payload.get("priority", 1),
                payload.get("message", ""),
                payload.get("source_url", ""),
                payload.get("chart_url", ""),
                json.dumps(payload, ensure_ascii=False),
                now,
            ),
        )
        db.commit()
        new = db.total_changes > 0
    finally:
        db.close()

    if new:
        print(f"[local] alert stored: {code} {signal}")
        _export_alerts_json()
    return new


# ── Watchlist Store ─────────────────────────────────────────────────────────────

def fetch_watchlist() -> dict[str, dict[str, Any]]:
    """
    Fetch active watchlist from SQLite.

    Returns {code: entry} dict — same format as fetch_watchlist_from_gas().
    """
    today = datetime.now(HKT).strftime("%Y-%m-%d")
    db = get_db()
    try:
        rows = db.execute(
            """
            SELECT * FROM scanner_watchlist
            WHERE active = 1 AND expires_at >= ?
            ORDER BY created_at DESC
            """,
            (today,),
        ).fetchall()

        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            code = r["code"]
            entry: dict[str, Any] = {
                "code": code,
                "name": r["name"],
                "types": json.loads(r["types_json"]),
                "ann_date": r["ann_date"],
            }
            # Merge any extra raw_json fields
            if r["raw_json"]:
                try:
                    extra = json.loads(r["raw_json"])
                    entry.update(extra)
                except json.JSONDecodeError:
                    pass
            out[code] = entry
        return out
    finally:
        db.close()


def add_to_watchlist(
    code: str,
    name: str,
    types: list[str],
    ann_date: str,
    source_url: str = "",
    raw: dict[str, Any] | None = None,
) -> None:
    """
    Add stock to watchlist with N-day expiry.

    Same signature as post_watchlist_to_gas() but local.
    """
    now = datetime.now(HKT)
    expires = now + timedelta(days=WATCHLIST_EXPIRY_DAYS)

    db = get_db()
    try:
        db.execute(
            """
            INSERT OR REPLACE INTO scanner_watchlist
                (code, market, name, types_json, ann_date, source_url,
                 created_at, expires_at, active, raw_json)
            VALUES (?, 'HK', ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                code,
                name,
                json.dumps(types, ensure_ascii=False),
                ann_date,
                source_url,
                now.isoformat(timespec="seconds"),
                expires.strftime("%Y-%m-%d"),
                json.dumps(raw, ensure_ascii=False) if raw else None,
            ),
        )
        db.commit()
    finally:
        db.close()
    print(f"[local] watchlist +{code} ({', '.join(types)})")


# ── JSON Exports (dashboard) ────────────────────────────────────────────────────

def _export_alerts_json() -> Path:
    db = get_db()
    try:
        rows = db.execute(
            "SELECT payload_json FROM scanner_alerts ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        alerts = [json.loads(r["payload_json"]) for r in rows]
    finally:
        db.close()

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(alerts),
        "alerts": alerts,
    }
    path = DATA_DIR / "alerts.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


def export_watchlist_json() -> Path:
    """Export active watchlist for dashboard."""
    wl = fetch_watchlist()
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(wl),
        "watchlist": list(wl.values()),
    }
    path = DATA_DIR / "watchlist.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


def export_history_json(days: int = 30) -> Path:
    """Export alert history grouped by day for history.html."""
    db = get_db()
    try:
        rows = db.execute(
            """
            SELECT date(created_at) as day, payload_json
            FROM scanner_alerts
            WHERE created_at >= date('now', ?)
            ORDER BY created_at DESC
            """,
            (f"-{days} days",),
        ).fetchall()

        days_map: dict[str, list] = {}
        for r in rows:
            day = r["day"]
            if day not in days_map:
                days_map[day] = []
            days_map[day].append(json.loads(r["payload_json"]))

        days_out = [
            {"date": day, "alerts": alerts}
            for day, alerts in sorted(days_map.items(), reverse=True)
        ]
    finally:
        db.close()

    out = {
        "ok": True,
        "total": sum(len(d["alerts"]) for d in days_out),
        "days": days_out,
    }
    path = DATA_DIR / "history.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


def export_all() -> None:
    """Export all dashboard JSON files."""
    _export_alerts_json()
    export_watchlist_json()
    export_history_json()
    print("[local] exported alerts.json + watchlist.json + history.json")


# ── Init on import ─────────────────────────────────────────────────────────────

init_tables()
