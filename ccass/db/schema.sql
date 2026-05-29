-- CCASS Tracker DB Schema
-- Design: per-stock-per-date flat table

-- 主表：每日每股 CCASS 總持倉
CREATE TABLE IF NOT EXISTS ccass_daily (
    stock_code TEXT NOT NULL,           -- '00700'
    trade_date TEXT NOT NULL,           -- 'YYYY-MM-DD'
    total_shares INTEGER NOT NULL,      -- CCASS 總持倉股數
    total_pct REAL,                     -- 佔已發行 %
    num_participants INTEGER,
    top5_pct REAL,
    top10_pct REAL,
    -- Sentinel Option A concentration metrics (ex-A00005)
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

-- Detail：每日每股每個 participant 持倉
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

-- Trend cache：5日/20日/60日/120日 持倉變化
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

-- Alerts log：避免重複 alert
CREATE TABLE IF NOT EXISTS alerts_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    alert_type TEXT NOT NULL,           -- 'spike_up' | 'spike_down' | 'consecutive_buy' | 'consecutive_sell'
    message TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'telegram'
);

CREATE INDEX IF NOT EXISTS idx_alerts_stock_date ON alerts_sent(stock_code, trade_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_dedup ON alerts_sent(stock_code, trade_date, alert_type);

-- Stock universe
CREATE TABLE IF NOT EXISTS stock_universe (
    stock_code TEXT PRIMARY KEY,
    stock_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    last_seen_at TEXT
);

-- Trading calendar
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date TEXT PRIMARY KEY,
    is_trading_day INTEGER NOT NULL,
    description TEXT
);

-- CCASS Events (Deposit / Transfer) — dedup via PK + alerted flag
CREATE TABLE IF NOT EXISTS ccass_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    event_type TEXT NOT NULL,           -- 'deposit' | 'transfer'
    broker_from TEXT,                    -- for transfer: losing broker
    broker_to TEXT,                      -- for transfer: gaining broker
    pct REAL NOT NULL,                   -- % of issued shares
    shares INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_stock_trade ON ccass_events(stock_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_events_alerted ON ccass_events(alerted);

-- Scrape run metadata
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stocks_attempted INTEGER,
    stocks_succeeded INTEGER,
    stocks_failed INTEGER,
    status TEXT NOT NULL,               -- 'running' | 'success' | 'partial' | 'failed'
    error_summary TEXT
);
