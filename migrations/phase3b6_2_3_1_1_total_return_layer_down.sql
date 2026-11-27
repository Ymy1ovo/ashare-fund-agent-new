-- ============================================================================
-- 阶段3B-6.2.3.1.1 回滚脚本（仅删除本阶段新增的 tr_* 表）
--
-- **不触碰** index_daily / index_master / 任何基金表。
-- 执行顺序：先删子表，再删父表（外键依赖）。
-- ============================================================================

DROP TABLE IF EXISTS tr_price_index_mapping;
DROP TABLE IF EXISTS tr_candidate_quality;
DROP TABLE IF EXISTS tr_index_daily_raw;
DROP TABLE IF EXISTS tr_ingest_runs;
DROP TABLE IF EXISTS tr_evidence_files;
DROP TABLE IF EXISTS tr_candidate_master;
