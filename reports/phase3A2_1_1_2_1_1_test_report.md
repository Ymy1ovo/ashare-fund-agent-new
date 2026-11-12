# 阶段3A.2.1.1.2.1.1 测试报告

- 执行时间：2026-11-12
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 基线提交：`8cbf77e429fd71ea8fae6ed21f38ebeca39a7fe9`
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
| 阶段3A.2.1.1.2.1 | 12 | 全部通过 |
| **原有小计** | **322** | **全部保留并通过** |
| **本次新增**（`test_cost_aggregation.py`） | **15** | **全部通过** |
| **全量合计** | **337** | **全部通过** |

| 项目 | 数值 |
| --- | ---: |
| 收集测试 | 337 |
| 通过 | **337** |
| 失败 | **0** |
| 跳过 | **0** |
| 未执行 | **0** |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 24.43s |
| 日志 | `logs/pytest_phase3a2_1_1_2_1_1.log` |

## 二、新增测试清单（15 项）

| # | 测试 | 场景 | 结果 |
| ---: | --- | --- | --- |
| 1 | `test_scenario_a_total_cost_includes_taxes_and_slippage` | A | 佣金6+印花10+过户0.2+滑点2=**18.2** | 通过 |
| 2 | `test_scenario_a_old_formula_would_undercount` | A | **回归**：旧公式得 8.0，漏 10.2 | 通过 |
| 3 | `test_scenario_b_zero_tax_compat` | B | 税费 0，佣金 5 + 滑点 1 = **6.0** | 通过 |
| 4 | `test_scenario_c_mixed_buy_sell_trades` | C | 三笔买卖混合，总成本 30.80 | 通过 |
| 5 | `test_scenario_d_all_zero_cost` | D | 全 0 → total_cost = 0 | 通过 |
| 6 | `test_no_trades_zero_cost` | D | 无成交 → 全 0 | 通过 |
| 7 | `test_scenario_e_multi_fill_uses_trade_total_fees` | E | 同单两次成交，20.20 而非 10.0 | 通过 |
| 8 | `test_total_commission_only_commission` | 语义 | 佣金 3，税费 150 → total_commission = 3 | 通过 |
| 9 | `test_total_slippage_only_slippage` | 语义 | 滑点 2，费用 150 → total_slippage = 2 | 通过 |
| 10 | `test_total_cost_components_additive` | 语义 | 四项可加总 | 通过 |
| 11 | `test_performance_as_dict_contains_new_fields` | 接口 | 6 个成本字段齐全 | 通过 |
| 12 | `test_report_renders_separate_cost_lines` | 报告 | 分项列示且总成本 18.20 | 通过 |
| 13 | `test_cost_semantics_legacy_vs_new` | 兼容 | 新旧口径可区分 | 通过 |
| 14 | `test_cost_semantics_empty_summary` | 兼容 | 空 summary → legacy | 通过 |
| 15 | `test_new_run_summary_tagged` | 兼容 | 新回测写入 cost_semantics | 通过 |

## 三、场景 A 精确核对

```text
commission = 6, stamp_tax = 10, transfer_fee = 0.2, slippage = 2
```

| 指标 | 期望 | 实测 |
| --- | ---: | ---: |
| `total_commission` | 6.0 | 6.0 ✅ |
| `total_stamp_tax` | 10.0 | 10.0 ✅ |
| `total_transfer_fee` | 0.2 | 0.2 ✅ |
| `total_trade_fees` | 16.2 | 16.2 ✅ |
| `total_slippage` | 2.0 | 2.0 ✅ |
| **`total_cost`** | **18.2** | **18.2 ✅** |

旧公式 `commission + slippage = 6 + 2 = 8.0`，漏掉 10.2（印花税 + 过户费）。

## 四、场景 B 兼容性核对

税费为 0 时（项目历史默认配置）：

| 指标 | 值 |
| --- | ---: |
| total_commission | 5.0 |
| total_slippage | 1.0 |
| **total_cost** | **6.0** |

与旧口径完全一致，不会因本次修复改变历史配置下的结论。

## 五、场景 C 多笔混合

| # | 方向 | 金额 | 佣金 | 印花税 | 过户费 | 滑点 | 单笔成本 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 买 | 10,000 | 5.0 | 0 | 0.10 | 3.0 | 8.10 |
| 2 | 卖 | 12,000 | 5.0 | 6.0 | 0.12 | 4.0 | 15.12 |
| 3 | 买 | 8,000 | 5.0 | 0 | 0.08 | 2.5 | 7.58 |

| 汇总 | 值 |
| --- | ---: |
| total_commission | 15.0 |
| total_stamp_tax | 6.0 |
| total_transfer_fee | 0.30 |
| total_trade_fees | 21.30 |
| total_slippage | 9.5 |
| **total_cost** | **30.80** |

与逐笔 `sum(t.total_fees + t.slippage_cost)` 一致。

## 六、场景 E 同一订单多次成交

| Trade | 佣金 | 印花税 | 过户费 | 费用合计 | 滑点 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 5.0 | 5.0 | 0.10 | 10.10 | 2.0 |
| 2 | 1.0 | 5.0 | 0.10 | 6.10 | 2.0 |
| 合计 | **6.0** | **10.0** | **0.20** | **16.20** | **4.0** |

| 计算方式 | 值 | 是否正确 |
| --- | ---: | --- |
| 正确：`total_trade_fees + slippage` | **20.20** | ✅ |
| 错误：`total_commission + slippage` | 10.00 | ❌ 低估 50.5% |

## 七、真实数据验证（DSH 实际执行）

3 只 ETF、2025-01-02 ~ 2026-11-09、非零税费、**264 笔成交**：

| 项目 | 数值 |
| --- | ---: |
| `total_commission` | 25,068.8621 |
| `total_stamp_tax` | 50,041.1562 |
| `total_transfer_fee` | 1,000.8231 |
| `total_trade_fees` | 76,110.8414 |
| `total_slippage` | 47,320.2449 |
| **修复后 `total_cost`** | **123,431.0862** |
| 修复前（旧公式） | 72,389.1069 |
| **漏计** | **51,041.9793（41.4%）** |
| 逐笔累加校验 | `sum(t.total_fees + t.slippage_cost)` == total_cost ✅ |

修复前每 100 元真实成本隐藏 41 元。

## 八、其余成本统计位置核查

| 位置 | 是否漏计 | 处理 |
| --- | --- | --- |
| `metrics.compute_performance()` | ❌ | **已修** |
| `report` 绩效表 | ❌ | **改为分项** |
| `report` 交易明细表 | ❌ | **增加税费列** |
| `validation.runner._metrics_payload()` | ✅ | 自动沿用 |
| `scripts/run_backtest.py` | ✅ | 自动沿用 |
| `scripts/report_backtest_3a.py` | ✅ | 人工手算，不读 metrics |
| `portfolio.total_fees` | ✅ | 累加三项和 |
| `api.get_trades()` | ✅ | 直读数据库不汇总 |
| `dashboard/pages/3_回测.py` | ✅ | 不展示成本汇总 |

## 九、历史记录兼容验证

| 检查 | 结果 |
| --- | --- |
| 历史 11 条 `backtest_runs` 记录数 | 未变（11） |
| 历史 `summary_json` 内容 | **未修改** |
| 历史 `total_cost` 语义 | 保留旧语义，通过 `cost_semantics` 区分 |
| 历史税费字段 | **不补造**（不猜测历史税费） |
| 新记录 `cost_semantics` | 写入 `commission+taxes+slippage` |

历史记录实测（旧语义）：

| run_id | total_cost | total_commission |
| --- | ---: | ---: |
| `7181d2a6ed3f4555` | 595.94 | 248.86 |
| `d08db2c030a64458` | 130,431.33 | 50,053.63 |
| `2ecc9c0803174978` | 196,010.80 | 99,807.08 |

这些记录当时 `stamp_duty_rate = 0`、`transfer_fee_rate = 0`，
旧 `total_cost` 数值上等于真实总成本，**无需重算**。

## 十、API 与 Streamlit 冒烟（DSH 实际执行）

| 检查 | 结果 |
| --- | --- |
| `GET /health` | 200 |
| `GET /api/backtests?limit=3` | 200（3 条） |
| `GET /api/backtests/{id}/trades` | 200 |
| `GET /api/validations?limit=3` | 200 |
| `GET /api/validations/not_exist` | 404（期望） |
| Streamlit `3_回测.py` AppTest | **0 异常** |
| Streamlit `4_策略验证.py` AppTest | **0 异常** |

## 十一、数据库完整性（DSH 实际执行）

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
| 数据库结构 | **无变更，无需迁移** |

## 十二、静态代码审查（非运行测试）

- `metrics.py` 中 `total_cost` 只在一处赋值，全文无第二处旧公式
- `Performance` dataclass 新增 3 个字段，`as_dict()` 自动包含
- `report.py` 中不再出现「总费用 = total_commission」的错误表述
- `api.COST_SEMANTICS` 常量与 `storage.save_result()` 的写入值一致

## 十三、未执行或未覆盖

1. **未重算历史记录的成本**：遵守「历史结果不被覆盖」的约束，用标记区分而非回刷
2. **未验证成本对历史策略结论的影响**：历史税率均为 0，`total_cost` 数值不变，
   但本次未重跑那 11 次回测
3. **未测试极端浮点累积误差**：264 笔量级已覆盖
4. **未新增其他功能**

## 十四、结论

| 通过条件 | 实际 | 结论 |
| --- | --- | --- |
| `total_commission` 只统计佣金 | 场景 A/语义测试 | ✅ |
| `total_slippage` 只统计滑点 | 场景 A/语义测试 | ✅ |
| `total_cost` 含佣金+税费+滑点 | 18.2 / 30.80 / 20.20 / 123,431.09 | ✅ |
| 所有成本统计位置口径一致 | 9 处逐一核查 | ✅ |
| 历史费用语义不被错误混合 | `cost_semantics` 标记 | ✅ |
| 原有 322 项全部保留并通过 | 322/322 | ✅ |
| 新增测试全部通过 | 15/15 | ✅ |
| 历史数据未被污染 | 记录数不变、指纹一致 | ✅ |
