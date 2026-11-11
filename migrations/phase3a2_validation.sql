-- 阶段3A.2：策略可信度验证体系
-- 独立迁移，只新增表，不修改既有表结构，不删除历史回测记录。
-- 全部使用 CREATE TABLE IF NOT EXISTS，可重复执行。

CREATE TABLE IF NOT EXISTS validation_runs (
    validation_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    input_hash TEXT,
    etf_codes TEXT NOT NULL,
    excluded_codes TEXT,
    ma_window_grid TEXT NOT NULL,
    is_start TEXT,
    is_end TEXT,
    oos_start TEXT,
    oos_end TEXT,
    walkforward_config TEXT,
    benchmark_config TEXT,
    stress_config TEXT,
    status TEXT NOT NULL,
    conclusion TEXT,
    summary_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS validation_windows (
    validation_id TEXT NOT NULL,
    window_index INTEGER NOT NULL,
    train_start TEXT,
    train_end TEXT,
    test_start TEXT,
    test_end TEXT,
    train_days INTEGER,
    test_days INTEGER,
    selected_param INTEGER,
    status TEXT NOT NULL,
    reason TEXT,
    train_metrics_json TEXT,
    test_metrics_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (validation_id, window_index)
);

CREATE TABLE IF NOT EXISTS validation_grid (
    validation_id TEXT NOT NULL,
    ma_window INTEGER NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (validation_id, ma_window, phase)
);

CREATE TABLE IF NOT EXISTS validation_stress (
    validation_id TEXT NOT NULL,
    scenario_key TEXT NOT NULL,
    scenario_name TEXT,
    is_hypothetical INTEGER NOT NULL DEFAULT 1,
    config_json TEXT,
    status TEXT NOT NULL,
    metrics_json TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (validation_id, scenario_key)
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_status
    ON validation_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_validation_grid_phase
    ON validation_grid(validation_id, phase);
