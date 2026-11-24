# 阶段3B-6.0.2 测试报告（3B-6.0.2.1 修正版）

- 基线 HEAD：`6c9405411737f42776962e0a87ce5f97112462ca`
- 执行日期：2026-11-24
- 修正轮：3B-6.0.2.1

> 区分三类：**真实执行测试** / **静态检查** / **数据源实际调用**。

在本轮中：数据源实际调用 = **0 次**（禁止重新采集）。

---

## 1. 本轮新增专项测试（22 项）

```bash
$ pytest tests/test_3b6_0_2_1_raw_quality_and_basis.py -q
22 passed in 6.33s
```

### 1.1 阻断一：原始质检顺序（10 项）

| 测试 | 覆盖要求 |
| --- | --- |
| `test_A_duplicate_dates_rejected_at_ingest` | A 重复日期：ok=False、0 行入库、审计保留、质量记录反映重复 |
| `test_A2_duplicate_not_hidden_by_dedup` | 重复未被字典覆盖掩盖 |
| `test_B_descending_dates_rejected_at_ingest` | B 倒序：ok=False、0 行入库、质量记录反映倒序 |
| `test_B2_descending_not_hidden_by_sort` | 倒序未被排序掩盖 |
| `test_C_normal_data_ingested` | C 正常：5 行正常入库 |
| `test_C2_normal_order_preserved_in_result` | 正常数据日期区间正确 |
| `test_raw_quality_runs_before_normalization` | 顺序证明：原始 5 行如实进质检 |
| `test_rejected_data_leaves_no_daily_rows` | 被拒数据不留行 |
| `test_master_recorded_on_quality_failure` | 失败仍登记 master 便于追溯 |

**全部直接调用真实采集入口 `collect_one()`**，非只测质量函数。

### 1.2 阻断二：复合基准收益口径（9 项）

| 测试 | 覆盖要求 |
| --- | --- |
| `test_D_unknown_basis_blocks_reproducible` | A 类：unknown → 不可复现，原因指出口径未知 |
| `test_D2_unknown_component_marked_unavailable` | unknown → `data_available=0` |
| `test_E_price_return_blocks_reproducible` | B 类：price_return → 拒绝，原因指出不含分红 |
| `test_F_total_return_passes_basis_but_others_block` | C 类：total_return 通过，其他成分缺失仍不可复现 |
| `test_G_net_total_return_passes_and_kept_distinct` | D 类：net_total_return 通过且保持独立标识 |
| `test_H_cash_still_blocks_even_with_good_basis` | 现金成分仍阻塞 |
| `test_I_missing_weight_still_not_reproducible` | F 类：缺权重不可复现且不补造 |
| `test_J_fake_series_is_not_total_return` | 有行情 ≠ 可用于总收益 |

### 1.3 正式库现状（4 项）

| 测试 | 断言 |
| --- | --- |
| `test_K_production_all_indices_unknown` | 10 个指数仍全部 unknown，其他口径为 0 |
| `test_L_production_composites_none_reproducible` | 15 条复合基准，可复现 0 |
| `test_M_production_index_rows_unchanged` | 指数行数仍 50,603 |
| `test_N_production_basis_not_touched_by_tests` | 跑完测试后口径仍全 unknown |

### 1.4 门禁（1 项）

`test_gate_unchanged`

---

## 2. 变异验证（证明测试有约束力）

### 2.1 原始质检顺序变异

把 `collect_one()` 临时改回旧顺序（先去重排序再质检）：

```
7 failed, 15 passed
```

失败项：`test_A`、`test_A2`、`test_B`、`test_B2`、
`test_raw_quality_runs_before_normalization`、
`test_rejected_data_leaves_no_daily_rows`、`test_master_recorded_on_quality_failure`

### 2.2 复合基准口径变异

| 变异范围 | 失败测试数 |
| --- | ---: |
| 只去掉 `add_component` 口径检查 | **2** |
| 只去掉 `evaluate_composite` 口径检查 | **2** |

两处检查各有测试独立守住。验证后已全部还原。

---

## 3. 既有测试调整（收紧，非放宽）

| 测试 | 调整 | 性质 |
| --- | --- | --- |
| `test_duplicate_dates_in_payload_deduped` | 改名为 `test_duplicate_dates_in_payload_rejected_at_ingest` | **收紧** |

| 项 | 旧断言 | 新断言 |
| --- | --- | --- |
| 重复日期结果 | `ok is True`（去重后入库） | `ok is False`（拒绝入库） |
| 入库行数 | 5 | **0** |

**旧断言本身就是被修掉的绕过**：它断言「重复日期被去重后可以入库」，
正是本轮要禁止的行为。改为断言拒绝，是收紧不是放宽。

**未删除任何测试文件，未弱化任何其他断言。**

---

## 4. 回归测试

### 4.1 3B-6.0.2 既有专项

```bash
$ pytest tests/test_3b6_0_2_index_layer.py -q
46 passed in 16.73s
```

### 4.2 本轮 + 3B-6.0.2 合并

```bash
$ pytest tests/test_3b6_0_2_1_raw_quality_and_basis.py \
        tests/test_3b6_0_2_index_layer.py -q
68 passed in 38.96s
```

### 4.3 3B-6.0.1 / 3B-6.0.1.1 系列

```bash
$ pytest tests/test_3b6_0_1_benchmark_audit.py \
        tests/test_3b6_0_1_1_index_verify.py -q
61 passed in 20.31s
```

### 4.4 3B-5.5 系列

```bash
$ pytest tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
112 passed in 139.72s (0:02:19)
```

---

## 5. 全量测试

```bash
$ pytest -q
1758 passed, 1 warning in 714.20s (0:11:54)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1758** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 714.20 秒 |

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-6.0.2 | 1736 |
| **3B-6.0.2.1** | **1758** |

1736 + 22 = 1758。

---

## 6. 数据源实际调用

| 项 | 本轮 |
| --- | --- |
| 中证官网接口调用 | **0 次**（任务书禁止重新采集） |
| 指数行数变化 | **0** |
| 收益口径变化 | **0** |

---

## 7. 静态检查（不计入 1758）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | 静态 |
| JSON 合法性校验 | 静态 |

---

## 8. 数据库守恒

| 项 | 值 |
| --- | --- |
| `fund_master` | 60（未变） |
| `fund_share_classes` | 89（未变） |
| `fund_nav_daily` | 80,083（未变） |
| `fund_lifecycle_events` | 49（未变） |
| `index_daily` | 50,603（未变） |
| `index_master` 口径 | 10 个全 `unknown`（未变） |
| 复合基准可复现 | 0（未变） |
| 内容指纹 | `11c56eba…c05116`（未变） |
| ETF 指纹 | `d54727c0…bbcac49`（未变） |
| `integrity_check` | ok |
| 外键违规 | 0 |

**正式数据库本轮零写入。**

---

## 9. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/index_ingest.py` | **修改** | 原始质检提前，硬性失败即拒绝入库 |
| `app/fund/composite_benchmark.py` | **修改** | 增加 `return_basis` 校验（两处） |
| `tests/test_3b6_0_2_index_layer.py` | **修改** | 1 项断言收紧 |
| `tests/test_3b6_0_2_1_raw_quality_and_basis.py` | **新增** | 22 项专项 |
| `index_layer.py` / `index_returns.py` | **未改** | — |
| `engine.py` / `indicators.py` / `quality.py` | **未改** | — |
| Schema / 迁移 | **未改** | — |

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
