# 阶段3A.2.1.1.2.1 验证报告

- 生成时间：2026-11-12
- 范围：佣金与交易税费累计混用修复
- **重要前提**：工程修复通过不代表任何策略具备实盘投资价值

## 1. 原始问题根因

### 1.1 缺陷

```python
fee = incremental_commission(
    cumulative_gross,
    order.fee,          # ← 传的是「全部费用」，不是「已收佣金」
    self.config.costs,
    fill_gross=gross,
)
stamp, transfer = taxes(gross, self.config.costs)
fee += stamp + transfer
```

`order.fee` 在每笔成交后都累加了印花税与过户费，
而 `incremental_commission()` 需要的是 `previously_paid_commission`。
税费被当成已收佣金，导致后续成交**少收佣金**。

### 1.2 量化影响

| 成交 | 累计金额 | 应收佣金 | 传入的已收 | 实际增量 | 应收增量 | 少收 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10,000 | 5.00 | 0 | 5.00 | 5.00 | 0 |
| 2 | 20,000 | 6.00 | 10.10 | **0.00** | **1.00** | **1.00** |

税费越高，误差越大。实测 3 只 ETF 的真实回测中，
264 笔成交的 `reconcile()` 期末现金差 **51,041.98 元**，正是被漏算的税费。

### 1.3 为什么之前没暴露

11 次历史回测的 `stamp_duty_rate` 与 `transfer_fee_rate` **全为 0**
（已实测 `backtest_runs.config_json` 确认），`order.fee` 恰等于佣金，缺陷被掩盖。

## 2. 修复前后的费用字段含义

### 2.1 Order

| 字段 | 修复前 | 修复后 |
| --- | --- | --- |
| `gross_amount` | 累计成交金额 | 不变 |
| `commission` | **不存在** | **累计佣金**（不含税费） |
| `stamp_tax` | **不存在** | 累计印花税 |
| `transfer_fee` | **不存在** | 累计过户费 |
| `fee` | 累计全部费用 | 累计全部费用（= 三项之和） |
| `slippage_cost` | 累计滑点 | 不变 |
| `total_fees` | 不存在 | **新增 property** |

### 2.2 Trade

| 字段 | 修复前 | 修复后 |
| --- | --- | --- |
| `commission` | **全部费用**（名实不符） | **只含佣金** |
| `stamp_tax` | **不存在** | 本笔印花税 |
| `transfer_fee` | **不存在** | 本笔过户费 |
| `total_fees` | 不存在 | **新增 property** |
| `slippage_cost` | 本笔滑点 | 不变 |

### 2.3 Portfolio

`total_fees` 语义不变，但接收值从「全部费用」改为「三项之和」，
现在可直接与 `sum(trade.total_fees)` 核对。

### 2.4 数据库

| 表 | 新增列 |
| --- | --- |
| `backtest_orders` | `commission`、`stamp_tax`、`transfer_fee` |
| `backtest_trades` | `stamp_tax`、`transfer_fee` |

旧列 `fee`（orders）与 `commission`（trades）**全部保留**，未删除。

## 3. 修复后的佣金累计公式

```python
cumulative_gross = order.gross_amount + gross

commission_due = max(cumulative_gross * commission_rate, min_commission)

commission_delta = max(0.0, commission_due - order.commission)

stamp    = gross * stamp_duty_rate
transfer = gross * transfer_fee_rate

fee = commission_delta + stamp + transfer
```

**关键**：第二个参数只传 `order.commission`。

## 4. 佣金与税费分离方式

| 费用 | 基数 | 最低佣金约束 | 累加字段 |
| --- | --- | --- | --- |
| 佣金 | 订单**累计**成交金额 | 是 | `order.commission` |
| 印花税 | 本笔成交金额 | 否 | `order.stamp_tax` |
| 过户费 | 本笔成交金额 | 否 | `order.transfer_fee` |
| 滑点 | 价差 × 数量 | 否 | `order.slippage_cost` |

每次成交后 `order.fee = order.total_fees`（分项累加后重算）。

**未修改**印花税、过户费的费率与征收规则（默认仍为 0），
仅修复佣金基数错误。

## 5. 场景 A–H 实际测试结果

| 场景 | 内容 | 实测 | 结果 |
| --- | --- | --- | --- |
| A | 卖单 10000+10000 | 佣金 5→+1，印花税 5+5=10，过户费 0.10+0.10=0.20，总 16.20 | ✅ |
| A' | 误用 fee 当基数 | 增量被压到 0.00；正确应为 1.00 | ✅ 已证明 |
| B | 100000+50000 | 佣金 30→+15，不重复收最低佣金 | ✅ |
| C | 三次成交 3000/5000/7000 | Trade 四项之和 == Order 四项 | ✅ |
| D | 买单两次部分成交 | 买入印花税 0，过户费累加正确，现金差额 < 1e-6 | ✅ |
| E | 两个订单 | 各收 5.00，合计 10.00，不共享 | ✅ |
| F | 部分成交后取消 | 已收佣金/印花税/过户费全保留，状态 partial | ✅ |
| G | 回测结束仍部分成交 | 未成交 300 股零费用 | ✅ |
| H | 账本一致性 | 四项 sum 全部相等，Portfolio 一致 | ✅ |

## 6. 订单费用与成交费用对账

### 6.1 单元测试（场景 C/H）

```text
sum(trade.commission)    == order.commission    ✅
sum(trade.stamp_tax)     == order.stamp_tax     ✅
sum(trade.transfer_fee)  == order.transfer_fee  ✅
sum(trade.total_fees)    == order.total_fees    ✅
```

### 6.2 真实数据回测（264 笔成交，非零税费）

| 核对项 | 值 | 一致 |
| --- | ---: | --- |
| `trade.commission` 和 | 25,068.862067 | ✅ |
| `order.commission` 和 | 25,068.862067 | ✅ |
| `trade.stamp_tax` 和 | 50,041.156176 | ✅ |
| `order.stamp_tax` 和 | 50,041.156176 | ✅ |
| `trade.transfer_fee` 和 | 1,000.823124 | ✅ |
| `order.transfer_fee` 和 | 1,000.823124 | ✅ |
| `trade.total_fees` 和 | 76,110.841367 | ✅ |
| `order.total_fees` 和 | 76,110.841367 | ✅ |

## 7. Portfolio 累计费用对账

| 核对 | 结果 |
| --- | --- |
| `portfolio.total_fees` = 期初 + `sum(trade.total_fees)` | ✅ 场景 H 通过 |
| `reconcile()` 期末现金推演 | ✅ True（修复前 False，差 51,041.98） |
| 每日 `cash >= -1e-6` | ✅ 两池 sparse 均 0 违规 |

## 8. 旧 310 项测试保留及通过情况

| 分类 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过 |
| 阶段3A.2 | 55 | 全部通过 |
| 阶段3A.2.1 | 40 | 全部通过 |
| 阶段3A.2.1.1 | 27 | 全部通过 |
| 阶段3A.2.1.1.2 | 34 | 全部通过 |
| **合计** | **310** | **全部通过，无删除、无跳过、无弱化** |

## 9. 新增测试数量

**12 项**（`tests/test_fee_split.py`），全部通过。

## 10. 全量测试结果

```text
322 collected
322 passed
0 failed
0 skipped
1 warning（Starlette/httpx 弃用，非失败）
耗时 23.34s
```

日志：`logs/pytest_phase3a2_1_1_2_1.log`

## 11. 数据库前后完整性

| 项目 | 修复前 | 修复后 |
| --- | ---: | ---: |
| `PRAGMA integrity_check` | ok | **ok** |
| 行情 | 116,609 | 116,609 |
| 指标 | 350,292 | 350,292 |
| 复权快照 | 139 | 139 |
| 历史回测 run | 11 | 11 |
| 订单 | 29,248 | 29,248 |
| 成交 | 26,093 | 26,093 |
| validation 记录 | 12 | 13（+1 新 id，历史 12 条完整） |
| 行情指纹 v3 | `d54727c0...ac49` | `d54727c0...ac49` |

**数据库结构有变化**（新增 5 列），因此重新生成了 data-snapshot（见交付文件）。

### 回填前提

11 次历史回测的 `stamp_duty_rate` 与 `transfer_fee_rate` **实测均为 0.0**，
旧 `fee` 在数值上等于佣金。据此把 `backtest_orders.commission` 回填为 `fee`。
29,248 条订单全部满足 `commission == fee`。

**不伪造声明**：如果存在「历史 fee 含税」的记录，该回填会失真。
本次已逐条核对配置确认为 0 税率，故回填成立。

## 12. 阶段验收结论

| 通过条件 | 实际 | 结论 |
| --- | --- | --- |
| 同单多次成交只按累计佣金算增量 | 场景 A/B/C 验证 | ✅ |
| 税费不计入已收佣金 | 场景 A 核心回归 | ✅ |
| 买卖费用规则正确 | 场景 D | ✅ |
| 不同订单最低佣金独立 | 场景 E | ✅ |
| Trade/Order/Portfolio 账本一致 | 场景 H + 264 笔真实数据 | ✅ |
| 原有 310 项保留并通过 | 310/310 | ✅ |
| 新增测试全部通过 | 12/12 | ✅ |
| 全量测试通过 | 322/322 | ✅ |
| 原始行情与历史记录未污染 | 指纹一致、记录数不变 | ✅ |

**全部满足，允许通过。**

## 13. 未完成事项和已知限制

1. **旧 `backtest_trades.commission` 语义变更**：历史行仍是「全部费用」，
   新行是「纯佣金」。当前下游（report、metrics）已按新语义处理，
   但若外部工具直接读该列需要留意。迁移文件与设计说明均已标注。
2. **per_order 佣金模型仍是模拟假设**，未与真实券商对账单核对。
3. 未模拟跨营业日拆分计费的券商侧差异。
4. 未做 sparse 删除比例敏感性扫描。
5. 未测试并发验证任务。
6. 涨跌停仍为整日近似。

## 14. 策略结论（未变）

工程修复通过**不代表策略有效**。

最新代表性池验证 `a04091b514ce4c4f` 结论仍为**不通过**。
上一轮全池样本外对照：

| 基准 | 总收益 | Sharpe | 最大回撤 |
| --- | ---: | ---: | ---: |
| **等权买入持有** | **31.97%** | **0.8805** | **-18.58%** |
| MA250 趋势 | 32.21% | 0.7859 | 更大 |

趋势策略风险调整后未跑赢买入持有，且样本内普遍为负。
历史回测收益不构成未来收益承诺。
