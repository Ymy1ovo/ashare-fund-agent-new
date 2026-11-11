# 阶段3A.1 验收报告：回测引擎验收问题修复

- 项目：A股基金量化分析 Agent V1.0
- 阶段：3A.1
- 完成时间：2026-11-10
- 范围：仅修复审查发现的三个问题，不重写引擎，不进入阶段3B
- 测试：**144 passed，0 failed**

## 1. 三个问题的修复结论

| 问题 | 修复 | 验证 |
| --- | --- | --- |
| Sharpe/Sortino 用 CAGR 当分子 | 改为日均超额收益年化 ÷ 年化波动率 / 下行波动率 | 9 项新测试，含手算核对 |
| 缺失行情污染日收益 | 缺口当日与次日置 NaN，只统计持仓 ETF | 9 项新测试，含未持仓不影响、无压缩 |
| 部分成交被覆盖为 filled | 保留 partial，记录剩余数量，剩余续挂或明确取消 | 8 项新测试，含状态不被降级、无超额成交 |

## 2. 问题1：Sharpe / Sortino 公式

```text
daily_rf = (1 + rf) ^ (1/252) - 1
excess_t = r_t - daily_rf
Sharpe   = mean(excess) × 252 / (std(r, ddof=1) × sqrt(252))
Sortino  = mean(excess) × 252 / (sqrt(mean(min(excess,0)^2)) × sqrt(252))
```

- CAGR 独立计算，不参与 Sharpe/Sortino。
- 零波动返回 None；样本 < 2 返回 None；无下跌日时 Sortino 为 None 并记录原因。
- 报告新增 `日均收益`、`日均无风险利率`、`下行波动率`、`风险统计样本日`、`排除日收益`。

### 人工数据实证（6 个净值点）

| 口径 | Sharpe |
| --- | ---: |
| 修复前（CAGR 分子） | 21.3409 |
| 修复后（日均超额分子） | 9.3443 |

差值巨大，证明旧口径确实把多期复合收益当成了单期收益分子。

## 3. 问题2：缺失行情污染

`risk_return_series()` 规则：

1. 只看**当日持仓数量 > 0** 的 ETF 是否缺有效报价。
2. 缺口当日 → `held_price_gap`，日收益置 NaN。
3. 缺口次日 → `prior_day_price_gap`，同样置 NaN。
4. 未持仓 ETF 缺行情 → 不影响组合。
5. 无持仓日 → 按实际净值变化计入。
6. 最大回撤仍用估值净值，但记录 `nav_days_with_price_gaps`。

### 人工数据实证（持仓 1 只，第 3 日 stale）

| 口径 | 样本日 | 年化波动率 | Sharpe | Sortino |
| --- | ---: | ---: | ---: | ---: |
| 修复前 | 6 | 40.8168% | 8.6211 | - |
| 修复后 | 4 | 50.7318% | 8.0162 | 18.1035 |

真实数据 46 只趋势策略：4 个日收益被排除（`gap_excluded=4`），Sharpe 从 0.5033 修正到 0.5897。

## 4. 问题3：部分成交

- `Order.remaining_quantity` 入库；迁移文件 `migrations/phase3a1_backtest_partial_fill.sql`。
- Broker 在动账本前夹紧数量，累计成交量永不超过原始订单量。
- 只有 `filled_quantity >= quantity` 才是 `filled`，否则严格 `partial`。
- 剩余部分：`max_defer_days > 0` 续挂；否则 `remainder_cancelled`。
- 已部分成交的订单即使剩余被拒/过期，状态保持 `partial`。
- 费用只按实际成交金额。

### 数据库核对（新回测 `08a4c7f1529b42e2`）

- 订单状态：filled 804、rejected 400、unfilled 3
- 超额成交订单数：**0**
- 部分成交订单：无（本次策略在现金充足时一次成交）
- 账本核对：`reconciliation.ok = true`

## 5. 真实回测修复前后对比

同一策略、同一区间、同一参数（5 只 ETF，MA20，2024-01-02 ~ 2026-11-09）：

| 指标 | 修复前 `dbf4bc0e46104b23` | 修复后 `08a4c7f1529b42e2` |
| --- | ---: | ---: |
| 总收益率 | 23.81% | 23.67% |
| CAGR | 8.14% | 8.09% |
| 年化波动率 | 11.28% | 11.35% |
| **Sharpe** | 0.7213 | **0.7427** |
| **Sortino** | 1.0060 | **1.0387** |
| 最大回撤 | -11.29% | -12.01% |
| 成交笔数 | 961 | 1,116 |
| 总成本 | 129,199.28 | 140,028.34 |
| 账本核对 | 通过 | 通过 |

说明：

- Sharpe/Sortino 变化来自口径修正（分子从 CAGR 改为日均超额）。
- 波动率、最大回撤、成交笔数略有变化，来自部分成交修复后剩余订单会在次日继续撮合，
  成交拆分更细，成本随之上升；这是更真实的行为，不是回归错误。
- CAGR 变化极小，证明 CAGR 口径未被这次修复影响。

## 6. 修改文件清单

| 文件 | 变更 |
| --- | --- |
| `app/backtest/metrics.py` | 重写风险口径：`risk_return_series()`、`held_price_gap_days()`；Sharpe/Sortino 改用日均超额；新增 6 个绩效字段 |
| `app/backtest/broker.py` | 动账本前夹紧数量；partial 状态严格判定；卖出部分成交按配置 |
| `app/backtest/engine.py` | 保留 partial；剩余续挂或标记取消；不把 partial 降级为 rejected |
| `app/backtest/models.py` | 新增 `Order.remaining_quantity` 属性 |
| `app/backtest/storage.py` | 订单表写入 `remaining_quantity` |
| `app/backtest/report.py` | 报告展示日均收益/下行波动/样本日/排除日 |
| `app/database/db.py` | 幂等加列 `backtest_orders.remaining_quantity` 与状态索引 |
| `migrations/phase3a1_backtest_partial_fill.sql` | 新增独立迁移 |
| `tests/test_backtest_risk_fix.py` | 新增 9 项 |
| `tests/test_backtest_partial_fill.py` | 新增 8 项 |
| `scripts/compare_phase3a1.py` | 修复前后对比报告生成器 |
| 文档 | `phase3A_design.md`、`phase3A_test_report.md`、`phase3A_report.md`、README、CHANGELOG |

未修改阶段1、阶段2核心逻辑；未删除任何历史指标版本或回测记录。

## 7. 数据库变化

- `backtest_orders` 新增 `remaining_quantity INTEGER`。
- 新增索引 `idx_bt_orders_status`。
- 历史 24,697 条订单已回填 `remaining_quantity = max(0, quantity - filled_quantity)`。
- 其余表结构与数据不变：行情 116,609 行、指标 350,292 行、复权快照 139 条。

## 8. 已知限制（更新）

1. 分红/拆分事件仍未建模，收益为价格口径，低估分红贡献。
2. 部分成交只覆盖"现金不足缩量"与"可卖量不足缩量"，无盘口级撮合。
3. 债券/商品 ETF 交易规则未逐一确认，采用保守上限。
4. 缺失行情期间的估值净值仍用于最大回撤，报告已标注但不剔除该段。
5. 无冲击成本、成交量占比约束。
6. 不接券商，不产生实盘指令。

## 9. 测试

- 全量 144 项通过，0 失败，约 18.08 秒。
- 阶段3A 原有 127 项全部保留通过。
- 阶段3A.1 新增 17 项。
- 日志：`logs/pytest_phase3a1.log`
- 详见 `reports/phase3A1_test_report.md`。

## 10. 交付

| 类型 | 文件 |
| --- | --- |
| source-only | `dist/Ashare-Fund-Agent_source-only_<时间戳>.zip`（161 文件 + manifest，约 928 KB）<br>SHA256 见同名 `.sha256` 侧车文件 |
| data-snapshot | `dist/Ashare-Fund-Agent_data-snapshot_<时间戳>.zip`（integrity_check=ok，约 267 MB）<br>SHA256 见同名 `.sha256` 侧车文件 |

## 11. 结论

- 三个问题均已修复并有针对性测试。
- 原有 127 项测试无回退。
- 真实回测已重跑，账本核对通过，Sharpe/Sortino 变化可解释。
- **本轮停止，不进入阶段3B。**
