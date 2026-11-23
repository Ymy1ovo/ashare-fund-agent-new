-- ============================================================================
-- 阶段3B-6.0.2 指数与基准数据层
--
-- 只新增独立表，不触碰任何基金表（fund_*）、不触碰 ETF 行情表。
-- 全部语句 IF NOT EXISTS，可重复执行。
-- 指数历史与基金净值是两种完全不同的数据，物理隔离在不同表中。
-- ============================================================================

-- ---------------------------------------------------------------- 1. 指数基础信息
CREATE TABLE IF NOT EXISTS index_master (
    index_code TEXT PRIMARY KEY,
    index_name TEXT NOT NULL,
    index_short_name TEXT,
    -- 指数系列：csindex=中证/上证系列，cni=国证，sw=申万，hsi=恒生
    index_family TEXT,
    -- 发布机构（有证据才填）
    publisher TEXT,
    -- 数据来源接口标识，与 index_ingest_runs.source 对应
    data_source TEXT NOT NULL,
    -- 指数成立日期：只有来源明确给出才填，禁止用首行日期顶替
    inception_date TEXT,
    inception_date_evidence TEXT,
    frequency TEXT NOT NULL DEFAULT 'daily',
    currency TEXT NOT NULL DEFAULT 'CNY',
    -- 收益口径：price_return / total_return / net_total_return / unknown
    -- 不得仅凭名称或代码推断全收益口径
    return_basis TEXT NOT NULL DEFAULT 'unknown'
        CHECK (return_basis IN ('price_return', 'total_return',
                                'net_total_return', 'unknown')),
    return_basis_evidence TEXT,
    -- active / suspended / unknown
    data_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (data_status IN ('active', 'suspended', 'unknown')),
    -- 数据层就绪状态：ready 表示已入库且质量通过
    layer_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (layer_status IN ('pending', 'ready', 'degraded', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data_version TEXT NOT NULL DEFAULT 'index-v1'
);

CREATE INDEX IF NOT EXISTS idx_index_master_family
    ON index_master(index_family);
CREATE INDEX IF NOT EXISTS idx_index_master_basis
    ON index_master(return_basis);
CREATE INDEX IF NOT EXISTS idx_index_master_status
    ON index_master(layer_status);

-- ---------------------------------------------------------------- 3. 采集审计
CREATE TABLE IF NOT EXISTS index_ingest_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_code TEXT,
    source TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    request_start_date TEXT,
    request_end_date TEXT,
    requested_at TEXT NOT NULL,
    finished_at TEXT,
    -- success / failed / partial
    status TEXT NOT NULL
        CHECK (status IN ('success', 'failed', 'partial')),
    returned_rows INTEGER,
    actual_date_min TEXT,
    actual_date_max TEXT,
    error_type TEXT,
    error_message TEXT,
    -- 返回内容指纹，用于追溯同一请求是否内容变化
    content_fingerprint TEXT,
    -- full=首次全量，incremental=增量
    ingest_mode TEXT NOT NULL DEFAULT 'full'
        CHECK (ingest_mode IN ('full', 'incremental')),
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_code
    ON index_ingest_runs(index_code, requested_at);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_status
    ON index_ingest_runs(status);

-- ---------------------------------------------------------------- 2. 指数历史行情
CREATE TABLE IF NOT EXISTS index_daily (
    index_code TEXT NOT NULL
        REFERENCES index_master(index_code) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    -- 来源提供时的成交量/成交额，缺失为 NULL，不补 0
    volume REAL,
    amount REAL,
    source TEXT NOT NULL,
    -- 原始口径：raw=原始收盘，adjusted=来源已复权
    raw_basis TEXT NOT NULL DEFAULT 'raw',
    -- 该行属于哪一次采集
    run_id INTEGER REFERENCES index_ingest_runs(run_id) ON DELETE SET NULL,
    collected_at TEXT NOT NULL,
    -- 行内容指纹，用于识别实际内容变化
    row_fingerprint TEXT NOT NULL,
    -- valid / suspect / rejected
    quality_status TEXT NOT NULL DEFAULT 'valid'
        CHECK (quality_status IN ('valid', 'suspect', 'rejected')),
    quality_note TEXT,
    PRIMARY KEY (index_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_index_daily_date
    ON index_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_index_daily_quality
    ON index_daily(quality_status);
CREATE INDEX IF NOT EXISTS idx_index_daily_run
    ON index_daily(run_id);

-- ---------------------------------------------------------------- 4. 质量检查记录
CREATE TABLE IF NOT EXISTS index_quality_checks (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_code TEXT NOT NULL
        REFERENCES index_master(index_code) ON DELETE CASCADE,
    run_id INTEGER REFERENCES index_ingest_runs(run_id) ON DELETE SET NULL,
    checked_at TEXT NOT NULL,
    check_start_date TEXT,
    check_end_date TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    -- 各项检查结果：ok=1/fail=0
    date_parsed_ok INTEGER NOT NULL DEFAULT 0,
    date_ascending_ok INTEGER NOT NULL DEFAULT 0,
    duplicate_dates_ok INTEGER NOT NULL DEFAULT 0,
    null_close_ok INTEGER NOT NULL DEFAULT 0,
    numeric_ok INTEGER NOT NULL DEFAULT 0,
    ohlc_complete INTEGER NOT NULL DEFAULT 0,
    -- 缺口只报疑似，永远不判定为真实缺失
    suspected_gap_count INTEGER NOT NULL DEFAULT 0,
    suspected_gap_days INTEGER NOT NULL DEFAULT 0,
    calendar_proxy TEXT,
    calendar_note TEXT,
    -- 缺口是否可确认为真实缺失：恒为 NULL（无法确定）
    gap_is_real_missing INTEGER,
    -- 是否完整：硬性检查全过 + 无未确认缺口
    is_complete INTEGER NOT NULL DEFAULT 0,
    -- A / B / C / D（A 最好）
    quality_level TEXT NOT NULL DEFAULT 'D'
        CHECK (quality_level IN ('A', 'B', 'C', 'D')),
    degrade_reason TEXT,
    -- 完整检查明细 JSON，便于回溯
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_quality_code_time
    ON index_quality_checks(index_code, checked_at);
CREATE INDEX IF NOT EXISTS idx_quality_level
    ON index_quality_checks(quality_level);

-- ---------------------------------------------------------------- 5. 复合基准结构
CREATE TABLE IF NOT EXISTS benchmark_composite (
    composite_id INTEGER PRIMARY KEY AUTOINCREMENT,
    benchmark_name TEXT NOT NULL,
    benchmark_raw_text TEXT,
    -- 证据来源：contract / platform / inferred
    evidence_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (evidence_source IN ('contract', 'platform', 'inferred', 'unknown')),
    -- 是否所有成分都已接入数据层
    is_complete INTEGER NOT NULL DEFAULT 0,
    -- 是否可复现：必须所有成分齐全 + 权重齐全 + 现金成分有序列
    is_reproducible INTEGER NOT NULL DEFAULT 0,
    missing_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_composite_component (
    component_id INTEGER PRIMARY KEY AUTOINCREMENT,
    composite_id INTEGER NOT NULL
        REFERENCES benchmark_composite(composite_id) ON DELETE CASCADE,
    -- 成分类型：index / bond_index / cash / fixed_rate
    component_type TEXT NOT NULL
        CHECK (component_type IN ('index', 'bond_index', 'cash', 'fixed_rate')),
    -- 指数成分填代码，非指数成分留 NULL
    index_code TEXT REFERENCES index_master(index_code) ON DELETE SET NULL,
    -- 未识别的成分标签，原样保留
    component_label TEXT,
    weight REAL,
    weight_evidence TEXT,
    weight_effective_from TEXT,
    weight_effective_to TEXT,
    -- 该成分是否已具备可用收益序列
    data_available INTEGER NOT NULL DEFAULT 0,
    unavailable_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_composite_comp
    ON benchmark_composite_component(composite_id);
CREATE INDEX IF NOT EXISTS idx_composite_comp_code
    ON benchmark_composite_component(index_code);
