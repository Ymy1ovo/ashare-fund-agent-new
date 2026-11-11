-- 阶段3A.1：回测订单增加「剩余未成交数量」列
-- 独立迁移，不修改既有表结构，不删除历史回测记录。

ALTER TABLE backtest_orders ADD COLUMN remaining_quantity INTEGER;

-- 回填历史数据：剩余 = 原始数量 - 累计成交，负值归零
UPDATE backtest_orders
SET remaining_quantity = MAX(0, quantity - filled_quantity)
WHERE remaining_quantity IS NULL;

CREATE INDEX IF NOT EXISTS idx_bt_orders_status
    ON backtest_orders(run_id, status);
