"""Database connection helpers."""
from __future__ import annotations

import sqlite3
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "ccass.db"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
BACKUP_DIR = PROJECT_ROOT / "backups"


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if missing. Idempotent."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        # Migration: add top5_pct/top10_pct for existing DBs
        for col in ("top5_pct", "top10_pct"):
            try:
                conn.execute(f"ALTER TABLE ccass_daily ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass
        # Migration: add delta_60d_pct/delta_120d_pct for existing DBs
        for col in ("delta_60d_pct", "delta_120d_pct", "delta_60d_shares", "delta_120d_shares"):
            try:
                conn.execute(f"ALTER TABLE ccass_trends ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass
        # Migration: Sentinel Option A concentration metric columns
        for col in ("adj_hhi", "broker_top5_pct", "top_broker_id", "top_broker_name",
                    "top_broker_pct", "futu_pct", "a00005_pct", "adjusted_float"):
            col_type = "INTEGER" if col == "adjusted_float" else "TEXT" if col.endswith("_id") or col.endswith("_name") else "REAL"
            try:
                conn.execute(f"ALTER TABLE ccass_daily ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass


def backup_db(db_path: Path = DB_PATH) -> Path:
    """Backup DB before any migration (FATAL-002)."""
    if not db_path.exists():
        raise FileNotFoundError(f"No DB at {db_path}")
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"ccass.db.bak.{ts}"
    shutil.copy2(db_path, dest)
    return dest


@contextmanager
def get_conn(db_path: Path = DB_PATH):
    """Connection with WAL + foreign keys."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
