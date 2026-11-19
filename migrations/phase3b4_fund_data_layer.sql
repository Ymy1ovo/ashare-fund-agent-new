-- 阶段3B-4.0：场外公募基金数据层
-- 依据 reports/phase3B3_fund_data_feasibility.md 的 10 张表设计。
-- 只新增表与索引，不修改任何既有 ETF 行情/指标/回测/会计/公司行为表。
-- 全部语句均为 IF NOT EXISTS，可重复执行。

-- ---------------------------------------------------------------- 1. 基金本体
-- 一只基金一行；A/C/E/I 等份额不在本表，避免基金数量重复计数。
CREATE TABLE IF NOT EXISTS fund_master (
    fund_id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 主代码：用于对外引用。同一基金本体的其他份额代码在 fund_share_classes。
    fund_code_primary TEXT NOT NULL UNIQUE,
    fund_name TEXT NOT NULL,
    fund_full_name TEXT,
    fund_company TEXT,
    custodian TEXT,
    fund_type_l1 TEXT,
    fund_type_l2 TEXT,
    invest_scope TEXT,
    benchmark TEXT,
    -- 成立日期未知时为 NULL，禁止用抓取日期或当前日期顶替。
    established_date TEXT,
    -- 清盘日期未知时为 NULL，禁止根据申购状态推测。
    terminated_date TEXT,
    -- active / terminated / merged / unknown；无可靠证据时保持 unknown。
    lifecycle_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (lifecycle_status IN ('active', 'terminated', 'merged', 'unknown')),
    is_index_fund INTEGER,
    tracking_index TEXT,
    -- 归属不可靠时置 1，不得强行并入某个基金本体。
    needs_review INTEGER NOT NULL DEFAULT 0
        CHECK (needs_review IN (0, 1)),
    source TEXT NOT NULL,
    source_updated_at TEXT,
    ingested_at TEXT NOT NULL,
    data_version TEXT NOT NULL DEFAULT 'fund-v1'
);

CREATE INDEX IF NOT EXISTS idx_fund_master_name ON fund_master(fund_name);
CREATE INDEX IF NOT EXISTS idx_fund_master_company ON fund_master(fund_company);
CREATE INDEX IF NOT EXISTS idx_fund_master_review ON fund_master(needs_review);

-- ---------------------------------------------------------------- 2. 基金份额
-- 份额代码必须独立保存；同一基金本体可挂多个份额。
CREATE TABLE IF NOT EXISTS fund_share_classes (
    share_class_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL REFERENCES fund_master(fund_id) ON DELETE CASCADE,
    share_class_code TEXT NOT NULL UNIQUE,
    share_class_name TEXT NOT NULL,
    -- A / C / E / I / R / D / plain / unknown
    share_class_type TEXT NOT NULL DEFAULT 'unknown',
    currency TEXT NOT NULL DEFAULT 'CNY',
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    -- 费率未知时为 NULL，禁止填行业平均费率。
    management_fee REAL,
    custody_fee REAL,
    sales_service_fee REAL,
    min_purchase REAL,
    min_holding REAL,
    listed_date TEXT,
    terminated_date TEXT,
    source TEXT NOT NULL,
    source_updated_at TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE (fund_id, share_class_code)
);

CREATE INDEX IF NOT EXISTS idx_fund_share_fund ON fund_share_classes(fund_id);

-- ---------------------------------------------------------------- 3. 每日净值
-- 单位净值与累计净值分列，禁止混用。
-- 货币基金用 nav_kind='money_yield'，其 unit_nav/acc_nav 必须为 NULL。
CREATE TABLE IF NOT EXISTS fund_nav_daily (
    share_class_id INTEGER NOT NULL
        REFERENCES fund_share_classes(share_class_id) ON DELETE CASCADE,
    nav_date TEXT NOT NULL,
    nav_kind TEXT NOT NULL DEFAULT 'net_value'
        CHECK (nav_kind IN ('net_value', 'money_yield')),
    unit_nav REAL,
    acc_nav REAL,
    -- 货币基金专用：每万份收益与 7 日年化，不得写入 unit_nav。
    per_10k_yield REAL,
    seven_day_annual REAL,
    daily_return REAL,
    nav_status TEXT NOT NULL DEFAULT 'normal',
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (share_class_id, nav_date, nav_kind),
    -- 净值型必须有单位净值；货币型必须有每万份收益；两者互斥。
    CHECK (
        (nav_kind = 'net_value' AND unit_nav IS NOT NULL
            AND per_10k_yield IS NULL AND seven_day_annual IS NULL)
        OR
        (nav_kind = 'money_yield' AND per_10k_yield IS NOT NULL
            AND unit_nav IS NULL AND acc_nav IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_fund_nav_date ON fund_nav_daily(nav_date);

-- ---------------------------------------------------------------- 4. 分红
-- 同时保留每 10 份原始文本与归一化后的每份现金分红。
CREATE TABLE IF NOT EXISTS fund_dividends (
    dividend_id INTEGER PRIMARY KEY AUTOINCREMENT,
    share_class_id INTEGER NOT NULL
        REFERENCES fund_share_classes(share_class_id) ON DELETE CASCADE,
    record_date TEXT,
    ex_date TEXT NOT NULL,
    pay_date TEXT,
    -- 归一化：每份现金分红 = 每10份金额 / 10
    cash_per_share REAL NOT NULL,
    -- 原始文本，例如「每10份派现金0.2100元」，禁止只存归一化结果。
    per_10_raw TEXT NOT NULL,
    dividend_type TEXT NOT NULL DEFAULT 'cash',
    reinvest_nav REAL,
    source TEXT NOT NULL,
    source_updated_at TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE (share_class_id, ex_date, source)
);

CREATE INDEX IF NOT EXISTS idx_fund_div_exdate ON fund_dividends(ex_date);

-- ---------------------------------------------------------------- 5. 基金经理任职
CREATE TABLE IF NOT EXISTS fund_manager_history (
    manager_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL REFERENCES fund_master(fund_id) ON DELETE CASCADE,
    manager_name TEXT NOT NULL,
    company TEXT,
    -- 起止日期未知时为 NULL，禁止用当前日期伪造历史。
    start_date TEXT,
    end_date TEXT,
    tenure_days INTEGER,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fund_mgr_fund ON fund_manager_history(fund_id);
-- NULL 在 SQLite 的 UNIQUE 里视为互不相等，因此用表达式索引做幂等键。
CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_mgr_natural
    ON fund_manager_history(
        fund_id, manager_name, COALESCE(start_date, '__unknown__'));

-- ---------------------------------------------------------------- 6. 规模历史
CREATE TABLE IF NOT EXISTS fund_aum_history (
    aum_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER REFERENCES fund_master(fund_id) ON DELETE CASCADE,
    share_class_id INTEGER
        REFERENCES fund_share_classes(share_class_id) ON DELETE CASCADE,
    report_date TEXT NOT NULL,
    aum_total REAL,
    shares_total REAL,
    aum_unit TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    CHECK (fund_id IS NOT NULL OR share_class_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_fund_aum_report ON fund_aum_history(report_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_aum_natural
    ON fund_aum_history(
        COALESCE(fund_id, -1), COALESCE(share_class_id, -1), report_date, source);

-- ---------------------------------------------------------------- 7. 费率规则
-- 赎回费阶梯必须存 holding_days 区间；费率未知时 rate 允许 NULL。
CREATE TABLE IF NOT EXISTS fund_fee_rules (
    fee_rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    share_class_id INTEGER NOT NULL
        REFERENCES fund_share_classes(share_class_id) ON DELETE CASCADE,
    fee_type TEXT NOT NULL
        CHECK (fee_type IN ('purchase', 'redemption', 'sales_service',
                            'management', 'custody')),
    tier_order INTEGER NOT NULL DEFAULT 0,
    lower_bound REAL,
    upper_bound REAL,
    -- NULL 表示费率未知；禁止填行业平均值。
    rate REAL,
    -- 赎回费按持有天数分档。
    holding_days_min INTEGER,
    holding_days_max INTEGER,
    effective_from TEXT,
    effective_to TEXT,
    source TEXT NOT NULL,
    -- official_contract / official_announcement / third_party / unverified
    evidence_level TEXT NOT NULL DEFAULT 'unverified',
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fund_fee_class
    ON fund_fee_rules(share_class_id, fee_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_fee_natural
    ON fund_fee_rules(
        share_class_id, fee_type, tier_order,
        COALESCE(effective_from, '__na__'));

-- ---------------------------------------------------------------- 8. 申购赎回状态快照
-- 必须按日留快照；单次抓取只是当日状态，不能覆盖历史。
CREATE TABLE IF NOT EXISTS fund_subscription_status (
    status_id INTEGER PRIMARY KEY AUTOINCREMENT,
    share_class_id INTEGER NOT NULL
        REFERENCES fund_share_classes(share_class_id) ON DELETE CASCADE,
    as_of_date TEXT NOT NULL,
    purchase_status TEXT,
    redeem_status TEXT,
    daily_limit REAL,
    min_purchase REAL,
    next_open_date TEXT,
    -- 天天基金状态不等于支付宝可购买状态；无可靠证据时必须 unknown。
    alipay_purchasable TEXT NOT NULL DEFAULT 'unknown'
        CHECK (alipay_purchasable IN ('unknown', 'yes', 'no')),
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE (share_class_id, as_of_date, source)
);

CREATE INDEX IF NOT EXISTS idx_fund_status_date
    ON fund_subscription_status(as_of_date);

-- ---------------------------------------------------------------- 9. 生命周期事件
-- 成立、清盘、合并、份额变更都落这张表。清盘数据源当前缺失，先留结构。
CREATE TABLE IF NOT EXISTS fund_lifecycle_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL REFERENCES fund_master(fund_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('established', 'terminated', 'merged',
                              'share_change', 'renamed', 'unknown')),
    event_date TEXT,
    announcement_date TEXT,
    announcement_url TEXT,
    detail TEXT,
    successor_fund_id INTEGER REFERENCES fund_master(fund_id),
    -- official_announcement / third_party / unverified
    evidence_level TEXT NOT NULL DEFAULT 'unverified',
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fund_life_fund ON fund_lifecycle_events(fund_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_life_natural
    ON fund_lifecycle_events(
        fund_id, event_type, COALESCE(event_date, '__unknown__'), source);

-- ---------------------------------------------------------------- 10. 数据质量
CREATE TABLE IF NOT EXISTS fund_data_quality (
    quality_id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_key TEXT NOT NULL,
    check_name TEXT NOT NULL,
    -- ok / warning / failed / missing / mismatch
    status TEXT NOT NULL,
    detail TEXT,
    severity TEXT NOT NULL DEFAULT 'info'
        CHECK (severity IN ('info', 'warning', 'error')),
    checked_at TEXT NOT NULL,
    UNIQUE (table_name, record_key, check_name)
);

CREATE INDEX IF NOT EXISTS idx_fund_dq_status ON fund_data_quality(status);
CREATE INDEX IF NOT EXISTS idx_fund_dq_table ON fund_data_quality(table_name);
