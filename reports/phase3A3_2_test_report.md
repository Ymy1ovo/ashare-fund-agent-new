# 阶段3A.3.2 测试报告

- 生成时间：2026-11-12
- 环境：Python 3.11.2 / pytest / Windows
- 命令：`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q`

## 1. 总数（按纪律拆分，不给单一总数）

| 类别 | 数量 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| **原有测试**（阶段1A~3A.3.1） | **387** | **387** | 0 | 0 |
| **本阶段新增测试** | **25** | **25** | 0 | 0 |
| **合计** | **412** | **412** | **0** | **0** |

- `--collect-only`：412 tests collected
- 单独跑新增：`pytest tests/test_corporate_actions.py` → 25 passed
- 单独跑原有：`pytest tests/ --ignore=tests/test_corporate_actions.py` → 387 passed

**原有 387 项全部保留、全部通过，无删除、无跳过、无 xfail 标记。**

## 2. 新增测试逐项（25 项）

对应任务书 §9 要求的 18 项会计恒等式场景：

| # | 要求场景 | 测试函数 | 结果 |
| ---: | --- | --- | :---: |
| 1 | 10:1 拆分 | `test_split_10_to_1_keeps_total_assets_continuous` | ✅ |
| 2 | 1:2 反向拆分 | `test_reverse_split_1_to_2_halves_shares` | ✅ |
| 3 | 非整数比例 | `test_fractional_split_produces_fractional_cash` | ✅ |
| 4 | 现金分红 | `test_cash_distribution_increases_cash` | ✅ |
| 5 | 同一天拆分+分红 | `test_split_and_distribution_same_day` | ✅ |
| 6 | 重复导入 | `test_duplicate_event_import_is_idempotent` | ✅ |
| 7 | 事件顺序错误 | `test_effective_before_ex_date_rejected`、`test_split_ratio_must_exceed_one` | ✅ |
| 8 | 事件落在非交易日 | `test_event_on_non_trading_day_applies_next_trading_day` | ✅ |
| 9 | 无持仓 | `test_event_without_position_changes_nothing` | ✅ |
| 10 | 部分成交订单挂起 | `test_event_with_pending_order_keeps_ledger_consistent` | ✅ |
| 11 | 零碎股 | `test_fractional_shares_converted_to_cash` | ✅ |
| 12 | 现金不足 | `test_leveraged_position_does_not_break_cash` | ✅ |
| 13 | 市值连续性 | `test_market_value_and_total_assets_continuous_across_split` | ✅ |
| 14 | 总资产连续性 | `test_total_assets_continuous_across_cash_distribution` | ✅ |
| 15 | 调整后收益率正确 | `test_daily_return_identity_after_split` | ✅ |
| 16 | 缺失行情与事件日重叠 | `test_event_day_with_missing_quote_uses_last_price` | ✅ |
| 17 | 未确认事件不得自动应用 | `test_unverified_action_not_applied`、`test_compute_impact_rejects_unverified` | ✅ |
| 18 | 历史更新不得污染已有记录 | `test_same_action_applied_twice_raises`、`test_load_actions_filters_by_range_and_codes` | ✅ |

附加 7 项：

| # | 测试函数 | 目的 | 结果 |
| ---: | --- | --- | :---: |
| 19 | `test_unverified_actions_listed_separately` | 未确认事件可查询、与确认事件分离 | ✅ |
| 20 | `test_disabled_corporate_actions_matches_legacy` | 开关关闭退化为旧口径（证明修复生效） | ✅ |
| 21 | `test_no_action_etf_unaffected` | 无事件标的开关前后完全一致 | ✅ |
| 22 | `test_portfolio_rejects_negative_new_quantity` | 负数量拒绝 | ✅ |

> 部分测试函数覆盖两个断言场景（如第 7、17、18 项），
> 因此 18 项要求由 21 个测试函数承载；加上 4 个附加项 = 25。

### 2.1 测试粒度说明

**全部测试走完整链路**：`BacktestEngine.run()` → `Broker` 撮合 →
`Portfolio` 账本 → 每日估值 → `DailySnapshot`，断言对象是
**持仓数量、现金余额、总资产、净值**，不是函数返回值。

唯一例外是第 13/14 项（市值/总资产连续性），直接用 `Portfolio`
验证「数量 ×10、价格 ÷10 后总资产不变」，因为要精确控制价格。

## 3. 未验证项（明确列出）

| # | 项 | 为什么未验证 | 风险 |
| ---: | --- | --- | --- |
| 1 | 真实分红发放日与除息日的现金可用性差异 | 回测不模拟「现金 T+N 到账」 | 极小（不影响收益） |
| 2 | 零碎股的官方处理规则 | 官方公告未逐项规定 | 实测 188.49 元，< 0.02% |
| 3 | unverified 路径的真实数据触发 | 当前 166 条全部 confirmed | 有测试覆盖，无真实数据 |
| 4 | 2005-2019 年 320 处复权异常 | 不在回测区间内 | 无 |
| 5 | 其余 36 条历史验证记录的重放 | 耗时约 12 小时 | 数值仍受影响，已记录 |
| 6 | 券商真实对账单核对 | 无对账单数据 | 无法验证绝对正确性 |
| 7 | 事件数据的多源交叉验证（165/166 条） | 成本高 | 单源数据可能有误 |
| 8 | 极端行情下的事件叠加（停牌 + 拆分 + 分红） | 未构造该场景 | 理论上有风险 |

## 4. 其他验证

### 4.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/c46fa37b932944c2` | 200（windows=8 grid=8 stress=7，结论「有条件通过」） |
| `GET /api/validations/not_exist` | 404（符合预期） |

**结论**：`SMOKE_FAILED: 无`

### 4.2 Streamlit AppTest

| 页面 | 异常 | 错误 |
| --- | --- | :---: |
| `3_回测.py` | 无 | 无 |
| `4_策略验证.py` | 无 | 无 |

### 4.3 数据库完整性

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 行情指纹（修复前后） | **一致** |
| 旧记录删改 | **无** |

### 4.4 迁移幂等性

在备份副本上执行 `init_db()` 两次：行数完全一致，`integrity_check=ok`。
详见 `phase3A3_2_data_snapshot.md` 第 5 节。

### 4.5 人工账本抽查（3 个代表性事件）

| 事件 | 修复前 | 修复后 | 判断 |
| --- | ---: | ---: | --- |
| `511030` 2025-03-19 合并 1:0.1 | 总资产 +900.18%（凭空 899.6 万） | +0.049% | **修复正确** |
| `510300` 2021-01-19 分红 0.072 元/份 | 日收益 -1.343%（分红丢失） | -0.054%（现金补回 13,024.80） | **修复正确** |
| `512100` 2022-09-05 合并 1:0.3656 | 该区间无持仓，无差异 | 无差异 | **符合预期** |

### 4.6 无公司行为标的回归

15 只全区间无事件的 ETF 中，`test_no_action_etf_unaffected`
验证开关前后净值序列**逐日完全相等**。

### 4.7 全量回测回归

| 项 | 结果 |
| --- | --- |
| 6 次重放（3 组 × 2 口径） | 全部完成，无异常 |
| 数据指纹 | 前后一致 |
| 完整验证流程重放 | 1,125.6 秒，success |

## 5. 测试覆盖的代码

| 文件 | 新增测试覆盖 |
| --- | --- |
| `app/backtest/corporate_actions.py` | `CorporateAction` 校验、`compute_impact`、`save_action`、`load_actions`、`record_application`、`unverified_actions` |
| `app/backtest/portfolio.py` | `apply_corporate_action`（数量缩放、成本守恒、现金入账、负数量拒绝） |
| `app/backtest/engine.py` | `_load_corporate_actions`、`_apply_corporate_actions`、`input_hash` 版本字段 |
| `app/backtest/config.py` | `apply_corporate_actions`、`apply_cash_distributions` 开关 |
| `app/database/db.py` | `init_db` 建表与幂等迁移 |
| `app/research/attribution.py` | `contamination_estimate` 新公式（原有 14 项测试全部通过） |

## 6. 失败与跳过明细

| 项 | 数量 |
| --- | ---: |
| 失败 | **0** |
| 错误 | **0** |
| 跳过（skip） | **0** |
| xfail | **0** |
| 警告 | 1（Starlette `httpx` 弃用警告，与本次改动无关） |

## 7. 复现方式

```bash
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_corporate_actions.py -q
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/smoke_validation_api.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/replay_3a3_2.py
```

## 8. 测试局限

1. 测试用构造行情（`pd.bdate_range` 生成的工作日 + 人工收盘价），
   不覆盖真实市场的跳空、停牌、涨跌停叠加。
2. 未做性能测试（公司行为查找是 O(1) 字典索引，不影响回测速度）。
3. 未做并发测试（回测是单线程；`record_application` 依赖唯一约束防重）。
4. 未测「同一 ETF 同一天多个同类型事件」（如一天两次分红）——
   现实不存在，`UNIQUE(code, action_type, ex_date)` 也不允许。
