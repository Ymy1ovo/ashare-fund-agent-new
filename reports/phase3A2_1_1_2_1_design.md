# 阶段3A.2.1.1.2.1 设计说明：佣金与交易税费累计混用修复

- 编写时间：2026-11-12
- 基线提交：`b18395163358d3f5a329037bec830654a9303961`
- 范围：只修费用字段混用，不开发跨营业日收费、并发验证等新功能

## 1. 原始问题根因

### 1.1 缺陷代码

`app/backtest/broker.py`（修复前）：

```python
cumulative_gross = float(order.gross_amount) + gross
fee = incremental_commission(
    cumulative_gross,
    order.fee,          # ← 这里是「全部费用」，不是「佣金」
    self.config.costs,
    fill_gross=gross,
)
stamp, transfer = taxes(gross, self.config.costs)
fee += stamp + transfer
```

### 1.2 错误后果

`incremental_commission()` 的第二参数语义是 `previously_paid_commission`，
但传入的是 `order.fee`。而 `order.fee` 在每一笔后都加上了 `stamp + transfer`，
所以**税费被当成了已收佣金**。

实际后果：

| 步骤 | 累计金额 | 应收佣金 | 传入的「已收佣金」 | 计算的增量 | 正确增量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 第 1 笔（10,000 元，含税 5.10） | 10,000 | 5.00 | 0 | 5.00 | 5.00 |
| 第 2 笔（10,000 元） | 20,000 | 6.00 | 10.10（含税 5.10） | **0.00** | **1.00** |

第 2 笔应补收 1.00 元佣金，实际收了 0，**少收佣金 1.00 元**。
税费越高，误差越大。

### 1.3 为什么之前没暴露

项目历史 11 次回测的 `stamp_duty_rate` 与 `transfer_fee_rate` **全部为 0**，
`order.fee` 恰好等于佣金，所以缺陷一直隐藏。
一旦配置非零税费（如本次测试的 0.0005 / 0.00001），问题立即出现。

## 2. 修复前的费用字段含义（实测调用链）

### 2.1 Order 级

| 字段 | 修复前含义 | 更新位置 |
| --- | --- | --- |
| `gross_amount` | 累计成交金额 | `broker.py` `order.gross_amount += gross` |
| `fee` | **累计全部交易费用**（佣金+印花税+过户费） | `broker.py` `order.fee += fee` |
| `slippage_cost` | 累计滑点（不计入 fee） | `broker.py` |

**没有独立的佣金字段。**

### 2.2 Trade 级

| 字段 | 修复前含义 | 更新位置 |
| --- | --- | --- |
| `commission` | **全部交易费用**（佣金+印花税+过户费） | `broker.py` Trade 构造 |
| `slippage_cost` | 本笔滑点 | 同上 |

**`commission` 字段名与实际内容不符。**

### 2.3 Portfolio 级

| 字段 | 含义 | 更新位置 |
| --- | --- | --- |
| `total_fees` | 累计全部费用（接收的是 Trade 的 `fee` 参数） | `portfolio.apply_buy/apply_sell` |

### 2.4 数据库

| 表 | 字段 | 修复前 |
| --- | --- | --- |
| `backtest_orders` | `fee` | 全部费用 |
| `backtest_orders` | `commission` | **不存在** |
| `backtest_trades` | `commission` | 全部费用 |
| `backtest_trades` | `stamp_tax` | **不存在** |
| `backtest_trades` | `transfer_fee` | **不存在** |

### 2.5 可对账性结论

修复前 `sum(trade.commission) == order.fee` 成立（都是总费用），
但**无法把佣金与税费分开核对**，也无法验证「按累计金额算佣金」是否真的正确。

## 3. 修复后的费用字段模型

### 3.1 Order 级

| 字段 | 修复后含义 |
| --- | --- |
| `gross_amount` | 累计成交金额（不变） |
| `commission` | **累计佣金**（含最低佣金规则，不含税费） |
| `stamp_tax` | 累计印花税 |
| `transfer_fee` | 累计过户费 |
| `fee` | 累计全部交易费用 = `commission + stamp_tax + transfer_fee` |
| `slippage_cost` | 累计滑点（独立，不进 fee） |

新增 `Order.total_fees` property，返回三项之和。

### 3.2 Trade 级

| 字段 | 修复后含义 |
| --- | --- |
| `gross_amount` | 本笔成交金额 |
| `commission` | **本笔佣金**（只含佣金） |
| `stamp_tax` | 本笔印花税 |
| `transfer_fee` | 本笔过户费 |
| `total_fees` | 本笔全部费用（property） |
| `slippage_cost` | 本笔滑点（独立） |

### 3.3 Portfolio 级

`total_fees` 语义不变：累计收到的费用总和。现在接收的是**三项之和**，
因此 `portfolio.total_fees == sum(trade.total_fees)` 可直接核对。

### 3.4 数据库

新增列（独立迁移 `migrations/phase3a2_1_1_2_1_fee_split.sql`）：

| 表 | 新增列 |
| --- | --- |
| `backtest_orders` | `commission`、`stamp_tax`、`transfer_fee` |
| `backtest_trades` | `stamp_tax`、`transfer_fee` |

**未删除任何旧字段**，`fee` 与 `commission`（trades）保留。

**历史记录处理**：

- 历史回测的 `stamp_duty_rate = 0`、`transfer_fee_rate = 0`，
  旧 `fee` 在数值上就等于佣金；
- 迁移把 `backtest_orders.commission` 回填为 `fee`，`stamp_tax`/`transfer_fee` 回填 0；
- `backtest_trades.stamp_tax` / `transfer_fee` 回填 0；
- **不伪造**：如果将来有历史记录是「fee 含税」的，该回填会失真，
  因此迁移文件与本节都明确写了适用前提。

实测回填结果：29,248 条订单中 25,586 条 `fee > 0`，全部满足 `commission == fee`；
26,093 条成交的 `stamp_tax` 全为 0。

## 4. 修复后的佣金累计公式

```python
cumulative_gross = order.gross_amount + gross

commission_due = max(
    cumulative_gross * commission_rate,
    min_commission,
)

incremental_commission = max(
    0.0,
    commission_due - order.commission,   # ← 只减「已收佣金」
)

stamp   = gross * stamp_duty_rate
transfer = gross * transfer_fee_rate
fee = incremental_commission + stamp + transfer
```

关键点：**第二个参数只传 `order.commission`，绝不传 `order.fee`**。

## 5. 佣金与税费的分离方式

| 费用 | 计算基数 | 是否受最低佣金约束 | 更新位置 |
| --- | --- | --- | --- |
| 佣金 | **订单累计成交金额** | 是 | `order.commission += delta` |
| 印花税 | 本笔成交金额 | 否 | `order.stamp_tax += stamp` |
| 过户费 | 本笔成交金额 | 否 | `order.transfer_fee += transfer` |
| 滑点 | 价格差 × 数量 | 否 | `order.slippage_cost += slip` |

`order.fee = order.total_fees`（分项累加后重算，避免浮点漂移）。

滑点**已经包含在成交价里**，不再从现金中扣除，只作为独立绩效指标。

## 6. 每次成交的费用核算顺序

```text
1. gross = quantity × price
2. cumulative_gross = order.gross_amount + gross
3. commission_due = max(cumulative_gross × rate, min_commission)
4. commission_delta = max(0, commission_due − order.commission)
5. stamp = gross × stamp_duty_rate
6. transfer = gross × transfer_fee_rate
7. fee = commission_delta + stamp + transfer
8. (卖出) 若 gross − fee < 0 且现金不足 → 拒单
9. portfolio.apply_buy/sell(fee=fee, slippage_cost=slip)
10. Trade(commission=delta, stamp_tax=stamp, transfer_fee=transfer, ...)
11. order.commission += delta; order.stamp_tax += stamp
    order.transfer_fee += transfer; order.fee = order.total_fees
12. order.gross_amount += gross; order.slippage_cost += slip
```

## 7. 附带修正的三处一致性问题

| 问题 | 修复前 | 修复后 |
| --- | --- | --- |
| `_max_affordable()` 佣金基数 | 用 `order.fee` | 用 `order.commission` |
| `_max_affordable()` 现金约束 | 只算 `gross + 佣金` | 加上 `stamp + transfer` |
| `reconcile()` 期末现金推演 | `− trade.commission` | `− trade.total_fees` |

前两项不修会导致「可买数量算多了，实盘下单时现金不足」；
第三项不修会导致账本核对把税费差额误报为不一致。

## 8. 修改文件清单

| 文件 | 修改内容 |
| --- | --- |
| `app/backtest/models.py` | `Order` 增 `commission`/`stamp_tax`/`transfer_fee`/`total_fees`；`Trade` 增 `stamp_tax`/`transfer_fee`/`total_fees` |
| `app/backtest/broker.py` | 佣金基数改用 `order.commission`；税费独立字段；`_max_affordable` 纳入税费 |
| `app/backtest/metrics.py` | `reconcile()` 期末现金推演改用 `trade.total_fees`；增加税费非负检查 |
| `app/backtest/storage.py` | 订单与成交入库增加三个新字段 |
| `app/database/db.py` | SCHEMA 加列 + `_migrate` 幂等加列与回填 |
| `migrations/phase3a2_1_1_2_1_fee_split.sql` | 新增独立迁移 |
| `tests/test_fee_split.py` | **新增** 12 项场景测试 |

## 9. 不修改的部分

- 印花税率、过户费率的默认值与征收规则（仍为 0.0，可配置）
- 佣金费率与最低佣金默认值
- 滑点模型
- 现金非负检查
- 行情、指标、复权快照、历史回测、历史 validation 记录
- 策略逻辑

## 10. 已知限制

1. **历史记录的 commission 回填**依赖「旧 fee = 佣金」这一前提，
   该前提对现有数据成立（两个税率均为 0）。若将来引入含税历史数据，需重新评估。
2. `fee` 字段语义从「全部费用」延续为「全部费用」，但 `Trade.commission`
   语义从「全部费用」改为「只含佣金」——**这是语义变更**，
   旧的 `backtest_trades.commission` 行未改，仍是旧语义（等于当笔全部费用）。
   报告与迁移文件已注明。
3. 未模拟分笔成交的券商侧逐笔计费差异。
4. 涨跌停仍为整日近似。
