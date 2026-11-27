-- ============================================================================
-- 阶段3B-6.2.3.1.1 全收益指数独立原始数据层
--
-- **与 index_daily 完全物理隔离**：本迁移只新增 tr_* 前缀的独立表，
-- 不触碰 index_daily / index_master / 任何基金表。
--
-- 设计原则：
--   1. 原始数据原样归档，**不清洗、不插值、不修正**
--   2. 逐行质量标记，未验证行**不得默认标记为有效行情**
--   3. 候选注册表保留市场/口径/日历/连续性/真实起点等全部状态
--   4. 全部语句 IF NOT EXISTS，可重复执行
--   5. 回滚脚本见 phase3b6_2_3_1_1_total_return_layer_down.sql
-- ============================================================================

-- ---------------------------------------------------------------- 1. 候选注册表
CREATE TABLE IF NOT EXISTS tr_candidate_master (
    tr_code TEXT PRIMARY KEY,
    -- 对应价格指数代码（可追溯，非官方映射确认）
    price_index_code TEXT NOT NULL,
    -- 官方全称/简称（来自官方基本信息接口）
    official_full_name TEXT,
    official_short_name TEXT,
    -- 发布机构
    publisher TEXT,
    -- 官方基日与发布日期（两者不可混用）
    official_basic_date TEXT,
    official_publish_date TEXT,
    official_basic_index REAL,
    -- 市场分类：stock / bond / hk（三者严格隔离）
    market_group TEXT NOT NULL
        CHECK (market_group IN ('stock', 'bond', 'hk')),
    market_label TEXT,
    -- 收益口径（严格区分，不得混用）
    return_basis TEXT NOT NULL
        CHECK (return_basis IN ('gross_total_return', 'net_total_return',
                                'bond_clean_price',
                                'bond_interest_reinvestment', 'unknown')),
    -- 适用日历类型与可用性
    calendar_type TEXT NOT NULL,
    calendar_available INTEGER NOT NULL DEFAULT 0,
    calendar_is_official INTEGER NOT NULL DEFAULT 0,
    calendar_note TEXT,
    -- 映射证据（技术推断，非官方映射确认）
    mapping_verified INTEGER NOT NULL DEFAULT 0,
    mapping_evidence_level TEXT NOT NULL DEFAULT 'technical_inference'
        CHECK (mapping_evidence_level IN ('official_document',
                                          'technical_inference', 'none')),
    base_date_match INTEGER,
    -- 连续性等级（五态）
    continuity_level TEXT NOT NULL DEFAULT 'unknown'
        CHECK (continuity_level IN ('verified_official_calendar',
                                    'verified_against_proxy_calendar',
                                    'has_unresolved_suspicion',
                                    'has_issues', 'unknown')),
    -- 真实历史起点：未确认时必须为 unknown
    real_history_start TEXT NOT NULL DEFAULT 'unknown',
    synthetic_start_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (synthetic_start_status IN ('confirmed', 'strong_inference',
                                          'unknown')),
    -- 数据质量
    data_quality_verified INTEGER NOT NULL DEFAULT 0,
    non_positive_close_count INTEGER NOT NULL DEFAULT 0,
    -- 四个准入状态（本阶段全部保持审计结论，不得升级）
    raw_data_layer_ingest_candidate INTEGER NOT NULL DEFAULT 0,
    validated_series_candidate INTEGER NOT NULL DEFAULT 0,
    proxy_qualified_series_candidate INTEGER NOT NULL DEFAULT 0,
    formal_series_admitted INTEGER NOT NULL DEFAULT 0,
    -- 追溯：前置审计报告与原始证据
    source_audit_json TEXT,
    source_evidence_manifest TEXT,
    -- 数据版本
    layer_version TEXT NOT NULL DEFAULT 'tr-v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tr_master_market
    ON tr_candidate_master(market_group);
CREATE INDEX IF NOT EXISTS idx_tr_master_basis
    ON tr_candidate_master(return_basis);
CREATE INDEX IF NOT EXISTS idx_tr_master_continuity
    ON tr_candidate_master(continuity_level);

-- ---------------------------------------------------------------- 2. 原始证据表
CREATE TABLE IF NOT EXISTS tr_evidence_files (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 证据文件相对路径（相对项目根）
    relative_path TEXT NOT NULL UNIQUE,
    -- 证据类型：basic_info / history / control / manifest
    evidence_kind TEXT NOT NULL
        CHECK (evidence_kind IN ('basic_info', 'history', 'control',
                                 'manifest', 'other')),
    -- 该证据涉及的指数代码（对照文件为原价格指数代码）
    subject_code TEXT,
    bytes INTEGER,
    sha256 TEXT NOT NULL,
    -- 请求 URL 与采集时间（若有）
    request_url TEXT,
    obtained_at TEXT,
    -- 原始 manifest 校验状态：NULL=无原始 manifest 可校验
    original_manifest_sha256 TEXT,
    manifest_verified INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tr_evidence_kind
    ON tr_evidence_files(evidence_kind);
CREATE INDEX IF NOT EXISTS idx_tr_evidence_subject
    ON tr_evidence_files(subject_code);

-- ---------------------------------------------------------------- 3. 导入批次
CREATE TABLE IF NOT EXISTS tr_ingest_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 本阶段导入批次标识
    batch_key TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'success', 'failed', 'rolled_back')),
    candidate_count INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    -- 导入前后 index_daily 行数（用于证明未触碰）
    index_daily_before INTEGER,
    index_daily_after INTEGER,
    -- 导入前后 index_daily 内容指纹
    index_daily_fingerprint_before TEXT,
    index_daily_fingerprint_after TEXT,
    error_message TEXT,
    note TEXT
);

-- ---------------------------------------------------------------- 4. 原始历史行情
-- **逐行保留原始值**，不做任何清洗。
-- 主键 (tr_code, trade_date) 保证幂等。
CREATE TABLE IF NOT EXISTS tr_index_daily_raw (
    tr_code TEXT NOT NULL
        REFERENCES tr_candidate_master(tr_code) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    -- 原始字段，接口缺失即 NULL，**不补 0、不插值**
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    change REAL,
    change_pct REAL,
    cons_number REAL,
    peg REAL,
    -- 接口返回的指数代码与名称（可能与请求不同）
    returned_code TEXT,
    returned_name TEXT,
    -- 原始接口来源
    source_interface TEXT NOT NULL,
    request_url TEXT,
    -- 该行属于哪次导入
    run_id INTEGER REFERENCES tr_ingest_runs(run_id) ON DELETE SET NULL,
    -- 原始证据文件（可追溯到具体文件 + SHA256）
    evidence_relative_path TEXT,
    evidence_sha256 TEXT,
    -- 逐行质量标记（**默认不得为 normal_verified**）
    row_quality_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (row_quality_status IN (
            'normal_unverified',
            'suspected_synthetic',
            'suspected_market_closed_placeholder',
            'invalid_value',
            'unknown')),
    row_quality_note TEXT,
    -- 行内容指纹
    row_fingerprint TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (tr_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_tr_daily_date
    ON tr_index_daily_raw(trade_date);
CREATE INDEX IF NOT EXISTS idx_tr_daily_quality
    ON tr_index_daily_raw(row_quality_status);
CREATE INDEX IF NOT EXISTS idx_tr_daily_run
    ON tr_index_daily_raw(run_id);

-- ---------------------------------------------------------------- 5. 质量与连续性快照
CREATE TABLE IF NOT EXISTS tr_candidate_quality (
    quality_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tr_code TEXT NOT NULL
        REFERENCES tr_candidate_master(tr_code) ON DELETE CASCADE,
    run_id INTEGER REFERENCES tr_ingest_runs(run_id) ON DELETE SET NULL,
    checked_at TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    -- 逐行质量分布
    normal_unverified_count INTEGER NOT NULL DEFAULT 0,
    suspected_synthetic_count INTEGER NOT NULL DEFAULT 0,
    suspected_market_closed_count INTEGER NOT NULL DEFAULT 0,
    invalid_value_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    -- 覆盖与连续性（**无适用日历时必须 unknown**）
    coverage_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (coverage_status IN ('verified', 'has_gaps', 'unknown')),
    continuity_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (continuity_status IN ('verified_official_calendar',
                                     'verified_against_proxy_calendar',
                                     'has_unresolved_suspicion',
                                     'has_issues', 'unknown')),
    missing_trading_days INTEGER,
    dates_outside_calendar INTEGER,
    -- 真实历史起点（未确认时 unknown）
    real_history_start TEXT NOT NULL DEFAULT 'unknown',
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_tr_quality_code
    ON tr_candidate_quality(tr_code, checked_at);

-- ---------------------------------------------------------------- 6. 映射关系表
-- **技术映射推断，不是官方映射确认**
CREATE TABLE IF NOT EXISTS tr_price_index_mapping (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tr_code TEXT NOT NULL
        REFERENCES tr_candidate_master(tr_code) ON DELETE CASCADE,
    price_index_code TEXT NOT NULL,
    price_index_official_name TEXT,
    price_index_basic_date TEXT,
    tr_basic_date TEXT,
    base_date_match INTEGER,
    ratio_sample_count INTEGER,
    ratio_first REAL,
    ratio_last REAL,
    all_ratios_ge_one INTEGER,
    ratio_increasing INTEGER,
    ratio_equals_one_count INTEGER,
    mapping_verified INTEGER NOT NULL DEFAULT 0,
    evidence_level TEXT NOT NULL DEFAULT 'technical_inference'
        CHECK (evidence_level IN ('official_document',
                                  'technical_inference', 'none')),
    official_mapping_document_found INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tr_mapping_code
    ON tr_price_index_mapping(tr_code);
