# 阶段3B-6.0.2 测试报告（3B-6.0.2.3 修正版）

- 基线 HEAD：`95f7d0aa4346c31b354379b7ab7fed8982764d5f`
- 执行日期：2026-11-24
- 修正轮：3B-6.0.2.3（有效行情「有限正数」校验补强）

> 区分：**真实执行测试** / **静态检查** / **数据源实际调用**。

本轮数据源实际调用 = **0 次**。

---

## 1. 本轮新增专项（32 项）

```bash
$ pytest tests/test_3b6_0_2_3_finite_positive_close.py -q
32 passed in 6.94s
```

### 1.1 任务书要求的数值场景

| 值 | 测试 | 结果 |
| --- | --- | --- |
| `+inf` | `test_inf_not_counted` | 不计入 ✅ |
| `-inf` | `test_negative_inf_not_counted` | 不计入 ✅ |
| `NaN` | `test_nan_becomes_null_and_rejected_by_schema` | 驱动转 NULL，被 NOT NULL 拒绝 ✅ |
| `0` | `test_zero_and_negative_not_counted` | 不计入 ✅ |
| `-1` | `test_zero_and_negative_not_counted` | 不计入 ✅ |
| 有限正数 | `test_normal_finite_positive_counted` | 计入 ✅ |

### 1.2 核心场景（`assess_index_component` 实验证）

| 测试 | 构造 | 断言 |
| --- | --- | --- |
| `test_assess_inf_plus_normal_only_one_valid` | **2 条**：1 条 `+inf` + 1 条正常 | 总行数 2，**有效仅 1**，`available=0`，原因含「至少需要 2」|
| `test_assess_inf_plus_two_normal_available` | 3 条：`+inf` + 2 条正常 | 有效 2，`available=1` |
| `test_assess_only_inf_not_available` | 2 条全 `+inf` | 有效 0，原因含「没有有效行情」|
| `test_assess_negative_inf_not_available` | 2 条全 `-inf` | 有效 0 |
| `test_assess_inf_does_not_bypass_basis_check` | 2 正常 + 1 `inf`，口径 unknown | 有效 2 但不可用 |

### 1.3 复合基准端到端

| 测试 | 覆盖 |
| --- | --- |
| `test_composite_with_inf_component_not_available` | 含 inf 的指数成分 → `data_available=0` |
| `test_composite_reproducible_only_with_finite_positives` | 两成分各 2 条有限正数 → 可复现 |
| `test_evaluate_reevaluates_after_inf_injected` | 先可复现，注入 inf 后再次评估 → 不可复现 |

### 1.4 辅助函数与守恒

| 测试 | 覆盖 |
| --- | --- |
| `test_is_usable_close_rejects_non_finite_or_non_positive` | 7 个非法值参数化 |
| `test_is_usable_close_accepts_finite_positive` | 5 个合法值参数化 |
| `test_uses_isfinite_not_self_compare` | 证明 `v != v` 抓不到 inf |
| `test_production_no_infinite_close` | 正式库无 inf；**记录 1 条已知 0.0** |
| `test_production_zero_close_never_counted` | 该 0.0 从未计入有效观测 |
| `test_production_*` | 行数/口径/复合基准守恒 |

---

## 2. 变异验证

把判定退回旧写法 `c == c and c > 0`（等价于 `c != c or c <= 0` 的漏洞版）：

```
9 failed, 23 passed
```

失败项覆盖 inf 全部路径：

```
test_inf_not_counted
test_assess_inf_plus_normal_only_one_valid
test_assess_inf_plus_two_normal_available
test_assess_only_inf_not_available
test_assess_inf_does_not_bypass_basis_check
test_composite_with_inf_component_not_available
test_evaluate_reevaluates_after_inf_injected
```

验证后已还原，`git diff` 确认 `math.isfinite(c) and c > 0` 在位。

---

## 3. 回归测试

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| 3B-6.0.2.2 | `pytest tests/test_3b6_0_2_2_effective_observations.py -q` | 24 passed |
| 3B-6.0.2.1 | `pytest tests/test_3b6_0_2_1_raw_quality_and_basis.py -q` | 22 passed |
| 3B-6.0.2 指数层 | `pytest tests/test_3b6_0_2_index_layer.py -q` | 46 passed |
| **三套合并** | 上述三个文件 | **92 passed / 33.30s** |
| 3B-6.0.1 系列 | `pytest tests/test_3b6_0_1_benchmark_audit.py tests/test_3b6_0_1_1_index_verify.py -q` | **61 passed / 20.84s** |
| 3B-5.5 系列 | `pytest tests/test_3b5_5_quality_framework.py tests/test_3b5_5_1_peer_annualized.py -q` | **112 passed / 146.18s** |

---

## 4. 全量测试

```bash
$ pytest -q
1814 passed, 1 warning in 658.73s (0:10:58)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1814** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 658.73 秒 |

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-6.0.2.2 | 1782 |
| **3B-6.0.2.3** | **1814** |

1782 + 32 = 1814。

**未删除、未弱化、未修改任何历史断言。**

---

## 5. 数据源实际调用

| 项 | 本轮 |
| --- | --- |
| 中证官网接口 | **0 次** |
| 指数行数变化 | **0** |
| 收益口径变化 | **0** |

---

## 6. 静态检查（不计入 1814）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` | 静态 |
| JSON 合法性校验 | 静态 |

---

## 7. 数据库守恒

| 项 | 执行前 | 执行后 |
| --- | ---: | ---: |
| `fund_master` | 60 | **60** |
| `fund_share_classes` | 89 | **89** |
| `fund_nav_daily` | 80,083 | **80,083** |
| `fund_lifecycle_events` | 49 | **49** |
| 清盘本体 | 41 | **41** |
| `index_daily` | 50,603 | **50,603** |
| 指数口径 unknown | 10 | **10** |
| 复合基准可复现 | 0 | **0** |

| 指纹/检查 | 值 |
| --- | --- |
| 内容指纹 | `11c56eba1489976fa35be92586a99bc21a27e20c06e95cacab5c8ca553c05116`（未变）|
| ETF 指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`（未变）|
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

**正式数据库本轮零写入。**

---

## 8. 本轮发现的真实数据问题（如实记录）

核对正式库时发现 1 条异常行：

| 字段 | 值 |
| --- | --- |
| 指数 | `H30184` |
| 日期 | `2013-06-28` |
| `close` | **`0.0`** |
| `quality_status` | `valid` |

| 项 | 说明 |
| --- | --- |
| 本轮是否修改 | **否**（任务书禁止修改 50,603 条行情）|
| 是否影响判定 | **否**：修复前后都不被计入（旧 `c <= 0` 排除，新 `c > 0` 排除）|
| 该指数现状 | 有效 5,314 条，远超门槛，但口径 `unknown` 仍不可用 |
| 建议 | 后续数据修补轮单独处理 |

---

## 9. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/composite_benchmark.py` | **修改** | 新增 `_is_usable_close()`，改用 `math.isfinite` |
| `tests/test_3b6_0_2_3_finite_positive_close.py` | **新增** | 32 项专项 |
| `tests/test_3b6_0_2_2_*.py` | **未改** | — |
| `tests/test_3b6_0_2_1_*.py` | **未改** | — |
| `tests/test_3b6_0_2_index_layer.py` | **未改** | — |
| `app/fund/index_layer.py` / `index_ingest.py` / `index_returns.py` | **未改** | — |
| `engine.py` / `indicators.py` / `quality.py` | **未改** | — |
| Schema / 迁移 | **未改** | — |

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
