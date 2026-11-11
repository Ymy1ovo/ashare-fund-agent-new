-- 阶段2：量化指标引擎数据库迁移
-- 实际运行时由 app/database/db.py 的 init_db() 幂等执行；
-- 本文件用于审阅和手工迁移参考。

CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS indicator_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    etf_code TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    indicator_config TEXT NOT NULL,
    adjustment_snapshot_id INTEGER,
    status TEXT NOT NULL,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    missing_rows INTEGER NOT NULL DEFAULT 0,
    calculation_version TEXT NOT NULL,
    summary_json TEXT,
    quality_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etf_indicator_daily (
    etf_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    adjustment_snapshot_id INTEGER NOT NULL,
    calculation_version TEXT NOT NULL,
    run_id TEXT NOT NULL,
    adjusted_close REAL,
    return_1d REAL,
    return_5d REAL,
    return_10d REAL,
    return_20d REAL,
    return_60d REAL,
    return_120d REAL,
    return_250d REAL,
    cagr REAL,
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma30 REAL,
    ma60 REAL,
    ma120 REAL,
    ma250 REAL,
    ema12 REAL,
    ema26 REAL,
    rsi6 REAL,
    rsi12 REAL,
    rsi24 REAL,
    macd_dif REAL,
    macd_dea REAL,
    macd_hist REAL,
    volatility_20d REAL,
    volatility_60d REAL,
    volatility_120d REAL,
    max_drawdown_20d REAL,
    max_drawdown_60d REAL,
    max_drawdown_120d REAL,
    max_drawdown_all REAL,
    atr14 REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    calmar_ratio REAL,
    price_status TEXT,
    trade_status TEXT,
    quality_status TEXT NOT NULL,
    quality_reasons TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (etf_code, trade_date, calculation_version, adjustment_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_indicator_daily_code_date
    ON etf_indicator_daily(etf_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_indicator_daily_code_version
    ON etf_indicator_daily(etf_code, calculation_version, trade_date);
CREATE INDEX IF NOT EXISTS idx_indicator_runs_code
    ON indicator_runs(etf_code, created_at);

-- 若 etf_indicator_daily 是旧版本表且缺少 adjusted_close，请执行：
-- ALTER TABLE etf_indicator_daily ADD COLUMN adjusted_close REAL;
