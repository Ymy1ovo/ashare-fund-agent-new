# 阶段3A.3.2.3.1 测试报告

- 生成时间：2026-11-14
- 环境：Python 3.11.2 / pytest / Windows
- 基线：518 项（1A ~ 3A.3.2.2.4）

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.2.4） | **518** | 518 | 0 | 0 | 0 |
| **3A.3.2.3.1** 新增 | **20** | 20 | 0 | 0 | 0 |
| **合计** | **538** | **538** | **0** | **0** | **0** |

`--collect-only`：**538 tests collected**

## 2. 本轮新增的 20 项

新增文件 `tests/test_replay_3a3_2_3_1.py`。

### 2.1 盘点与分类（6 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 1 | `test_manifest_counts_backtests` | 4 条记录分别落入 legacy / non_replayable / current_formal / unknown_legacy；分类合计等于总数 |
| 2 | `test_manifest_marks_replayed` | 有成功重放记录时判为 replayed 并带出 `replay_record_id` |
| 3 | `test_manifest_reports_missing_params_explicitly` | 缺 `costs` 时逐项列出，且 `params_source` 标注每个值来源 |
| 4 | `test_manifest_rejects_validation_with_unproven_hash` | `config_hash` 反证失败 → non_replayable |
| 5 | `test_manifest_proves_validation_hash_when_it_matches` | 反证命中 → 参数被证明，可重放 |
| 6 | `test_manifest_flags_failed_validation_as_non_replayable` | 源记录 `status=failed` → non_replayable |

### 2.2 缺失源记录（2 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 7 | `test_missing_backtest_source_raises` | 不存在的 run_id → `ReplayError` |
| 8 | `test_missing_validation_source_raises` | 不存在的 validation_id → `ReplayError` |

### 2.3 参数忠实性（3 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 9 | `test_backtest_config_follows_source_not_defaults` | 12 个字段全部沿用源记录（含 `lot_size_override`、税率），且 `apply_corporate_actions` 强制为 True |
| 10 | `test_backtest_config_refuses_missing_ma_window` | 缺 `ma_window` → 抛错，不填默认值 |
| 11 | `test_validation_config_refuses_unproven_hash` | 参数不可证明 → 抛错，不按默认值重建 |

### 2.4 执行、幂等与恢复（6 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 12 | `test_replay_creates_new_record_and_registers_link` | 新 run_id、源记录不变、登记行含全部 8 个要求字段、新记录带 `ca-v2-receivable` 标记 |
| 13 | `test_replay_is_idempotent_without_force` | 第二次执行返回 skipped，不新增 attempt 行 |
| 14 | `test_replay_force_creates_second_record` | `--force` 产生第二条记录，源记录仍在，attempt 累计 2 行 |
| 15 | `test_replay_skips_non_replayable_source_without_creating_record` | 缺参数 → failed，只留源记录 1 行 |
| 16 | `test_replay_many_isolates_single_failure` | 批量中一条失败不影响另一条成功 |
| 17 | `test_replay_resumes_after_interruption` | 中断后重跑：已成功 skipped，未做的继续 |

### 2.5 历史保护与非正式口径（3 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 18 | `test_history_rows_not_overwritten_by_replay` | 重放前后源记录整行逐字段相等 |
| 19 | `test_replay_refuses_non_formal_result` | 重放拿到非正式口径 → failed，不写合法记录 |
| 20 | `test_pending_sources_lists_only_legacy` | 待重放清单只含 legacy，排除 current_formal 与 non_replayable |

## 3. 旧测试保留情况

- 518 项基线测试**全部保留**，未删除、未跳过、未弱化断言。
- 本轮修改了 1 处**实现**以迁就既有契约（见 §4.1），未改任何旧测试断言。

## 4. 实现缺陷与修正记录

开发过程中暴露并修正了三个真实缺陷，都记在此处：

### 4.1 重放记录未打会计版本标记

`save_result()` 只写 `summary_json`，不写 `backtest_runs.accounting_version` 列。
首次真实重放后盘点显示新记录被判为 `unknown_legacy`——因为分类读的是列。

修正：新增 `_stamp_replay_record()`，重放成功后只对该 run_id 执行 UPDATE。
测试 `test_replay_creates_new_record_and_registers_link` 补了对应断言。

### 4.2 口径常量用错

`replay_backtest()` 里用 `CURRENT_ACCOUNTING`（`ca-v2-receivable`）比对
`result.accounting_basis`（`formal_receivable`），两个是不同命名空间的值，
导致所有重放被误判为「非正式口径」。

修正：改用 `app.backtest.api.ACCOUNTING_FORMAL`。

### 4.3 `buy_and_hold` 被误判缺 `indicator_version`

`buy_and_hold` 历史上就是以 `indicator_version=None` 运行的，不需要指标。
原实现把所有 `indicator_version` 为空都判为缺参数。

修正：只有非 `buy_and_hold` 策略才要求指标版本。

## 5. 其他验证

### 5.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/0df22f3810974bea` | 200（windows=8 grid=8 stress=7） |
| `GET /api/validations/not_exist` | 404（期望 404） |

`SMOKE_FAILED: 无`

### 5.2 Streamlit AppTest

| 页面 | 异常 | 错误元素 | 数据表 | 指标 |
| --- | ---: | ---: | ---: | ---: |
| `dashboard/pages/3_回测.py` | 0 | 0 | 5 | 5 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 | 5 | 4 |

### 5.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 5.4 迁移幂等性

在 `data/fund_agent.db` 副本上连续执行 `init_db()` 两次：

| 表 | 前 | 第一次后 | 第二次后 |
| --- | ---: | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 | 116,609 |
| `backtest_runs` | 12 | 12 | 12 |
| `validation_runs` | 44 | 44 | 44 |
| `replay_attempts` | 1 | 1 | 1 |
| `corporate_actions` | 166 | 166 | 166 |
| `corporate_action_versions` | 704 | 704 | 704 |

**幂等。本轮唯一 schema 变更：新增 `replay_attempts` 表 + 2 个索引。**

### 5.5 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

重放前后均为该值，未变（连续第六个阶段）。

### 5.6 事件对账

`python scripts/reconcile_events.py` → 校验项 14，失败 0（本轮未改动公司行为逻辑）

## 6. 结论

- 基线 518 项全部保留且通过
- 本轮新增 20 项全部通过
- 最终 **538 passed / 0 failed / 0 skipped / 0 xfail**
- 测试结果是本会话本地执行结果，**不是外部独立测试**
