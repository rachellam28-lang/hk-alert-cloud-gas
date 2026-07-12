-- CCASS Tracker DB Schema
-- Design: per-stock-per-date flat tables plus participant-level caches.

CREATE TABLE IF NOT EXISTS ccass_daily (
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    total_shares INTEGER NOT NULL,
    total_pct REAL,
    num_participants INTEGER,
    top5_pct REAL,
    top10_pct REAL,
    adj_hhi REAL,
    broker_top5_pct REAL,
    top_broker_id TEXT,
    top_broker_name TEXT,
    top_broker_pct REAL,
    futu_pct REAL,
    a00005_pct REAL,
    adjusted_float INTEGER,
    scraped_at TEXT NOT NULL,
    validation_failed INTEGER DEFAULT 0,
    PRIMARY KEY (stock_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_ccass_daily_date ON ccass_daily(trade_date);

CREATE TABLE IF NOT EXISTS ccass_holdings (
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    participant_name TEXT,
    shares INTEGER NOT NULL,
    pct_of_issued REAL,
    PRIMARY KEY (stock_code, trade_date, participant_id)
);

CREATE INDEX IF NOT EXISTS idx_holdings_date ON ccass_holdings(trade_date);
CREATE INDEX IF NOT EXISTS idx_holdings_participant ON ccass_holdings(participant_id);
CREATE INDEX IF NOT EXISTS idx_holdings_stock_date ON ccass_holdings(stock_code, trade_date);

CREATE TABLE IF NOT EXISTS ccass_participant_deltas (
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    previous_date TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    participant_name TEXT,
    shares_previous INTEGER NOT NULL DEFAULT 0,
    shares_current INTEGER NOT NULL DEFAULT 0,
    shares_delta INTEGER NOT NULL DEFAULT 0,
    pct_previous REAL,
    pct_current REAL,
    pct_delta REAL,
    is_new INTEGER NOT NULL DEFAULT 0,
    is_exited INTEGER NOT NULL DEFAULT 0,
    abs_shares_delta INTEGER NOT NULL DEFAULT 0,
    abs_pct_delta REAL NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (stock_code, trade_date, participant_id)
);

CREATE INDEX IF NOT EXISTS idx_participant_deltas_date ON ccass_participant_deltas(trade_date);
CREATE INDEX IF NOT EXISTS idx_participant_deltas_participant ON ccass_participant_deltas(participant_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_participant_deltas_stock_date ON ccass_participant_deltas(stock_code, trade_date);

CREATE TABLE IF NOT EXISTS ccass_participant_anomalies (
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,
    participant_id TEXT NOT NULL DEFAULT '',
    participant_name TEXT,
    stock_name TEXT,
    previous_date TEXT,
    severity TEXT,
    score REAL NOT NULL DEFAULT 0,
    shares_delta INTEGER,
    pct_delta REAL,
    details_json TEXT,
    detected_at TEXT NOT NULL,
    PRIMARY KEY (stock_code, trade_date, anomaly_type, participant_id)
);

CREATE INDEX IF NOT EXISTS idx_participant_anomalies_date ON ccass_participant_anomalies(trade_date);
CREATE INDEX IF NOT EXISTS idx_participant_anomalies_type_date ON ccass_participant_anomalies(anomaly_type, trade_date);

CREATE TABLE IF NOT EXISTS ccass_trends (
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    delta_5d_pct REAL,
    delta_20d_pct REAL,
    delta_60d_pct REAL,
    delta_120d_pct REAL,
    delta_5d_shares INTEGER,
    delta_20d_shares INTEGER,
    delta_60d_shares INTEGER,
    delta_120d_shares INTEGER,
    consecutive_increase_days INTEGER,
    consecutive_decrease_days INTEGER,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (stock_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_trends_date ON ccass_trends(trade_date);

CREATE TABLE IF NOT EXISTS alerts_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'telegram'
);

CREATE INDEX IF NOT EXISTS idx_alerts_stock_date ON alerts_sent(stock_code, trade_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_dedup ON alerts_sent(stock_code, trade_date, alert_type);

CREATE TABLE IF NOT EXISTS stock_universe (
    stock_code TEXT PRIMARY KEY,
    stock_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date TEXT PRIMARY KEY,
    is_trading_day INTEGER NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS ccass_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    broker_from TEXT,
    broker_to TEXT,
    pct REAL NOT NULL,
    shares INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_stock_trade ON ccass_events(stock_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_events_alerted ON ccass_events(alerted);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stocks_attempted INTEGER,
    stocks_succeeded INTEGER,
    stocks_failed INTEGER,
    status TEXT NOT NULL,
    error_summary TEXT
);
