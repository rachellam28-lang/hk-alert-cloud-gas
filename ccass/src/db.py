"""Database connection helpers."""
from __future__ import annotations

import sqlite3
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
# Primary source of truth. Keep all runners/exporters on the same DB to avoid
# stale dashboard output from an empty legacy ccass.db.
DB_PATH = PROJECT_ROOT / "holdings.db"
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

        # Compatibility layer: keep legacy holdings_* names working against ccass_* tables.
        conn.executescript(
            """
            DROP VIEW IF EXISTS holdings_daily;
            DROP VIEW IF EXISTS holdings_holdings;
            DROP VIEW IF EXISTS holdings_trends;

            CREATE VIEW holdings_daily AS SELECT * FROM ccass_daily;
            CREATE VIEW holdings_holdings AS SELECT * FROM ccass_holdings;
            CREATE VIEW holdings_trends AS SELECT * FROM ccass_trends;

            DROP TRIGGER IF EXISTS holdings_daily_insert;
            DROP TRIGGER IF EXISTS holdings_daily_update;
            DROP TRIGGER IF EXISTS holdings_daily_delete;
            DROP TRIGGER IF EXISTS holdings_holdings_insert;
            DROP TRIGGER IF EXISTS holdings_holdings_update;
            DROP TRIGGER IF EXISTS holdings_holdings_delete;
            DROP TRIGGER IF EXISTS holdings_trends_insert;
            DROP TRIGGER IF EXISTS holdings_trends_update;
            DROP TRIGGER IF EXISTS holdings_trends_delete;

            CREATE TRIGGER holdings_daily_insert INSTEAD OF INSERT ON holdings_daily BEGIN
                INSERT INTO ccass_daily (
                    stock_code, trade_date, total_shares, total_pct, num_participants,
                    top5_pct, top10_pct, adj_hhi, broker_top5_pct, top_broker_id,
                    top_broker_name, top_broker_pct, futu_pct, a00005_pct, adjusted_float,
                    scraped_at, validation_failed
                ) VALUES (
                    NEW.stock_code, NEW.trade_date, NEW.total_shares, NEW.total_pct, NEW.num_participants,
                    NEW.top5_pct, NEW.top10_pct, NEW.adj_hhi, NEW.broker_top5_pct, NEW.top_broker_id,
                    NEW.top_broker_name, NEW.top_broker_pct, NEW.futu_pct, NEW.a00005_pct, NEW.adjusted_float,
                    NEW.scraped_at, COALESCE(NEW.validation_failed, 0)
                )
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                    total_shares = excluded.total_shares,
                    total_pct = excluded.total_pct,
                    num_participants = excluded.num_participants,
                    top5_pct = excluded.top5_pct,
                    top10_pct = excluded.top10_pct,
                    adj_hhi = excluded.adj_hhi,
                    broker_top5_pct = excluded.broker_top5_pct,
                    top_broker_id = excluded.top_broker_id,
                    top_broker_name = excluded.top_broker_name,
                    top_broker_pct = excluded.top_broker_pct,
                    futu_pct = excluded.futu_pct,
                    a00005_pct = excluded.a00005_pct,
                    adjusted_float = excluded.adjusted_float,
                    scraped_at = excluded.scraped_at,
                    validation_failed = excluded.validation_failed;
            END;

            CREATE TRIGGER holdings_daily_update INSTEAD OF UPDATE ON holdings_daily BEGIN
                UPDATE ccass_daily SET
                    total_shares = NEW.total_shares,
                    total_pct = NEW.total_pct,
                    num_participants = NEW.num_participants,
                    top5_pct = NEW.top5_pct,
                    top10_pct = NEW.top10_pct,
                    adj_hhi = NEW.adj_hhi,
                    broker_top5_pct = NEW.broker_top5_pct,
                    top_broker_id = NEW.top_broker_id,
                    top_broker_name = NEW.top_broker_name,
                    top_broker_pct = NEW.top_broker_pct,
                    futu_pct = NEW.futu_pct,
                    a00005_pct = NEW.a00005_pct,
                    adjusted_float = NEW.adjusted_float,
                    scraped_at = NEW.scraped_at,
                    validation_failed = NEW.validation_failed
                WHERE stock_code = OLD.stock_code AND trade_date = OLD.trade_date;
            END;

            CREATE TRIGGER holdings_daily_delete INSTEAD OF DELETE ON holdings_daily BEGIN
                SELECT RAISE(ABORT, 'Direct delete on holdings_daily view is disabled. Use ccass_daily table instead.');
            END;

            CREATE TRIGGER holdings_holdings_insert INSTEAD OF INSERT ON holdings_holdings BEGIN
                INSERT INTO ccass_holdings (
                    stock_code, trade_date, participant_id, participant_name, shares, pct_of_issued
                ) VALUES (
                    NEW.stock_code, NEW.trade_date, NEW.participant_id, NEW.participant_name, NEW.shares, NEW.pct_of_issued
                )
                ON CONFLICT(stock_code, trade_date, participant_id) DO UPDATE SET
                    participant_name = excluded.participant_name,
                    shares = excluded.shares,
                    pct_of_issued = excluded.pct_of_issued;
            END;

            CREATE TRIGGER holdings_holdings_update INSTEAD OF UPDATE ON holdings_holdings BEGIN
                UPDATE ccass_holdings SET
                    participant_name = NEW.participant_name,
                    shares = NEW.shares,
                    pct_of_issued = NEW.pct_of_issued
                WHERE stock_code = OLD.stock_code AND trade_date = OLD.trade_date AND participant_id = OLD.participant_id;
            END;

            CREATE TRIGGER holdings_holdings_delete INSTEAD OF DELETE ON holdings_holdings BEGIN
                DELETE FROM ccass_holdings
                WHERE stock_code = OLD.stock_code AND trade_date = OLD.trade_date AND participant_id = OLD.participant_id;
            END;

            CREATE TRIGGER holdings_trends_insert INSTEAD OF INSERT ON holdings_trends BEGIN
                INSERT INTO ccass_trends (
                    stock_code, trade_date, delta_5d_pct, delta_20d_pct, delta_60d_pct, delta_120d_pct,
                    delta_5d_shares, delta_20d_shares, delta_60d_shares, delta_120d_shares,
                    consecutive_increase_days, consecutive_decrease_days, computed_at
                ) VALUES (
                    NEW.stock_code, NEW.trade_date, NEW.delta_5d_pct, NEW.delta_20d_pct, NEW.delta_60d_pct, NEW.delta_120d_pct,
                    NEW.delta_5d_shares, NEW.delta_20d_shares, NEW.delta_60d_shares, NEW.delta_120d_shares,
                    NEW.consecutive_increase_days, NEW.consecutive_decrease_days, NEW.computed_at
                )
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                    delta_5d_pct = excluded.delta_5d_pct,
                    delta_20d_pct = excluded.delta_20d_pct,
                    delta_60d_pct = excluded.delta_60d_pct,
                    delta_120d_pct = excluded.delta_120d_pct,
                    delta_5d_shares = excluded.delta_5d_shares,
                    delta_20d_shares = excluded.delta_20d_shares,
                    delta_60d_shares = excluded.delta_60d_shares,
                    delta_120d_shares = excluded.delta_120d_shares,
                    consecutive_increase_days = excluded.consecutive_increase_days,
                    consecutive_decrease_days = excluded.consecutive_decrease_days,
                    computed_at = excluded.computed_at;
            END;

            CREATE TRIGGER holdings_trends_update INSTEAD OF UPDATE ON holdings_trends BEGIN
                UPDATE ccass_trends SET
                    delta_5d_pct = NEW.delta_5d_pct,
                    delta_20d_pct = NEW.delta_20d_pct,
                    delta_60d_pct = NEW.delta_60d_pct,
                    delta_120d_pct = NEW.delta_120d_pct,
                    delta_5d_shares = NEW.delta_5d_shares,
                    delta_20d_shares = NEW.delta_20d_shares,
                    delta_60d_shares = NEW.delta_60d_shares,
                    delta_120d_shares = NEW.delta_120d_shares,
                    consecutive_increase_days = NEW.consecutive_increase_days,
                    consecutive_decrease_days = NEW.consecutive_decrease_days,
                    computed_at = NEW.computed_at
                WHERE stock_code = OLD.stock_code AND trade_date = OLD.trade_date;
            END;

            CREATE TRIGGER holdings_trends_delete INSTEAD OF DELETE ON holdings_trends BEGIN
                DELETE FROM ccass_trends
                WHERE stock_code = OLD.stock_code AND trade_date = OLD.trade_date;
            END;
            """
        )


def backup_db(db_path: Path = DB_PATH) -> Path:
    """Backup DB before any migration (FATAL-002)."""
    if not db_path.exists():
        raise FileNotFoundError(f"No DB at {db_path}")
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"holdings.db.bak.{ts}"
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
