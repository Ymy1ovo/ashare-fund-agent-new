# 阶段3B-6.0.2 测试报告（3B-6.0.2.2 修正版）

- 基线 HEAD：`ae1dc1979bd32f85341e691405b2310b9d0ea84b`
- 执行日期：2026-11-24
- 修正轮：3B-6.0.2.2（复合基准有效行情判定补强）

> 区分：**真实执行测试** / **静态检查** / **数据源实际调用**。

本轮数据源实际调用 = **0 次**（禁止重新采集）。

---

## 1. 本轮新增专项（24 项）

```bash
$ pytest tests/test_3b6_0_2_2_effective_observations.py -q
24 passed in 7.09s
```

### 1.1 任务书要求的场景

| 要求 | 测试 | 断言 |
| --- | --- | --- |
| A 10 条全 suspect | `test_A_all_suspect_not_available` | valid_rows=0，不可用，原因含「没有有效行情」 |
| B 10 条全 rejected | `test_B_all_rejected_not_available` | 同上 |
| C 只有 1 条 valid | `test_C_single_valid_not_available` | 原因含「有效行情不足」「至少需要 2」 |
| D 2 条 valid + total_return | `test_D_two_valid_with_total_return_available` | available=1 |
| E 2 条 valid + unknown | `test_E_two_valid_but_unknown_not_available` | valid_rows=2 但 available=0，原因含 unknown |
| F 之后有效行情被降级 | `test_F_reevaluate_detects_degradation` | 再次评估 → 不可复现 |
| G 15 条正式复合基准 | `test_G_production_composites_none_reproducible` | total=15, repro=0 |
| H 10 个指数口径 + 行数 | `test_H_*` | 全 unknown，50,603 行不变 |

### 1.2 补充边界

| 测试 | 覆盖 |
| --- | --- |
| `test_B2_mixed_quality_only_valid_counted` | 混合质量只数 valid |
| `test_C2_min_observations_is_two` | 常量 = 2 |
| `test_C3_null_close_blocked_at_schema` | 空收盘被 NOT NULL 拒绝 |
| `test_C4_non_positive_close_not_counted` | 0/负数不计 |
| `test_D2_net_total_return_also_available` | net_total_return 通过 |
| `test_E2_two_valid_but_price_return_not_available` | price_return 拒绝 |
| `test_F2_reevaluate_detects_rows_deleted` | 行被删到 1 条 → 阻止 |
| `test_F3_reevaluate_detects_basis_downgrade` | 口径被改 unknown → 阻止 |
| `test_F4_stale_flag_does_not_stick` | 人为回填旧标记也无效 |
| `test_cash_component_rule_unchanged` | 现金规则不变 |
| `test_single_component_rule_unchanged` | 单成分规则不变 |
| `test_weight_rule_unchanged` | 权重规则不变 |
| `test_H3_production_all_indices_assessed_unavailable` | 10 个指数重新判定全不可用 |
| `test_H4_stale_component_flag_does_not_leak` | 存量标记不泄漏成可复现 |
| `test_gate_unchanged` | 门禁 |

---

## 2. 变异验证（证明测试有约束力）

| 变异 | 失败测试数 | 失败项 |
| --- | ---: | --- |
| 忽略 `quality_status`（退回总行数） | **5** | A、B、B2、F、F4 |
| `MIN_VALID_OBSERVATIONS = 1` | **4** | C、C2、C4、F2 |
| `evaluate_composite` 信任历史 `data_available` | **4** | F、F2、F3、F4 |

三类变异各自被独立测试守住。验证后全部还原。

---

## 3. 回归测试

### 3.1 3B-6.0.2.1 原始质量与口径专项

```bash
$ pytest tests/test_3b6_0_2_1_raw_quality_and_basis.py -q
22 passed
```

### 3.2 3B-6.0.2 指数数据层

```bash
$ pytest tests/test_3b6_0_2_index_layer.py -q
46 passed
```

### 3.3 三套合并

```bash
$ pytest tests/test_3b6_0_2_2_effective_observations.py \
        tests/test_3b6_0_2_1_raw_quality_and_basis.py \
        tests/test_3b6_0_2_index_layer.py -q
92 passed in 35.19s
```

### 3.4 3B-6.0.1 / 3B-6.0.1.1

```bash
$ pytest tests/test_3b6_0_1_benchmark_audit.py \
        tests/test_3b6_0_1_1_index_verify.py -q
61 passed in 21.19s
```

### 3.5 3B-5.5 系列

```bash
$ pytest tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
112 passed in 137.62s (0:02:17)
```

---

## 4. 全量测试

```bash
$ pytest -q
1782 passed, 1 warning in 673.98s (0:11:13)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1782** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 673.98 秒 |

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-6.0.2.1 | 1758 |
| **3B-6.0.2.2** | **1782** |

1758 + 24 = 1782。

**未删除、未弱化任何既有测试。**

---

## 5. 数据源实际调用

| 项 | 本轮 |
| --- | --- |
| 中证官网接口 | **0 次** |
| 指数行数变化 | **0** |
| 收益口径变化 | **0** |

---

## 6. 静态检查（不计入 1782）

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

## 8. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/composite_benchmark.py` | **修改** | 新增有效行情判定，evaluate 重新计算 |
| `tests/test_3b6_0_2_2_effective_observations.py` | **新增** | 24 项专项 |
| `tests/test_3b6_0_2_1_*.py` | **未改** | — |
| `tests/test_3b6_0_2_index_layer.py` | **未改** | — |
| `app/fund/index_layer.py` / `index_ingest.py` | **未改** | — |
| `app/fund/index_returns.py` | **未改** | — |
| `engine.py` / `indicators.py` / `quality.py` | **未改** | — |
| Schema / 迁移 | **未改** | — |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
