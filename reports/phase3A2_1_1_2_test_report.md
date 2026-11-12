# 阶段3A.2.1.1.2 测试报告

- 执行时间：2026-11-12
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 基线提交：`6c9fedf5a64674e53ce50c6b75b5640d92d31110`
- 执行方式：DSH 在当前工作区实际运行

## 一、全量测试结果（DSH 实际执行）

```powershell
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

| 项目 | 数值 |
| --- | ---: |
| 测试总数 | **310** |
| 通过 | **310** |
| 失败 | **0** |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 26.80s |
| 日志 | `logs/pytest_phase3a2_1_1_2.log` |

### 数量构成

| 来源 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过，无回退 |
| 阶段3A.2 | 55 | 全部通过 |
| 阶段3A.2.1 | 40 | 全部通过 |
| 阶段3A.2.1.1 | 27 | 全部通过 |
| 阶段3A.2.1.1.2 | **34** | 全部通过 |
| **合计** | **310** | **全部通过** |

原有 276 项**全部保留并通过**，未删除、未跳过、未弱化。

## 二、新增测试清单（34 项）

### 任务1：订单累计佣金（16 项）

| 测试 | 覆盖点 | 结果 |
| --- | --- | --- |
| `test_order_commission_uses_cumulative_amount` | 累计金额计算应收佣金 | 通过 |
| `test_incremental_commission_only_charges_difference` | 增量 = 应收 − 已收 | 通过 |
| `test_per_fill_model_charges_each_fill` | per_fill 对比模型 | 通过 |
| `test_invalid_commission_model_rejected` | 非法模型报错 | 通过 |
| `test_same_order_two_fills_charge_min_commission_once` | **测试1**：300+200 只收一次最低佣金 | 通过 |
| `test_same_order_three_fills_commission_increments` | **测试2**：三次成交增量正确 | 通过 |
| `test_fee_above_minimum_only_rate_after_threshold` | **测试3**：超门槛后只按费率 | 通过 |
| `test_different_orders_each_pay_min_commission` | **测试4**：不同订单各收一次 | 通过 |
| `test_partial_then_cancelled_fee_not_refunded` | **测试5**：已收费用不回退 | 通过 |
| `test_zero_fill_order_pays_nothing` | **测试6**：零成交零佣金 | 通过 |
| `test_buy_order_multi_fill_commission` | **测试7**：买单多次成交 | 通过 |
| `test_sell_order_multi_fill_commission` | **测试7**：卖单多次成交 | 通过 |
| `test_trade_fees_sum_equals_order_fee` | **测试8**：成交佣金和 == 订单 fee | 通过 |
| `test_portfolio_total_fees_equals_sum_of_trades` | **测试9**：Portfolio 累计费用一致 | 通过 |
| `test_completed_order_cannot_add_more_fee` | **测试10**：完成后不加费 | 通过 |
| `test_stamp_duty_and_transfer_fee_separate_from_min_commission` | 税费不参与最低佣金 | 通过 |

### 任务2：零碎股清仓（12 项）

| 测试 | 覆盖点 | 结果 |
| --- | --- | --- |
| `test_sell_quantity_liquidate_merges_odd_lot` | 清仓合并申报 | 通过 |
| `test_sell_quantity_partial_reduce_uses_whole_lots` | 部分减仓按整手 | 通过 |
| `test_sell_quantity_below_one_lot_partial` | 零股单独卖 | 通过 |
| `test_sell_quantity_never_exceeds_available` | 不超过可卖量 | 通过 |
| `test_liquidate_130400_no_residue` | 130,400 清仓无残留 | 通过 |
| `test_liquidate_537_full_clear` | 537 清仓 | 通过 |
| `test_liquidate_1237_full_clear` | 1,237 清仓 | 通过 |
| `test_partial_reduce_1237_keeps_737` | 1,237 卖 500 剩 737 | 通过 |
| `test_partial_reduce_537_then_clear_37` | 537→500→37 清掉 | 通过 |
| `test_liquidate_99_and_100` | 99 / 100 清仓 | 通过 |
| `test_no_tiny_residual_orders_from_float_error` | 浮点误差不生成残余单 | 通过 |
| `test_t_plus_one_still_enforced_on_liquidate` | 清仓仍守 T+1 | 通过 |
| `test_ledger_consistency_after_liquidation` | 账本一致 | 通过 |

### 任务3：统一统计口径（6 项）

| 测试 | 覆盖点 | 结果 |
| --- | --- | --- |
| `test_return_sample_stats_identity_holds` | 加总恒等式 | 通过 |
| `test_return_sample_stats_no_gap_all_valid` | 无缺口时有效 = 快照 − 1 | 通过 |
| `test_return_sample_stats_empty` | 空输入 | 通过 |
| `test_return_sample_stats_definition_tagged` | 口径版本标签 | 通过 |
| `test_sparse_evaluation_requires_additive_counts` | 不可加总判失败 | 通过 |

### 既有测试适配（1 项）

`test_sparse_evaluation_flags_bad_counts` 改为使用五参数接口并断言加总。
这是接口扩展后的必要同步，**不是弱化断言**：原断言「有效收益日超过快照天数判失败」，
现断言「加总不成立判失败」，覆盖面更广。

## 三、佣金模型实测对比（DSH 实际执行）

同一卖出订单，持仓 737 股分两日可卖（500 + 237）：

| 模型 | 第 1 笔 | 第 2 笔 | 订单累计 fee |
| --- | ---: | ---: | ---: |
| `per_order`（默认） | 5.0000 | 0.0000 | **5.0000** |
| `per_fill` | 5.00 | 5.00 | **10.00** |

累计成交金额 7,366.31 元，按 0.025% 费率 = 1.84 元 < 5 元最低佣金，
因此 `per_order` 应收 5.00 元，`per_fill` 多收一倍。

## 四、零碎股清仓实测（DSH 实际执行）

| 场景 | 委托 | 成交 | 剩余持仓 | 状态 |
| --- | ---: | ---: | ---: | --- |
| 持仓 130,400 清仓 | 130,400 | 130,400 | **0** | filled |
| 持仓 537 清仓 | 537 | 537 | **0** | filled |
| 持仓 1,237 清仓 | 1,237 | 1,237 | **0** | filled |
| 持仓 1,237 卖 500 | 500 | 500 | 737 | filled |
| 持仓 537 卖 500 | 500 | 500 | 37 | filled |
| 持仓 99 清仓 | 99 | 99 | **0** | filled |
| 持仓 100 清仓 | 100 | 100 | **0** | filled |

清仓链路：537 卖 500 → 剩 37 → 再清仓 37 → 剩 0，两步都正确。

## 五、全池 sparse_data 统一口径实测（DSH 实际执行）

### 5.1 代表性池（6 只）

| 项目 | 数值 |
| --- | ---: |
| 状态 | **success** |
| 删除零散 / 连续行 | 4,047 / 32 |
| 副本剩余行 | 112,530 |
| 快照天数 | **447** |
| ├ 首日无收益 | 1 |
| ├ 持仓缺口 | 88 + 88 = 176 |
| ├ 缺净值 | 0 |
| └ 有效日收益 | **270** |
| 加总恒等式 | **成立** |
| stale_price 标记数 | 544 |
| 订单 / 成交 / 部分 | 802 / 695 / 111 |
| **负现金天数** | **0** |
| 最终现金 | 10,005.71 |
| 源库指纹 | 前后一致 |

### 5.2 全池（41 只）

| 项目 | 数值 |
| --- | ---: |
| 状态 | **success** |
| 删除零散 / 连续行 | 4,047 / 32 |
| 副本剩余行 | 112,530 |
| 快照天数 | **447** |
| ├ 首日无收益 | 1 |
| ├ 持仓缺口 | 89 + 88 = 177 |
| ├ 缺净值 | 0 |
| └ 有效日收益 | **269** |
| 加总恒等式 | **成立** |
| stale_price 标记数 | 3,625 |
| 订单 / 成交 / 部分 | 2,117 / 1,244 / 216 |
| **负现金天数** | **0** |
| 最终现金 | 119,353.34 |
| 最终持仓 | 15 只 |
| 源库指纹 | 前后一致 |

### 5.3 口径一致性验证

两池均满足：

```text
447 = 1（首日） + 缺口 + 0（缺净值） + 有效
```

- 代表性池：`1 + 176 + 0 + 270 = 447` ✓
- 全池：`1 + 177 + 0 + 269 = 447` ✓

**不再出现 256/269 或 190/177 并存的情况**：本轮两池用同一 MA 窗口（MA60）与同一统计函数，
报告只输出可加总的统一口径。

### 5.4 历史数字差异的说明

上一阶段报告的 256 与 269 差异来源已查明：
验证流程用**样本内选出的 MA250**，独立复算脚本写死 **MA60**。
不同参数导致持仓结构、缺口日不同，数字理应不同。

这是**参数差异**，不是口径冲突。但报告同时列出两个数字而没说明，属表述缺陷。
本轮已改为所有路径统一调用 `return_sample_stats()`，并在报告中标注口径版本。

## 六、API 与 Streamlit 冒烟（DSH 实际执行）

| 检查 | 结果 |
| --- | --- |
| `GET /api/validations?limit=5` | 200 |
| `GET /api/validations/{id}` | 200 |
| `GET /api/validations/not_exist` | 404（期望） |
| `GET /health` | 200 |
| Streamlit `4_策略验证.py` AppTest | **0 异常** |

## 七、账本核对（DSH 实际执行）

| 检查 | 结果 |
| --- | --- |
| 代表性池负现金天数 | 0 |
| 全池负现金天数 | 0 |
| 成交记录佣金和 == 订单 fee | 通过（单测覆盖） |
| Portfolio.total_fees == 成交费用之和 | 通过（单测覆盖） |
| 订单 filled + remaining == quantity | 通过（3A.1.1 既有约束 + 本轮清仓测试） |

## 八、数据库检查（DSH 实际执行）

| 项目 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| `etf_pool` | 46（未变） |
| `etf_daily_prices` | 116,609（未变） |
| `etf_indicator_daily` | 350,292（未变） |
| `etf_adjustment_snapshots` | 139（未变） |
| `backtest_runs` | 11（未变） |
| `validation_runs` | 12（历史记录全部保留） |
| 数据库结构 | **无变更，无需迁移** |

## 九、静态代码审查（非运行测试）

- `sell_quantity()` 所有分支返回值均 `<= available`
- `incremental_commission()` 使用 `max(0.0, due - already)`，增量不会为负
- `_max_affordable()` 已改为按订单累计，不会因重复最低佣金低估可买量
- `return_sample_stats()` 的 `identity_holds` 由代码显式计算，不是硬编码 True

## 十、尚未验证的事项

1. **未用真实券商对账单核对 per_order 模型**：本项目公认这是模拟假设
2. **未模拟「同一委托跨营业日拆分」的券商侧费用规则**
3. **未对 sparse 删除比例做敏感性扫描**（固定每 5 日删 1 日 + 2 只连续缺 20 日）
4. **未测试并发执行多个验证任务**
5. **未验证 data-snapshot 跨机恢复**
6. **`sell_proceeds_below_fee` 防护分支未在真实数据触发**，仅 3A.2.1.1 单测覆盖

## 十一、结论

| 要求 | 实际 | 结论 |
| --- | --- | --- |
| 同单多次成交不重复收最低佣金 | 300+200 只收 5.00 | 满足 |
| 不同订单独立收佣金 | 各 5.00 | 满足 |
| 全部清仓不留残余 | 7 个场景剩余均为 0 | 满足 |
| 交易数量符合规则 | 清仓合并、减仓整手 | 满足 |
| 全池 sparse 统计统一可复核 | 加总恒等式成立 | 满足 |
| 负现金天数 | 0 | 满足 |
| 账本一致 | 全部通过 | 满足 |
| 276 项旧测试 | 全部保留并通过 | 满足 |
| 新增测试 | 34 项全部通过 | 满足 |
| 真实行情未污染 | 指纹前后一致 | 满足 |
| 历史 validation 完整 | 12 条全部保留 | 满足 |
