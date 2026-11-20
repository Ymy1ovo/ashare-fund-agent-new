-- 阶段3B-4.4 数据缺口补强：证据追溯列
--
-- 只补列，不改已有列、不删数据、不重建表。
-- 用途：把本轮从官方公告取得的费率生效时间、基金经理任职日期、
--       规模历史时点的来源与证据等级持久化，做到「不只有结论，还有证据」。
--
-- 执行由 app/fund/migration_3b4_4.py 完成（先查 PRAGMA table_info 再逐列补，
-- 保证可重复执行；SQLite 的 ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS）。

-- 基金经理任职历史：补来源追溯
ALTER TABLE fund_manager_history ADD COLUMN announcement_id TEXT;
ALTER TABLE fund_manager_history ADD COLUMN announcement_url TEXT;
ALTER TABLE fund_manager_history ADD COLUMN evidence_level TEXT;
ALTER TABLE fund_manager_history ADD COLUMN change_type TEXT;
ALTER TABLE fund_manager_history ADD COLUMN detail TEXT;

-- 规模历史：补来源追溯与「报告期末 vs 公告发布」区分
ALTER TABLE fund_aum_history ADD COLUMN announcement_id TEXT;
ALTER TABLE fund_aum_history ADD COLUMN announcement_url TEXT;
ALTER TABLE fund_aum_history ADD COLUMN evidence_level TEXT;
ALTER TABLE fund_aum_history ADD COLUMN disclosed_at TEXT;
ALTER TABLE fund_aum_history ADD COLUMN detail TEXT;

-- 费率规则：source_url / effective_from 已存在，仅补公告 ID 便于回源
ALTER TABLE fund_fee_rules ADD COLUMN announcement_id TEXT;

-- 索引：按公告回源、按证据等级筛
CREATE INDEX IF NOT EXISTS idx_fund_mgr_announcement
    ON fund_manager_history(announcement_id);
CREATE INDEX IF NOT EXISTS idx_fund_mgr_evidence
    ON fund_manager_history(evidence_level);
CREATE INDEX IF NOT EXISTS idx_fund_aum_evidence
    ON fund_aum_history(evidence_level);
CREATE INDEX IF NOT EXISTS idx_fund_fee_announcement
    ON fund_fee_rules(announcement_id);
CREATE INDEX IF NOT EXISTS idx_fund_fee_effective
    ON fund_fee_rules(effective_from, effective_to);
