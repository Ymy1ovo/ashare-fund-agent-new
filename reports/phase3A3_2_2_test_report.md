# 阶段3A.3.2.2 测试报告

- 生成时间：2026-11-13
- 环境：Python 3.11.2 / pytest / Windows
- 命令：`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q`

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| **原有测试**（1A ~ 3A.3.2.1） | **425** | **425** | 0 | 0 |
| **本阶段新增** | **29** | **29** | 0 | 0 |
| **合计** | **454** | **454** | **0** | **0** |

`--collect-only`：**454 tests collected**
`tests/test_corporate_actions.py`：**67 passed**

## 2. 本阶段新增的 29 项

### 2.1 零碎份额成本基准（10 项）

| # | 测试函数 | 覆盖要求 |
| ---: | --- | --- |
| 1 | `test_integer_split_cost_basis_unchanged` | 整数比例拆分，成本基准正确 |
| 2 | `test_integer_reverse_split_cost_basis_unchanged` | 整数比例合并，成本基准正确 |
| 3 | `test_fractional_split_disposes_cost_and_records_pnl` | 非整数拆分，零碎现金补偿 |
| 4 | `test_fractional_reverse_split_disposes_cost_and_records_pnl` | 非整数合并，零碎现金补偿 |
| 5 | `test_multi_lot_fractional_disposal_uses_portfolio_level_cost` | 多批次同时非整数折算 |
| 6 | `test_truncate_policy_records_loss_not_cash` | 舍去口径记损失不记现金 |
| 7 | `test_round_up_policy_adds_share_without_cost` | 进位口径不增加成本 |
| 8 | `test_consecutive_actions_do_not_double_charge_cost` | 连续事件不重复计成本 |
| 9 | `test_no_position_action_records_nothing` | 无持仓不产生成本或盈亏 |
| 10 | `test_engine_records_fractional_ledger` | **完整 Engine 流程**留痕 |

多个 lot 分配后总份额准确：测试 5 断言
`sum(lot.quantity) == position.quantity == new_quantity`。

事件前后总经济价值核对：测试 3 断言
`市值 + 补偿 == 拆分前市值`。

### 2.2 事件日期边界（8 项）

| # | 测试函数 | 覆盖要求 |
| ---: | --- | --- |
| 11 | `test_window_boundary_ex_date_equals_start` | `ex_date == start_date` |
| 12 | `test_window_boundary_ex_date_equals_end_effective_after` | `ex_date == end_date` 且 pay 在结束日之后 |
| 13 | `test_window_boundary_split_effective_equals_end` | 拆分 `effective_date == end_date` |
| 14 | `test_window_boundary_split_effective_after_end_excluded` | 拆分 `effective_date > end_date` |
| 15 | `test_window_excludes_events_before_start` | 开始日期前已发生的事件 |
| 16 | `test_end_of_backtest_unsettled_dividend_counted_in_assets` | 期末未到账分红计入净资产 |
| 17 | `test_same_event_not_loaded_twice_across_adjacent_ranges` | 跨相邻区间不重复 |
| 18 | `test_load_actions_filters_by_window_date` | 按类型分别筛（改造既有测试） |

### 2.3 事件指纹（9 项）

| # | 测试函数 | 覆盖要求 |
| ---: | --- | --- |
| 19 | `test_announcement_url_changes_fingerprint` | 公告 URL 改变 |
| 20 | `test_announcement_title_changes_fingerprint` | 公告标题改变 |
| 21 | `test_announcement_date_changes_fingerprint` | 公告日期改变 |
| 22 | `test_manager_name_changes_fingerprint` | 基金管理人改变 |
| 23 | `test_evidence_text_changes_fingerprint` | 证据内容改变 |
| 24 | `test_evidence_status_changes_fingerprint` | 证据等级改变 |
| 25 | `test_unrelated_field_does_not_change_fingerprint` | 无关字段**不**改变 |
| 26 | `test_same_metadata_repeat_gives_same_fingerprint` | 重复运行指纹一致 |
| 27 | `test_events_digest_order_independent` | 事件顺序变化集合指纹不变 |
| 28 | `test_events_digest_ignores_unrelated_events` | 未参与事件不污染指纹 |

### 2.4 引擎级（2 项）

| # | 测试函数 | 覆盖要求 |
| ---: | --- | --- |
| 29 | `test_engine_fractional_event_keeps_assets_identity` | 非整数折算后逐日资产恒等式 |
| 30 | `test_round_up_policy_through_engine` | 进位口径走完整引擎 |

> 注：上表编号累计 30，其中 `test_load_actions_filters_by_window_date`
> 是**改造既有测试**（不是新增），故新增实为 **29 项**。

## 3. 原 425 项全部保留

无一项被删除。唯一改动是 `test_load_actions_filters_by_range_and_codes`
→ `test_load_actions_filters_by_window_date`：

| 项 | 旧断言 | 新断言 |
| --- | --- | --- |
| `load_actions(start=01-04, end=01-04)` | `len == 2` | **`len == 1`（仅拆分）** |
| 新增 | — | `load_actions(start=01-03, end=01-03)` → 仅分红 |
| 新增 | — | `load_actions(start=01-03, end=01-04)` → 2 条 |

**断言更严，不是更松**：旧断言 `len == 2` 建立在「统一按 effective_date 筛」
的错误口径上，新断言按事件类型分别验证。

## 4. 其他验证

### 4.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/06600b4faac146c5` | 200（windows=8 grid=8 stress=7 有条件通过） |
| `GET /api/validations/not_exist` | 404 |

`SMOKE_FAILED: 无`

### 4.2 Streamlit AppTest

| 页面 | 异常 | 错误 |
| --- | --- | :---: |
| `dashboard/pages/3_回测.py` | 0 | 0 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 |

### 4.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 4.4 事件数量对账

`python scripts/reconcile_events.py`：

**校验项 14，失败 0**

口径已改为**经济权益日**（分红 `ex_date` / 拆分 `effective_date`）：

| 校验项 | 结果 |
| --- | :---: |
| 原始抓取 == 去重后（166） | OK |
| 样本内+样本外==区间内（49+32=81） | OK |
| 区间内+区间外==总数（81+85=166） | OK |
| split 分区间之和==合计（14+6+3=23） | OK |
| reverse_split 分区间之和==合计（1+3+18=22） | OK |
| cash_distribution 分区间之和==合计（34+23+64=121） | OK |
| 类型合计==去重总数（166） | OK |
| official_confirmed 分区间之和（49+27+61=137） | OK |
| secondary_confirmed 分区间之和（0+5+14=19） | OK |
| unverified 分区间之和（0+0+10=10） | OK |
| rejected 分区间之和（0） | OK |
| 证据等级合计==去重总数（166） | OK |
| 应用事件数<=可应用事件数（79 ≤ 81） | OK |

### 4.5 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本阶段是否改变 | **否**（连续第四阶段不变） |

### 4.6 事件指纹

| 区间 | 事件数 | 指纹（新字段集） |
| --- | ---: | --- |
| 样本内 | 49 | `27e331cfbbae…` |
| 样本外（41 只池） | 31 | `2b4b24e468cb…` |

## 5. 加载/指纹/应用三者一致性

| 环节 | 样本内 | 样本外 |
| --- | ---: | ---: |
| 数据库（41 只池，经济权益日） | 49 | 31 |
| `load_actions()` 加载 | **49** | **31** |
| 可应用（is_confirmed） | **49** | **31** |
| 引擎实际应用（去重） | 79（区间内合计，含两区间） | |

三者完全一致，不存在口径分叉。

## 6. 未验证项

| # | 项 | 原因 |
| ---: | --- | --- |
| 1 | 39 条历史验证记录重放 | 单次约 24 分钟，全量约 16 小时 |
| 2 | 跨界事件（ex 在区间内、eff 在区间外）的真实数据验证 | 本库无此类数据 |
| 3 | 非空初始持仓的分红处理 | 未实现 |
| 4 | 真实券商对账单核对 | 无对账单 |
| 5 | 21 条公告未明说零碎口径的核实 | 公告正文确无相关表述 |

## 7. 失败与跳过

| 项 | 数量 |
| --- | ---: |
| 失败 | **0** |
| 错误 | **0** |
| 跳过 | **0** |
| xfail | **0** |
| 警告 | 1（Starlette `httpx` 弃用，与本次改动无关） |

## 8. 复现命令

```bash
cd D:\ymy\jj-agent

PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_corporate_actions.py -q
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/reconcile_events.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/set_fractional_policy.py --dry-run
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/smoke_validation_api.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/replay_3a3_2.py --out data/replay_3a3_2_2.json
```

## 9. 测试局限

1. 行情用构造数据（`pd.bdate_range` + 人工收盘价），不覆盖真实停牌/跳空
2. 分红发放日用构造日期，不验证真实 T+3~T+7 分布
3. 零碎份额测试用单一日期的多批次，不覆盖跨日建仓的复杂 FIFO
4. 未做性能与并发测试
