-- 阶段3B-4.2 场外基金关键历史数据正式入库：最小必要迁移
--
-- 只做「补字段」，不重构表、不改已有列类型、不删任何数据。
-- SQLite 的 ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，
-- 因此实际执行由 app/fund/migration_3b4_2.py 先查 PRAGMA 再逐列补；
-- 本文件作为可读的迁移文档与打包产物，与 phase3b4_fund_data_layer.sql 同一规范。
--
-- 场景：把 3B-4.1.1 已审计的 41 个场外结构清盘事件、12 只基金费率阶梯正式入库。
-- 原则：宁可留 NULL / unknown，也不为填满数据库制造数据。


-- ---------------------------------------------------------------- 生命周期事件
-- 现有列：event_id / fund_id / event_type / event_date / announcement_date /
--         announcement_url / detail / successor_fund_id / evidence_level /
--         source / ingested_at
--
-- 缺：公告 ID（可追溯原文）、产品结构（区分场内 ETF 与场外）、
--     事件指纹（跨来源稳定幂等键）、基金代码清单（多份额不重复成本体）。

ALTER TABLE fund_lifecycle_events ADD COLUMN announcement_id TEXT;
ALTER TABLE fund_lifecycle_events ADD COLUMN product_structure TEXT;
ALTER TABLE fund_lifecycle_events ADD COLUMN fund_codes TEXT;
ALTER TABLE fund_lifecycle_events ADD COLUMN event_fingerprint TEXT;
ALTER TABLE fund_lifecycle_events ADD COLUMN fetched_at TEXT;

-- 幂等：同一公告 = 同一事件。不同基金/不同公告不冲突。
CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_life_fingerprint
    ON fund_lifecycle_events(event_fingerprint)
    WHERE event_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fund_life_announcement
    ON fund_lifecycle_events(announcement_id);
CREATE INDEX IF NOT EXISTS idx_fund_life_structure
    ON fund_lifecycle_events(product_structure);


-- ---------------------------------------------------------------- 费率规则
-- 现有列：fee_rule_id / share_class_id / fee_type / tier_order /
--         lower_bound / upper_bound / rate / holding_days_min / holding_days_max /
--         effective_from / effective_to / source / evidence_level / ingested_at
--
-- 缺：区间开闭（「小于365天」vs「小于等于365天」）、下界是否推断、
--     原始费率与平台优惠费率分列、平台名、是否年化、
--     来源 URL / 来源名 / 抓取时间 / 持有期口径 / 说明。

ALTER TABLE fund_fee_rules ADD COLUMN lower_inclusive INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN upper_inclusive INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN lower_inferred INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN holding_days_min_inclusive INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN holding_days_max_inclusive INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN holding_days_min_inferred INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN rate_original REAL;
ALTER TABLE fund_fee_rules ADD COLUMN rate_platform REAL;
ALTER TABLE fund_fee_rules ADD COLUMN platform_name TEXT;
ALTER TABLE fund_fee_rules ADD COLUMN is_annual INTEGER;
ALTER TABLE fund_fee_rules ADD COLUMN holding_days_basis TEXT;
ALTER TABLE fund_fee_rules ADD COLUMN source_name TEXT;
ALTER TABLE fund_fee_rules ADD COLUMN source_url TEXT;
ALTER TABLE fund_fee_rules ADD COLUMN fetched_at TEXT;
ALTER TABLE fund_fee_rules ADD COLUMN detail TEXT;

CREATE INDEX IF NOT EXISTS idx_fund_fee_type
    ON fund_fee_rules(share_class_id, fee_type);
CREATE INDEX IF NOT EXISTS idx_fund_fee_platform
    ON fund_fee_rules(platform_name);
