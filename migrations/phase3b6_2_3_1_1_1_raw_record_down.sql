-- ============================================================================
-- 阶段3B-6.2.3.1.1.1 原始记录逐行完整性字段（DOWN）
--
-- 删除本阶段新增的两列。**不删除表、不修改其他字段、不动任何行情数值。**
--
-- SQLite 的 ALTER TABLE DROP COLUMN 需要 3.35+，且不支持 IF EXISTS，
-- 因此由 tr_layer.rollback_raw_record_columns() 先检查列是否存在再执行本文件，
-- 以保证幂等。
-- ============================================================================

ALTER TABLE tr_index_daily_raw DROP COLUMN raw_record_sha256;

ALTER TABLE tr_index_daily_raw DROP COLUMN raw_record_json;
