# 阶段3A.2.1.1.2.1.1 验证报告

- 生成时间：2026-11-12
- 范围：绩效总交易成本漏计税费修复
- **重要前提**：工程修复通过不代表任何策略具备实盘投资价值

## 1. 原始问题根因

上一阶段把 `Trade.commission` 从「全部费用」收窄为「纯佣金」，
但 `metrics.compute_performance()` 的 `total_cost` 公式未同步：

```python
result.total_cost = result.total_commission + result.total_slippage
#                  ↑ 现在只是佣金，不含印花税和过户费
```

**后果**：`total_cost` 漏掉印花税 + 过户费。

## 2. 修复前后对照

### 2.1 公式

| 版本 | 公式 |
| --- | --- |
| 修复前 | `total_cost = total_commission + total_slippage` |
| 修复后 | `total_cost = total_trade_fees + total_slippage`<br>`total_trade_fees = total_commission + total_stamp_tax + total_transfer_fee` |

### 2.2 字段

| 字段 | 修复前 | 修复后 |
| --- | --- | --- |
| `total_commission` | 佣金（语义正确） | 佣金（不变） |
| `total_stamp_tax` | **不存在** | **新增** |
| `total_transfer_fee` | **不存在** | **新增** |
| `total_trade_fees` | **不存在** | **新增** |
| `total_slippage` | 滑点（语义正确） | 滑点（不变） |
| `total_cost` | 佣金 + 滑点（漏税费） | 佣金 + 税费 + 滑点 |

### 2.3 实测示例

3 只 ETF、264 笔成交、非零税费：

| 指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| `total_commission` | 25,068.8621 | 25,068.8621 |
| `total_stamp_tax` | 未统计 | 50,041.1562 |
| `total_transfer_fee` | 未统计 | 1,000.8231 |
| `total_trade_fees` | 未统计 | 76,110.8414 |
| `total_slippage` | 47,320.2449 | 47,320.2449 |
| **`total_cost`** | **72,389.1069** | **123,431.0862** |
| 差异 | — | **+51,041.9793（漏计 41.4%）** |

## 3. 场景 A–E 实测

| 场景 | 输入 | 期望 | 实测 | 结果 |
| --- | --- | ---: | ---: | --- |
| A | 佣金6/印花10/过户0.2/滑点2 | 18.2 | **18.2** | ✅ |
| A' | 旧公式对照 | 8.0（漏 10.2） | 8.0 | ✅ 已证明 |
| B | 佣金5/滑点1/税费0 | 6.0 | **6.0** | ✅ |
| C | 三笔混合 | 30.80 | **30.80** | ✅ |
| D | 全 0 | 0 | **0** | ✅ |
| E | 同单两次成交 | 20.20（旧公式 10.0） | **20.20** | ✅ |

## 4. 成本统计位置全量核查

对 `total_cost` / `total_commission` / `total_fees` / `stamp_tax` /
`transfer_fee` / `slippage_cost` / `trade.commission` 全文搜索，共 9 处：

| # | 位置 | 修复前状态 | 处理 |
| ---: | --- | --- | --- |
| 1 | `metrics.compute_performance()` | ❌ 漏税费 | **已修** |
| 2 | `report` 绩效表 | ❌ 「总费用」实为佣金 | **改为分项列示** |
| 3 | `report` 交易明细表 | ❌ 只显示佣金 | **增加 4 列** |
| 4 | `validation.runner._metrics_payload()` | ✅ 复制 `performance.total_cost` | 自动沿用 |
| 5 | `scripts/run_backtest.py` | ✅ 打印 `performance.total_cost` | 自动沿用 |
| 6 | `scripts/report_backtest_3a.py` | ✅ 人工手算，不读 metrics | 无需改 |
| 7 | `portfolio.total_fees` | ✅ 累加传入三项和 | 无需改 |
| 8 | `api.get_trades()` | ✅ 直读数据库不汇总 | 无需改 |
| 9 | `dashboard/pages/3_回测.py` | ✅ 不展示成本汇总 | 无需改 |

**结论**：只有 1、2、3 需要改，全部已修。其余位置自动沿用或本就不涉及。

## 5. 历史费用语义兼容

### 5.1 历史记录实况

11 条历史回测的 `stamp_duty_rate` 与 `transfer_fee_rate` **实测全为 0.0**
（逐条核对 `config_json`）。因此旧 `total_cost = 佣金 + 滑点` 在数值上
等于真实总成本，**没有失真**。

### 5.2 兼容机制

```python
COST_SEMANTICS = "commission+taxes+slippage"
```

- 新回测 `summary_json["cost_semantics"] = COST_SEMANTICS`
- 历史记录无此字段 → 判定为 `legacy`
- `describe_cost_semantics()` 返回可读说明：
  - `legacy`：`includes_taxes=False`，附「当时税率为 0」的前提说明
  - 新语义：`includes_taxes=True`

**不猜测历史税费**：历史记录的 `stamp_tax` / `total_transfer_fee` 保持缺失，
不补造 0 也不补造数值。只通过标记区分口径。

### 5.3 历史记录未被修改

| 检查 | 结果 |
| --- | --- |
| `backtest_runs` 记录数 | 11（未变） |
| 历史 `summary_json` | **未修改** |
| 历史 `backtest_orders` | 29,248（未变） |
| 历史 `backtest_trades` | 26,093（未变） |
| 历史 `validation_runs` | 13（未变） |

## 6. 旧 322 项测试保留情况

| 分类 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过 |
| 阶段3A.2 | 55 | 全部通过 |
| 阶段3A.2.1 | 40 | 全部通过 |
| 阶段3A.2.1.1 | 27 | 全部通过 |
| 阶段3A.2.1.1.2 | 34 | 全部通过 |
| 阶段3A.2.1.1.2.1 | 12 | 全部通过 |
| **合计** | **322** | **全部保留并通过** |

无删除、无跳过、无弱化断言。

## 7. 新增测试

**15 项**（`tests/test_cost_aggregation.py`），全部通过。

## 8. 全量测试结果

```text
337 collected
337 passed
0 failed
0 skipped
1 warning（Starlette/httpx 弃用，非失败）
耗时 24.43s
```

日志：`logs/pytest_phase3a2_1_1_2_1_1.log`

## 9. 数据库前后完整性

| 项目 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| `etf_pool` | 46 |
| `etf_daily_prices` | 116,609 |
| `etf_indicator_daily` | 350,292 |
| `etf_adjustment_snapshots` | 139 |
| `backtest_runs` | 11 |
| `backtest_orders` | 29,248 |
| `backtest_trades` | 26,093 |
| `validation_runs` | 13 |
| 行情指纹 v3 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 数据库结构 | **无变更** |

**数据库无变化，无需重新生成 data-snapshot。**

## 10. 阶段验收结论

| 通过条件 | 实际 | 结论 |
| --- | --- | --- |
| `total_commission` 只统计佣金 | 佣金 3、税费 150 时仍为 3 | ✅ |
| `total_slippage` 只统计滑点 | 滑点 2、费用 150 时仍为 2 | ✅ |
| `total_cost` 含佣金+税费+滑点 | 18.2 / 30.80 / 20.20 / 123,431.09 | ✅ |
| 所有成本统计位置口径一致 | 9 处核查，3 处已修 | ✅ |
| 历史费用语义不被错误混合 | `cost_semantics` 标记 | ✅ |
| 原有 322 项保留并通过 | 322/322 | ✅ |
| 新增测试全部通过 | 15/15 | ✅ |
| 历史数据未被污染 | 记录数不变、指纹一致 | ✅ |

**全部满足，允许通过。**

## 11. 未完成事项和已知限制

1. **历史记录成本未重算**：遵守「历史结果不被覆盖」约束，用标记区分而非回刷
2. **未重跑历史 11 次回测**：其税率均为 0，`total_cost` 数值不变，重跑无信息增量
3. `total_cost` 只含可量化现金费用与滑点，不含冲击成本、机会成本
4. 滑点为固定 bp 近似，非真实成交价差
5. 未模拟跨营业日拆分计费的券商侧差异

## 12. 策略结论（未变）

**工程修复通过不代表策略有效。**

上一轮全池验证（`32aead3291734f91`）：

| 项目 | 样本内 | 样本外 |
| --- | ---: | ---: |
| 总收益 | -16.33% | 32.21% |
| Sharpe | 0.1058 | 0.7859 |

样本外基准对照：

| 基准 | 总收益 | Sharpe | 最大回撤 |
| --- | ---: | ---: | ---: |
| **等权买入持有** | **31.97%** | **0.8805** | **-18.58%** |
| MA250 趋势 | 32.21% | 0.7859 | 更大 |

趋势策略收益略高，但风险调整后未跑赢买入持有，且样本内普遍为负。
**不能宣布策略验证通过。** 历史回测收益不构成未来收益承诺。
