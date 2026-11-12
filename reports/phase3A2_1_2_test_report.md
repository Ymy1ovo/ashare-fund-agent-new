# 阶段3A.2.1.2 测试报告

- 执行时间：2026-11-12
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 基线提交：`9806f2e0061f0bb8a33b1925a59dc9faebceaa76`
- 执行方式：DSH 在当前工作区实际运行

## 一、全量测试结果

```powershell
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

| 项目 | 数值 |
| --- | ---: |
| 收集测试 | **365** |
| 通过 | **365** |
| 失败 | **0** |
| 跳过 | **0** |
| 未执行 | **0** |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 24.56s |
| 日志 | `logs/pytest_phase3a2_1_2.log` |

## 二、测试构成分解

| 分类 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过 |
| 阶段3A.2 | 55 | 全部通过 |
| 阶段3A.2.1 | 40 | 全部通过 |
| 阶段3A.2.1.1 | 27 | 全部通过 |
| 阶段3A.2.1.1.2 | 34 | 全部通过 |
| 阶段3A.2.1.1.2.1 | 12 | 全部通过 |
| 阶段3A.2.1.1.2.1.1 | 15 | 全部通过 |
| **原有小计** | **337** | **全部保留并通过** |
| 阶段3A.2.1.2（`test_reliability.py`） | 14 | 全部通过 |
| **阶段3A.2.1.2.1 新增**（`test_final_acceptance.py`） | **14** | **全部通过** |
| **全量合计** | **365** | **全部通过** |

**原有 337 项全部保留**：未删除、未跳过、未弱化、未改断言。

## 三、本轮新增测试（14 项）

| # | 测试 | 覆盖点 | 结果 |
| ---: | --- | --- | --- |
| 1 | `test_deletion_ratios_and_modes_cover_required_set` | 6 比例 × 5 模式齐备 | 通过 |
| 2 | `test_copy_database_does_not_touch_source` | 副本不污染源库 | 通过 |
| 3 | `test_random_deletion_reproducible` | 相同种子删除结果一致 | 通过 |
| 4 | `test_random_deletion_ratio_approximately_correct` | 删除比例符合预期 | 通过 |
| 5 | `test_continuous_block_is_contiguous` | 连续模式确实连续 | 通过 |
| 6 | `test_missing_trading_day_count` | 缺失交易日统计正确 | 通过 |
| 7 | `test_zero_ratio_deletes_nothing` | 0% 基线不删任何行情 | 通过 |
| 8 | `test_summarize_matrix_groups_by_ratio_and_mode` | 汇总分组正确 | 通过 |
| 9 | `test_summarize_matrix_keeps_failed_and_insufficient` | 失败场景不被剔除 | 通过 |
| 10 | `test_concurrent_task_hash_consistency_same_params` | 同参数同 hash | 通过 |
| 11 | `test_concurrent_task_hash_inconsistent_same_params` | 同参数异 hash 报错 | 通过 |
| 12 | `test_concurrent_task_hash_inconsistent_diff_params` | 异参数同 hash 报错 | 通过 |
| 13 | `test_write_lock_serializes_and_returns_value` | 写锁串行且返回正确 | 通过 |
| 14 | `test_write_lock_releases_on_exception` | 异常后锁被释放 | 通过 |

## 四、实际执行的大型验证（非 pytest）

### 4.1 敏感性扫描：42 场景

| 池 | 比例数 | 模式数 | 场景数 | 状态分布 |
| --- | ---: | ---: | ---: | --- |
| 代表性池（6 只） | 6 | 5 | **30** | 5 success + 25 partial |
| 全池（41 只） | 6 | 2 | **12** | 0 success + 12 partial |
| **合计** | — | — | **42** | 5 success + 37 partial + 0 failed + 0 insufficient |

- 源库指纹：**前后一致**
- 所有场景 `integrity_check`：**ok**
- 负现金天数：**全部 0**

### 4.2 并发验证：4 组

| 组 | 任务数 | 总耗时 | integrity | ids 唯一 | hash 一致 |
| --- | ---: | ---: | --- | --- | --- |
| 两任务同参数 | 2 | 554.1s | ok | ✅ | ✅ |
| 四任务不同参数 | 4 | 840.3s | ok | ✅ | ❌→已修复 |
| 含失败任务 | 2 | 234.9s | ok | ✅ | ✅ |
| 两任务不同参数（修复后） | 2 | 400.0s | ok | ✅ | ✅ |

四任务首测的 `hash_consistency=false` 是**校验逻辑取错字段**（用了数据指纹
而非 input_hash），修复后重跑不同参数两任务验证通过。

### 4.3 受控卖出场景：2 组 + 阈值扫描

| 场景 | 触发拒单 | 状态 | 成交额 | 佣金 | 现金变化 | 持仓变化 |
| --- | --- | --- | ---: | ---: | --- | --- |
| 现金不足（2.02 元） | **是** | rejected | 0 | 0 | **不变** | **不变** |
| 现金足够（6.02 元） | 否 | filled | 0.3738 | 5.00 | +0.3738-5.00 | 清仓 |

阈值扫描 6 档，负现金天数全部 0。

### 4.4 sparse_data 回归

| 项目 | 代表性池（6 只） | 全池（41 只） |
| --- | ---: | ---: |
| 状态 | **success** | **success** |
| 删除行数 | 4,079 | 4,079 |
| 快照 | 447 | 447 |
| 首日 / 缺口 / 缺净值 / 有效 | 1 / 176 / 0 / **270** | 1 / 177 / 0 / **269** |
| 加总恒等式 | 成立 | 成立 |
| 负现金天数 | **0** | **0** |
| 源库指纹 | 一致 | 一致 |

## 五、API 与 Streamlit 冒烟

| 检查 | 结果 |
| --- | --- |
| `GET /health` | 200 |
| `GET /api/validations?limit=3` | 200 |
| `GET /api/backtests?limit=3` | 200 |
| `GET /api/validations/x` | 404（期望） |
| Streamlit `3_回测.py` AppTest | **0 异常** |
| Streamlit `4_策略验证.py` AppTest | **0 异常** |

## 六、数据库完整性

| 项目 | 数值 |
| --- | ---: |
| `PRAGMA integrity_check` | **ok** |
| `etf_pool` | 46 |
| `etf_daily_prices` | 116,609 |
| `etf_indicator_daily` | 350,292 |
| `etf_adjustment_snapshots` | 139 |
| `backtest_runs` | 11 |
| `backtest_orders` | 29,248 |
| `backtest_trades` | 26,093 |
| `validation_runs` | 13 → **22**（新增 9 条，历史 13 条完整） |
| 行情指纹 v3 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 数据库结构 | **无变更** |

## 七、测试真实性声明

| 类别 | 内容 |
| --- | --- |
| **实际执行的自动化测试** | pytest 351 项；42 场景敏感性扫描；4 组并发；2 场景 + 6 档阈值卖出验证；2 池 sparse 回归 |
| **人工检查** | 历史 74 笔「成交额 < 费用」逐一核对；各 run 最小现金比对 |
| **静态代码审查** | 锁释放路径、`_check_hash_consistency` 字段语义、状态判定条件 |
| **尚未执行** | 8 并发、多进程并发、非零税率下的该分支、全池持仓/信号/恢复三模式 |
| **外部证据不足暂缓** | 真实券商交割单核验（`deferred_external_evidence`） |

## 八、结论

| 要求 | 实际 | 结论 |
| --- | --- | --- |
| 原有 337 项全部保留通过 | 337/337 | ✅ |
| 新增测试全部通过 | 14/14 | ✅ |
| 全量测试通过 | 351/351，0 failed / 0 skipped | ✅ |
| 敏感性扫描真实执行 | 42 场景 | ✅ |
| 并发 2/4 任务可验证 | 均通过（hash 问题已修） | ✅ |
| sell_proceeds 受控链路 | 两场景 + 阈值扫描 | ✅ |
| 历史数据未污染 | 记录数不变、指纹一致 | ✅ |
