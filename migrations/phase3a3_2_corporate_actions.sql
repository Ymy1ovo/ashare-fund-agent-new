-- 阶段3A.3.2：公司行为事件表
-- 只新增表与索引，不修改任何既有表结构、不删除任何历史记录。

CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    share_ratio REAL,
    cash_per_share REAL,
    record_date TEXT,
    pay_date TEXT,
    source TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    data_version TEXT NOT NULL DEFAULT 'ca-v1',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(code, action_type, ex_date)
);

CREATE TABLE IF NOT EXISTS corporate_action_applications (
    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    action_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    action_type TEXT NOT NULL,
    shares_before INTEGER NOT NULL,
    shares_after INTEGER NOT NULL,
    cash_delta REAL NOT NULL DEFAULT 0,
    fractional_cash REAL NOT NULL DEFAULT 0,
    applied_at TEXT NOT NULL,
    UNIQUE(run_id, action_id)
);

CREATE INDEX IF NOT EXISTS idx_ca_code_effective
    ON corporate_actions(code, effective_date);
CREATE INDEX IF NOT EXISTS idx_ca_status ON corporate_actions(status);
CREATE INDEX IF NOT EXISTS idx_caa_run ON corporate_action_applications(run_id);
CREATE INDEX IF NOT EXISTS idx_caa_action ON corporate_action_applications(action_id);
