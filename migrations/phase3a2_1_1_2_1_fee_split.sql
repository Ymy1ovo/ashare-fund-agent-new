-- 阶段3A.2.1.1.2.1：佣金与交易税费字段分离
-- 独立迁移，不删除旧字段，不覆盖历史记录。
-- 全部使用 ALTER TABLE ADD COLUMN，可重复执行（SQLite 无 IF NOT EXISTS 语法，
-- 由 db._migrate 的 PRAGMA table_info 检查保证幂等）。

-- 订单表：把佣金、印花税、过户费分开累计
-- commission 旧值时等于「全部交易费用」；历史回测的 stamp_duty_rate 与
-- transfer_fee_rate 均为 0，因此回填规则：commission = 旧 fee，税费 = 0。
-- 该回填只对「旧 fee 语义 = 佣金」的记录成立，见验收报告的口径说明。
ALTER TABLE backtest_orders ADD COLUMN commission REAL;
ALTER TABLE backtest_orders ADD COLUMN stamp_tax REAL;
ALTER TABLE backtest_orders ADD COLUMN transfer_fee REAL;

UPDATE backtest_orders
SET commission = fee
WHERE commission IS NULL;

UPDATE backtest_orders
SET stamp_tax = 0.0
WHERE stamp_tax IS NULL;

UPDATE backtest_orders
SET transfer_fee = 0.0
WHERE transfer_fee IS NULL;

-- 成交表：commission 只表示佣金，税费独立
ALTER TABLE backtest_trades ADD COLUMN stamp_tax REAL;
ALTER TABLE backtest_trades ADD COLUMN transfer_fee REAL;

UPDATE backtest_trades
SET stamp_tax = 0.0
WHERE stamp_tax IS NULL;

UPDATE backtest_trades
SET transfer_fee = 0.0
WHERE transfer_fee IS NULL;

CREATE INDEX IF NOT EXISTS idx_bt_trades_order
    ON backtest_trades(run_id, order_id);
