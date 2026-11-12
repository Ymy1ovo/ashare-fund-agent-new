# 阶段3A.2.1.1.2.1 测试报告

- 执行时间：2026-11-12
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 基线提交：`b18395163358d3f5a329037bec830654a9303961`
- 执行方式：DSH 在当前工作区实际运行

## 一、测试总数分解

```powershell
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

| 分类 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过 |
| 阶段3A.2 | 55 | 全部通过 |
| 阶段3A.2.1 | 40 | 全部通过 |
| 阶段3A.2.1.1 | 27 | 全部通过 |
| 阶段3A.2.1.1.2 | 34 | 全部通过 |
| **原有小计** | **310** | **全部保留并通过** |
| **本次新增**（`test_fee_split.py`） | **12** | **全部通过** |
| **全量合计** | **322** | **全部通过** |

| 项目 | 数值 |
| --- | ---: |
| 收集测试 | 322 |
| 通过 | **322** |
| 失败 | **0** |
| 跳过 | **0** |
| 未执行 | **0** |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 23.34s |
| 日志 | `logs/pytest_phase3a2_1_1_2_1.log` |

**原有 310 项全部保留**：未删除、未跳过、未降低断言。
唯一变化是从 310 增到 322，新增 12 项。

## 二、新增测试清单（12 项，覆盖场景 A–H）

| # | 测试 | 场景 | 覆盖点 | 结果 |
| ---: | --- | --- | --- | --- |
| 1 | `test_scenario_a_two_fills_split_fees_correctly` | A | 10000+10000，佣金 5→+1，税费分笔 | 通过 |
| 2 | `test_scenario_a_exact_values_with_fixed_amounts` | A | 精确数值：佣金 6 / 印花税 10 / 过户费 0.20 / 总 16.20 | 通过 |
| 3 | `test_fee_not_misused_as_commission_base` | A | **核心回归**：误用 fee 会少收佣金 | 通过 |
| 4 | `test_scenario_b_above_threshold_no_min_commission_repeat` | B | 100000+50000，佣金 30→+15 | 通过 |
| 5 | `test_scenario_c_three_fills_trade_sums_match_order` | C | 三次成交，Trade 和 == Order | 通过 |
| 6 | `test_scenario_d_buy_order_fees` | D | 买单两次成交，买入无印花税 | 通过 |
| 7 | `test_scenario_e_different_orders_independent` | E | 两订单各收最低佣金 | 通过 |
| 8 | `test_scenario_f_partial_then_cancel_keeps_fees` | F | 取消后已收费用保留 | 通过 |
| 9 | `test_scenario_g_unfilled_portion_pays_nothing` | G | 未成交不产生费用 | 通过 |
| 10 | `test_scenario_h_ledger_reconciliation` | H | Trade 和 == Order；Portfolio 一致 | 通过 |
| 11 | `test_order_fee_equals_component_sum` | H | fee == commission + stamp + transfer | 通过 |
| 12 | `test_zero_fee_config_keeps_commission_only` | 兼容 | 税费为 0 时行为与旧模型一致 | 通过 |

## 三、场景 A 精确数值核对

### 3.1 约定费率

```text
佣金费率 0.0003    最低佣金 5 元
印花税   0.0005    过户费   0.00001
```

### 3.2 理论值

| 成交 | 金额 | 累计金额 | 累计应收佣金 | 已收佣金 | **本次佣金** | 印花税 | 过户费 | 本次总费用 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10,000 | 10,000 | max(3, 5) = 5 | 0 | **5** | 5.00 | 0.10 | 10.10 |
| 2 | 10,000 | 20,000 | max(6, 5) = 6 | 5 | **1** | 5.00 | 0.10 | 6.10 |
| 合计 | 20,000 | — | 6 | — | **6** | 10.00 | 0.20 | **16.20** |

**实测结果与理论值完全一致**（`test_scenario_a_exact_values_with_fixed_amounts` 通过）。

### 3.3 核心回归测试

```python
# 错误写法：用「含税费的 fee」当已收佣金
wrong_base = 5.0 + 5.0 + 0.10   # = 10.10
wrong = incremental_commission(20_000, wrong_base, ...)   # → 0.00

# 正确写法：只用已收佣金
right = incremental_commission(20_000, 5.0, ...)          # → 1.00
```

测试断言 `right > wrong`，证明**混用税费会导致少收佣金**。
这正是本次修复的核心缺陷。

## 四、场景 B 核对

| 成交 | 金额 | 累计金额 | 应收佣金 | 已收 | 本次佣金 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 100,000 | 100,000 | 30.00 | 0 | **30.00** |
| 2 | 50,000 | 150,000 | 45.00 | 30.00 | **15.00** |

税费：印花税 50 + 25 = 75；过户费 1.0 + 0.5 = 1.5。
不重复收最低佣金（首笔已超门槛）。

## 五、场景 D 买单核对

| 项目 | 数值 |
| --- | --- |
| 首笔成交 | 部分成交（现金只够部分） |
| 买入印花税 | **0.00**（不误收卖出专属税费） |
| 买入过户费 | > 0 |
| 累计佣金 | 等于 `order_commission(order.gross_amount)` |
| 现金变化 | `成交金额 + 佣金 + 过户费`（实测差额 < 1e-6） |

## 六、场景 E/F/G/H 核对

| 场景 | 关键断言 | 结果 |
| --- | --- | --- |
| E 不同订单 | 两订单各收 5.00，合计 10.00，不共享额度 | 通过 |
| F 部分成交后取消 | 已收佣金/印花税/过户费全部保留，订单状态 `partial` | 通过 |
| G 回测结束时部分成交 | 未成交 300 股不产生任何费用 | 通过 |
| H 账本一致性 | `sum(trade.commission) == order.commission` 等四项全部成立 | 通过 |

## 七、真实数据回测对账（DSH 实际执行）

配置：非零税费（印花税 0.0005、过户费 0.00001），3 只 ETF，2025-01-02 ~ 2026-11-09。

| 核对项 | 结果 |
| --- | --- |
| 成交数 / 订单数 | 264 / 276 |
| `trade.commission` 和 vs `order.commission` 和 | 25,068.862067 == 25,068.862067 ✅ |
| `trade.stamp_tax` 和 vs `order.stamp_tax` 和 | 50,041.156176 == 50,041.156176 ✅ |
| `trade.transfer_fee` 和 vs `order.transfer_fee` 和 | 1,000.823124 == 1,000.823124 ✅ |
| `trade.total_fees` 和 vs `order.total_fees` 和 | 76,110.841367 == 76,110.841367 ✅ |
| `reconcile()` 期末现金推演 | **True**（修复前为 False，差 51,041.98） |
| 佣金 / 税费比 | 0.49（税费远大于佣金，符合 0.0005 vs 0.00025 费率） |

修复前 `reconcile` 报错 `期末现金推演不一致：79538.1931 vs 28496.2138`，
差值 51,041.98 正是被漏算的印花税 + 过户费。修复后一致。

## 八、Sparse_data 回归（DSH 实际执行）

| 项目 | 代表性池（6 只） | 全池（41 只） |
| --- | ---: | ---: |
| 状态 | **success** | **success** |
| 删除行情行 | 4,079 | 4,079 |
| 快照天数 | 447 | 447 |
| 首日 / 缺口 / 缺净值 / 有效 | 1 / 176 / 0 / **270** | 1 / 177 / 0 / **269** |
| 加总恒等式 | 成立 | 成立 |
| 订单 / 成交 | 802 / 695 | 2,117 / 1,244 |
| **负现金天数** | **0** | **0** |
| 源库指纹 | 前后一致 | 前后一致 |

统计口径与上一轮完全一致（`return-sample-stats-v1`），无数字漂移。

## 九、代表性池完整验证（DSH 实际执行）

| 项目 | 值 |
| --- | --- |
| validation_id | `a04091b514ce4c4f`（**新 id，未覆盖历史**） |
| 结论 | 不通过 |
| ETF 数 | 6 |
| 压力场景 | base/cost_plus_50/cost_plus_100/slippage_x2/slippage_x3 全部 success |
| sparse_data | success |
| insufficient | insufficient（预期） |

## 十、API 与 Streamlit 冒烟（DSH 实际执行）

| 检查 | 结果 |
| --- | --- |
| `GET /api/validations?limit=5` | 200 |
| `GET /api/validations/{id}` | 200 |
| `GET /api/validations/not_exist` | 404（期望） |
| `GET /health` | 200 |
| Streamlit `4_策略验证.py` AppTest | **0 异常** |

## 十一、数据库完整性（DSH 实际执行）

| 项目 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| `PRAGMA integrity_check` | ok | **ok** |
| `etf_pool` | 46 | 46 |
| `etf_daily_prices` | 116,609 | 116,609 |
| `etf_indicator_daily` | 350,292 | 350,292 |
| `etf_adjustment_snapshots` | 139 | 139 |
| `backtest_runs` | 11 | 11 |
| `backtest_orders` | 29,248 | 29,248 |
| `backtest_trades` | 26,093 | 26,093 |
| `validation_runs` | 12 | 13（新增 1 条，历史 12 条保留） |
| 行情指纹 v3 | `d54727c0...ac49` | `d54727c0...ac49`（**一致**） |

### 回填结果

| 检查 | 结果 |
| --- | ---: |
| `backtest_orders.commission` 非零 | 25,586 |
| `backtest_orders.fee` 非零 | 25,586 |
| `commission == fee` 的行数 | **29,248（全部）** |
| `backtest_trades.stamp_tax` 全为 0 | 26,093 |

回填正确性依赖「历史 fee 语义 = 佣金」，该前提对现有数据成立
（11 次历史回测的 `stamp_duty_rate` 与 `transfer_fee_rate` 均为 0，已实测确认）。

## 十二、静态代码审查（非运行测试）

- `broker.py` 中 `incremental_commission()` 第二个参数已是 `order.commission`，
  全文搜索确认无 `order.fee` 作为佣金基数
- `order.fee = order.total_fees` 在每次成交后重算，不会浮点漂移累积
- `Trade.total_fees` 与 `Order.total_fees` 均为 property，非独立存储字段
- `reconcile()` 已把税费纳入现金推演

## 十三、未执行或未覆盖

1. **未验证真实券商对账单**：per_order 佣金模型仍是模拟假设
2. **未测试旧 `backtest_trades.commission` 语义变更的下游影响**：
   该字段对历史行仍是「全部费用」语义，新行是「纯佣金」。
   当前只有 report 与 metrics 使用它，两者都已按新语义处理
3. **未做跨营业日拆分计费测试**
4. **未做 sparse 删除比例敏感性扫描**
5. **未测试并发验证**
6. **未验证 data-snapshot 跨机恢复**

## 十四、结论

| 通过条件 | 实际 | 结论 |
| --- | --- | --- |
| 同单多次成交佣金只按累计佣金算增量 | 场景 A/B/C 实测正确 | ✅ |
| 税费不计入此前已收佣金 | 场景 A 核心回归证明 | ✅ |
| 买卖费用规则正确 | 场景 D：买入无印花税 | ✅ |
| 不同订单最低佣金独立 | 场景 E：各 5.00 | ✅ |
| Trade/Order/Portfolio 账本一致 | 场景 H + 真实数据 264 笔 | ✅ |
| 原有 310 项全部保留并通过 | 310/310 | ✅ |
| 新增测试全部通过 | 12/12 | ✅ |
| 全量测试通过 | 322/322 | ✅ |
| 原始行情与历史记录未污染 | 指纹一致、记录数不变 | ✅ |
