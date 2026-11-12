# 阶段3A.3.2 修复报告

- 生成时间：2026-11-12
- 性质：**代码与账本修复说明**。核查证据见 `phase3A3_2_corporate_action_audit.md`，
  设计规则见 `phase3A3_2_accounting_design.md`，重放结果见 `phase3A3_2_backtest_replay_report.md`。

## 1. 修复清单

| # | 缺陷 | 修复 | 文件 |
| ---: | --- | --- | --- |
| 1 | 份额拆分/合并后不调整持仓数量 | 新增事件驱动调整，`_apply_corporate_actions()` 在开盘前执行 | `app/backtest/engine.py` |
| 2 | 现金分红完全不入账 | 事件驱动现金入账 | `app/backtest/engine.py` |
| 3 | 没有公司行为数据结构 | 新增 `corporate_actions` + `corporate_action_applications` 两表 | `app/database/db.py`、`migrations/phase3a3_2_corporate_actions.sql` |
| 4 | 账本不支持数量缩放 | 新增 `Portfolio.apply_corporate_action()` | `app/backtest/portfolio.py` |
| 5 | `input_hash` 不含公司行为口径 | 加入 `corporate_action_version` | `app/backtest/engine.py` |
| 6 | 3A.3.1 污染估算公式错误 | 改为 `r_raw - r_adj` 口径，并标注废弃旧法 | `app/research/attribution.py` |
| 7 | 8% 阈值漏掉小额分红 | 改为读事件表，不再依赖阈值 | 全链路 |

## 2. 新增文件

| 文件 | 作用 |
| --- | --- |
| `app/backtest/corporate_actions.py` | 事件模型、合法性校验、影响计算、数据库读写、重复应用保护 |
| `migrations/phase3a3_2_corporate_actions.sql` | 两表 + 4 个索引的 DDL |
| `scripts/seed_corporate_actions.py` | 把官方核实事件写入事件表（幂等） |
| `scripts/audit_corporate_actions.py` | 抓取官方分红送配数据（只读，供核查） |
| `scripts/replay_3a3_2.py` | 修复口径 vs 旧口径的 backtest 对照 |
| `scripts/replay_validation_3a3_2.py` | 完整验证流程重放，生成新 validation_id |
| `tests/test_corporate_actions.py` | 25 项专项测试（18 项要求场景 + 7 项附加） |

## 3. 核心实现

### 3.1 事件应用流程

```
BacktestEngine.run()
  ├─ _load_corporate_actions(codes)
  │    └─ load_actions(start, end, codes) → 只保留 status=='confirmed'
  ├─ 每个交易日：
  │    ├─ _apply_corporate_actions()      ← 开盘撮合之前
  │    │    ├─ compute_impact(action, holding, price)
  │    │    ├─ portfolio.apply_corporate_action(code, new_qty, cash_delta)
  │    │    └─ record_application(run_id, impact)  → 唯一约束防重复
  │    ├─ 开盘撮合
  │    ├─ 收盘估值（原始 close）
  │    └─ 生成下一批订单
```

### 3.2 数量缩放时的成本基准守恒

`Portfolio.apply_corporate_action()` 按比例缩放每个 `Lot` 的数量，
同时把 `lot.price` 按 1/比例 反比调整：

```
Σ(批次数量 × 批次成本)  在事件前后完全相等
```

这样卖出时的已实现盈亏不会因为拆分而失真。
（测试 `test_market_value_and_total_assets_continuous_across_split` 验证）

### 3.3 未确认事件的处置

`status != 'confirmed'` 的事件：
- `load_actions()` 返回但 `_load_corporate_actions()` 过滤掉；
- 在 `result.notes` 写入 `公司行为：N 条未确认事件未应用（unverified_corporate_action）`；
- `compute_impact()` 对未确认事件直接抛 `CorporateActionError`，双重保险。

实测当前库 166 条全部 confirmed，此路径**有测试覆盖但无真实数据触发**。

## 4. 修复前后的差异验证

### 4.1 单元/集成测试（25 项）

| 场景 | 测试 | 结果 |
| --- | --- | :---: |
| 10:1 拆分 | `test_split_10_to_1_keeps_total_assets_continuous` | 通过 |
| 1:2 合并 | `test_reverse_split_1_to_2_halves_shares` | 通过 |
| 非整数比例 | `test_fractional_split_produces_fractional_cash` | 通过 |
| 现金分红 | `test_cash_distribution_increases_cash` | 通过 |
| 同日拆分+分红 | `test_split_and_distribution_same_day` | 通过 |
| 重复导入 | `test_duplicate_event_import_is_idempotent` | 通过 |
| 事件顺序错误 | `test_effective_before_ex_date_rejected`、`test_split_ratio_must_exceed_one` | 通过 |
| 跨非交易日 | `test_event_on_non_trading_day_applies_next_trading_day` | 通过 |
| 无持仓 | `test_event_without_position_changes_nothing` | 通过 |
| 部分成交订单 | `test_event_with_pending_order_keeps_ledger_consistent` | 通过 |
| 零碎股 | `test_fractional_shares_converted_to_cash` | 通过 |
| 现金不足边界 | `test_leveraged_position_does_not_break_cash` | 通过 |
| 市值连续性 | `test_market_value_and_total_assets_continuous_across_split` | 通过 |
| 总资产连续性 | `test_total_assets_continuous_across_cash_distribution` | 通过 |
| 收益率正确性 | `test_daily_return_identity_after_split` | 通过 |
| 缺失行情重叠 | `test_event_day_with_missing_quote_uses_last_price` | 通过 |
| 未确认不得应用 | `test_unverified_action_not_applied`、`test_compute_impact_rejects_unverified` | 通过 |
| 重复应用保护 | `test_same_action_applied_twice_raises` | 通过 |
| 附加：区间/代码过滤 | `test_load_actions_filters_by_range_and_codes` | 通过 |
| 附加：unverified 列表 | `test_unverified_actions_listed_separately` | 通过 |
| 附加：开关退化对照 | `test_disabled_corporate_actions_matches_legacy` | 通过 |
| 附加：无事件标的回归 | `test_no_action_etf_unaffected` | 通过 |
| 附加：负数量拒绝 | `test_portfolio_rejects_negative_new_quantity` | 通过 |

**全部走完整 Engine + Broker + Portfolio + 估值流程**，
不是只测函数返回值。

### 4.2 人工账本核对（3 个代表性事件）

**`511030` 2025-03-19 份额合并 1:0.1（样本外）**

| 日期 | 现金 | 市值 | 总资产 | 持仓 | 日变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025-03-18 | 340.55 | 999,124.00 | 999,464.55 | 95,200 | — |
| **2025-03-19（修复后）** | 340.55 | 999,609.52 | **999,950.07** | **9,520** | **+0.049%** |
| 2025-03-19（修复前） | 340.55 | 9,996,095.20 | **9,996,435.75** | 95,200 | **+900.18%** |

**修复前凭空多出 899.6 万元（占初始资金 900%）。**

**`510300` 2021-01-19 现金分红 0.072 元/份（样本内）**

| 日期 | 现金 | 总资产 | 日变化 |
| --- | ---: | ---: | ---: |
| 2021-01-18 | 13,174.41 | 1,010,476.11 | — |
| **2021-01-19（修复后）** | **26,199.21** | **1,009,933.41** | **-0.054%** |
| 2021-01-19（修复前） | 13,174.41 | 996,908.61 | **-1.343%** |

分红 13,024.80 元（180,900 份 × 0.072）正确入账，
除息下跌被现金完全抵消。

### 4.3 无公司行为标的回归

`test_no_action_etf_unaffected` 验证：对全区间无事件的标的，
`apply_corporate_actions` 开关前后净值序列**逐日完全相等**。

## 5. 修复影响范围

| 维度 | 影响 |
| --- | --- |
| 撮合成交价 | **无影响**（仍用原始 `open`） |
| 交易成本计算 | **无影响** |
| T+1 与涨跌停规则 | **无影响** |
| 技术指标 | **无影响**（仍用 `adjusted_close`） |
| 每日估值价 | **无影响**（仍用原始 `close`） |
| 持仓数量 | **受影响**（拆分/合并时调整） |
| 现金余额 | **受影响**（分红时增加） |
| 组合净值 | **受影响**（上述两者导致） |
| `input_hash` | **受影响**（加入 `corporate_action_version`） |

## 6. 未修复的事项（明确记录）

| # | 事项 | 原因 | 影响 |
| ---: | --- | --- | --- |
| 1 | 2005-2019 年 320 处历史复权因子异常 | 不在回测区间内 | 无（不影响任何回测） |
| 2 | 分红按除息日而非发放日入账 | 经济价值在除息日已确定；发放日只影响可用现金时点 | 极小机会成本 |
| 3 | 零碎股按收盘价折现金（非官方规则） | 官方公告未逐项规定 | 实测合计 188.49 元，占比 < 0.02% |
| 4 | 其余 36 条历史验证记录未重放 | 全池单次约 20 分钟，一次性重放约 12 小时 | 数值仍偏高/偏低，见重放报告第 11 节 |
| 5 | 事件数据单一来源（165/166） | 逐条交叉验证成本高 | 已标注；`511030` 已双源验证 |

## 7. 数据安全

| 检查 | 结果 |
| --- | --- |
| 数据库备份 | `data/backups/fund_agent_pre_3a3_2_20261112.db`（269,828,096 → 270,176,256 字节） |
| 备份方式 | SQLite `backup()` API，非文件复制 |
| `integrity_check` | **ok** |
| 行情行数 | 116,609（未变） |
| 行情指纹 | `d54727c0…ac49`（未变） |
| 旧 validation 记录 | 37 条完整保留 |
| 旧 backtest 记录 | 11 条完整保留 |
| 旧 order / trade | 29,248 / 26,093（未变） |
| 新增表 | 2 个，均为 `CREATE TABLE IF NOT EXISTS` |
| 既有表结构 | **未改动** |
| 迁移幂等 | `init_db()` 可重复执行 |
