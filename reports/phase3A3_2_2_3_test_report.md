# 阶段3A.3.2.2.3 测试报告

- 生成时间：2026-11-14
- 环境：Python 3.11.2 / pytest / Windows
- 基线：484 项（1A ~ 3A.3.2.2.2）

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.2.2） | **484** | 484 | 0 | 0 | 0 |
| **3A.3.2.2.3** 新增 | **12** | 12 | 0 | 0 | 0 |
| **合计** | **496** | **496** | **0** | **0** | **0** |

`--collect-only`：**496 tests collected**

## 2. 本轮新增的 12 项

新增文件 `tests/test_phase3a3_2_2_3.py`（266 行），全部走真实路径。

### 2.1 问题1：异常路径（4 项）

| # | 测试 | 断言 |
| ---: | --- | --- |
| 1 | `test_sql_execution_error_raises_load_error` | `load_actions` 抛 `sqlite3.OperationalError` → `CorporateActionLoadError` |
| 2 | `test_deserialization_error_raises_load_error` | 真实反序列化失败（`ex_date='not-a-date'`）→ `CorporateActionLoadError` |
| 3 | `test_load_failure_leaves_no_successful_record` | 三张表均 0 行，`list_runs()` 为空 |
| 4 | `test_validation_digest_load_failure_raises` | 验证层 `_events_digest_for` 抛 `ValidationError` |

### 2.2 问题2：持久化（6 项）

| # | 测试 | 断言 |
| ---: | --- | --- |
| 5 | `test_non_formal_result_persists_both_fields` | summary / 顶层 / `list_runs` 三处字段完整 |
| 6 | `test_formal_result_persists_formal_basis` | 正式结果不变，`performance` 与内存一致 |
| 7 | `test_legacy_record_without_fields_is_not_formal` | 无字段 → `unknown_legacy` + `False` |
| 8 | `test_accounting_basis_helpers_fail_closed` | 三个判定函数语义 |
| 11 | `test_missing_basis_is_persisted_as_unknown_not_formal` | 结果缺口径 → 不默认正式 |
| 12 | `test_disabled_basis_forces_non_formal_even_if_flag_true` | 口径非正式 → 强制 `False` |

### 2.3 问题3：验证闸门（2 项）

| # | 测试 | 断言 |
| ---: | --- | --- |
| 9 | `test_non_formal_backtest_rejected_by_validation` | `_run_backtest` 抛 `ValidationError` |
| 10 | `test_validation_config_keeps_corporate_actions_on` | 验证配置默认开启公司行为 |

## 3. 旧测试保留情况

- 484 项基线测试**全部保留**，未删除、未跳过、未弱化断言。
- `tests/test_corporate_actions.py` **97 项**全部通过。
- 其他测试文件 **387 项**全部通过。
- 本轮**没有修改任何既有测试**的断言。

## 4. 其他验证

### 4.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/<最新>` | 200 |
| `GET /api/validations/not_exist` | 404 |
| `GET /api/backtests` | 200，11 条 |
| `GET /api/backtests/<run_id>` | 200，含 `accounting_basis` / `formal_valuation` 顶层字段 |

`SMOKE_FAILED: 无`

### 4.2 Streamlit AppTest

| 页面 | 异常 | 错误元素 | 数据表 | 指标 |
| --- | ---: | ---: | ---: | ---: |
| `dashboard/pages/3_回测.py` | 0 | 0 | 5 | 5 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 | 5 | 4 |

非正式口径提示使用 `st.warning`，不计入页面错误。

### 4.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 4.4 迁移幂等性

在 `data/fund_agent.db` 副本上连续执行 `init_db()` 两次：

| 表 | 前 | 第一次后 | 第二次后 |
| --- | ---: | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 | 116,609 |
| `etf_pool` | 46 | 46 | 46 |
| `trade_calendar` | 8,797 | 8,797 | 8,797 |
| `backtest_runs` | 11 | 11 | 11 |
| `corporate_actions` | 166 | 166 | 166 |
| `corporate_action_versions` | 704 | 704 | 704 |
| `corporate_action_applications` | 3,787 | 3,787 | 3,787 |
| `dividend_receivables` | 785 | 785 | 785 |
| `validation_runs` | 44 | 44 | 44 |

**幂等，本轮无 schema 变更。**

### 4.5 事件对账

`python scripts/reconcile_events.py` → **校验项 14，失败 0**

### 4.6 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

连续第五个阶段未变。

## 5. 结论

- 基线 484 项全部保留且通过
- 本轮新增 12 项全部通过
- 最终 **496 passed / 0 failed / 0 skipped / 0 xfail**
- 测试结果是本会话本地执行结果，**不是外部独立测试**
