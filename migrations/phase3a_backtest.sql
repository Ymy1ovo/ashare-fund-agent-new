-- 阶段3A：回测引擎数据表
-- 幂等：全部 CREATE TABLE IF NOT EXISTS，不修改任何既有表。

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    etf_codes TEXT NOT NULL,
    indicator_version TEXT,
    snapshot_ids TEXT,
    input_hash TEXT NOT NULL,
    summary_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_daily_nav (
    run_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    cash REAL NOT NULL,
    market_value REAL NOT NULL,
    total_assets REAL NOT NULL,
    nav REAL NOT NULL,
    daily_return REAL,
    price_status TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_date)
);

CREATE TABLE IF NOT EXISTS backtest_positions_daily (
    run_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    close_price REAL,
    market_value REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_date, code)
);

CREATE TABLE IF NOT EXISTS backtest_orders (
    run_id TEXT NOT NULL,
    order_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    order_date TEXT NOT NULL,
    fill_date TEXT,
    quantity INTEGER NOT NULL,
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    fill_price REAL,
    status TEXT NOT NULL,
    reason TEXT,
    deferred_days INTEGER NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0,
    slippage_cost REAL NOT NULL DEFAULT 0,
    reference_price REAL,
    target_weight REAL,
    strategy TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, order_id)
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    gross_amount REAL NOT NULL,
    commission REAL NOT NULL,
    slippage_cost REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    holding_days REAL,
    cash_after REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_id)
);

CREATE INDEX IF NOT EXISTS idx_bt_nav_run_date ON backtest_daily_nav(run_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_bt_orders_run ON backtest_orders(run_id, signal_date);
CREATE INDEX IF NOT EXISTS idx_bt_trades_run ON backtest_trades(run_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_bt_positions_run ON backtest_positions_daily(run_id, trade_date);
