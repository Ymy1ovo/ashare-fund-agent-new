"""阶段3A.3.2.3.4.1：审计相关 DDL 集中定义。

拆出来避免 audit.py 继续膨胀，同时让 app/database/db.py 能复用同一份 DDL。
"""
from __future__ import annotations

# validation → 内部回测 关联表
VALIDATION_BACKTEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL,
    backtest_run_id TEXT NOT NULL,
    run_role TEXT NOT NULL,
    scenario_key TEXT,
    strategy_name TEXT,
    strategy_version TEXT,
    strategy_params_json TEXT,
    start_date TEXT,
    end_date TEXT,
    indicator_version TEXT,
    initial_cash REAL,
    codes_json TEXT,
    accounting_basis TEXT,
    formal_valuation INTEGER,
    input_hash TEXT,
    corporate_action_digest TEXT,
    applied_action_count INTEGER,
    receivable_count INTEGER,
    receivable_amount REAL,
    settled_count INTEGER,
    settled_amount REAL,
    detail_location TEXT,
    detail_note TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(validation_id, backtest_run_id)
);
CREATE INDEX IF NOT EXISTS idx_vbr_validation
    ON validation_backtest_runs(validation_id);
CREATE INDEX IF NOT EXISTS idx_vbr_run ON validation_backtest_runs(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_vbr_role ON validation_backtest_runs(run_role);
"""

# 市场环境分组统计
VALIDATION_REGIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_regime_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL,
    regime_label TEXT NOT NULL,
    proxy_code TEXT,
    status TEXT NOT NULL,
    total_days INTEGER,
    valid_days INTEGER,
    missing_days INTEGER,
    samples INTEGER,
    cumulative_return REAL,
    mean_daily_return REAL,
    annualized_volatility REAL,
    win_rate REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    cagr REAL,
    max_drawdown REAL,
    trade_count INTEGER,
    min_samples INTEGER,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(validation_id, regime_label)
);
CREATE INDEX IF NOT EXISTS idx_vrs_validation
    ON validation_regime_stats(validation_id);
"""

# 阶段3A.3.2.3.4.1：sparse 场景明细的主库独立审计存储区。
# 副本库会被删除，逐笔明细必须先在主库落地，且能按 run_id + action_id 复原。
SPARSE_DETAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_sparse_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    action_id INTEGER NOT NULL,
    code TEXT,
    effective_date TEXT,
    action_type TEXT,
    shares_before INTEGER,
    shares_after INTEGER,
    cash_delta REAL,
    fractional_cash REAL,
    applied_at TEXT,
    receivable_amount REAL,
    cash_paid_amount REAL,
    fractional_shares REAL,
    disposed_cost_basis REAL,
    realized_pnl REAL,
    official_ratio REAL,
    version_no INTEGER,
    event_fingerprint TEXT,
    source_db TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(validation_id, run_id, action_id)
);
CREATE INDEX IF NOT EXISTS idx_asa_validation
    ON audit_sparse_applications(validation_id);
CREATE INDEX IF NOT EXISTS idx_asa_run ON audit_sparse_applications(run_id);

CREATE TABLE IF NOT EXISTS audit_sparse_receivables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    action_id INTEGER NOT NULL,
    code TEXT,
    record_date TEXT,
    ex_date TEXT,
    pay_date TEXT,
    shares_at_ex INTEGER,
    cash_per_share REAL,
    amount REAL,
    status TEXT,
    settled_at TEXT,
    version_no INTEGER,
    event_fingerprint TEXT,
    source_db TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(validation_id, run_id, action_id)
);
CREATE INDEX IF NOT EXISTS idx_asr_validation
    ON audit_sparse_receivables(validation_id);
CREATE INDEX IF NOT EXISTS idx_asr_run ON audit_sparse_receivables(run_id);
"""

# 阶段3A.3.2.3.4.1：内部回测在 backtest_runs 里的存在性凭证。
# run_scope 区分「用户直接跑的回测」与「validation 内部回测」，
# 保证 list_runs / 盘点默认不把内部回测混进用户视图。
BACKTEST_RUN_SCOPE_COLUMN = ("run_scope", "TEXT NOT NULL DEFAULT 'standalone'")
