# 阶段3B-6.1.0.3 测试报告

- 本轮基线 HEAD：`472f4a531da250cfe301c22c4668f52ac760a470`
- 执行时间：2026-11-24 17:39

> **严格区分**：真实执行 pytest / 静态检查 / 数据源调用 / **未实际执行**的检查。

---

## 0. 新增覆盖质量专项测试（22 项）

```bash
$ pytest tests/test_3b6_1_0_3_coverage.py -q
22 passed in 0.52s
```

| 任务要求 | 对应测试 |
| --- | --- |
| 1. retrieved 不自动等于 coverage | `test_retrieved_does_not_imply_coverage` |
| 2. range_verified 不自动等于 quality | `test_range_verified_does_not_imply_quality` |
| 3. 重大缺口不得标连续覆盖达标 | `test_major_gap_blocks_coverage` |
| 4. 399997/930930 不得标完整覆盖 | `test_399997_not_marked_full_coverage`、`test_930930_not_marked_full_coverage` |
| 5. 000012 不计入股票指数统计 | `test_bond_index_excluded_from_equity_stats` |
| 6. 占位行不计入有效覆盖 | `test_baseline_placeholder_not_counted`、`test_365_gap_is_baseline_placeholder`、`test_no_placeholder_for_true_dense_series` |
| 7. 非正值异常必须保留 | `test_non_positive_values_preserved` |
| 8. 回测不可用原因可追溯 | `test_backtest_blockers_per_index`、`test_backtest_usable_zero` |
| 9. return_basis 全 unknown | `test_all_return_basis_unknown` |
| 10. 门禁仍 false | `test_gates_still_false` |
| 11. MD/JSON/证据一致 | `test_markdown_five_states_match_json`、`test_rate_breakdown_matches_stats`、`test_report_quality_matches_evidence`、`test_evidence_standard_declared` |
| 12. 不改数据库 | `test_no_database_write` |
| 附加：五态独立字段 | `test_five_states_are_independent_fields` |
| 附加：无废弃字段 | `test_no_deprecated_broad_field` |
| 附加：统计可复算 | `test_summary_stats_recomputed_from_indexes` |

**全部断言从证据附件与报告结构计算，未硬编码预期结果。**

### 0.1 旧测试同步升级（未删断言）

| 文件 | 变更 |
| --- | --- |
| `tests/test_3b6_1_0_2_consistency.py` | 三层 → 五态；分类数组 → 经济语义分组；**仍 27 项** |
| `tests/test_3b6_1_0_2_hist_evidence.py` | 改读 `coverage_quality_probe`；**仍 7 项** |

**零删除、零弱化**——只是让断言匹配新的五态字段名，判定强度不降反升。

---

## 1. 全量 pytest（真实执行）

```bash
$ pytest -q
2001 passed, 1 warning in 778.48s (0:12:58)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **2001** |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | **0** |
| 耗时 | 778.48 秒 |

**演进**：1979（3B-6.1.0.2）→ **2001**（+22 本轮新增）

---

## 2. 相关回归（真实执行）

```bash
$ pytest tests/test_3b6_1_0_audit.py tests/test_3b6_1_0_1_audit_fix.py \
        tests/test_3b6_1_0_2_consistency.py tests/test_3b6_1_0_2_hist_evidence.py \
        tests/test_3b6_1_0_3_coverage.py -q
99 passed in 1.32s
```

```bash
$ pytest tests/test_3b6_0_4_1_lof_and_grade.py tests/test_3b6_0_4_peer_comparison.py \
        tests/test_3b6_0_4_share_cost_and_groups.py -q
88 passed
```

---

## 3. 静态检查（**不计入** 2001）

| 项 | 性质 | 是否执行 |
| --- | --- | --- |
| `python -m compileall` | 静态 | ✅ |
| JSON 合法性校验（8 份） | 静态 | ✅ |
| PDF 文本提取（18 份） | 静态解析 | ✅（复用上轮结果） |

---

## 4. 数据源实际调用（真实执行，非测试）

| 接口 | 次数 | 用途 |
| --- | ---: | --- |
| `stock_zh_index_hist_csindex` | **27** | 覆盖质量探测（逐代码取全量历史并分析缺口结构） |
| **合计** | **27** | |

---

## 5. 未实际执行的检查（如实声明）

| 检查项 | 状态 | 原因 |
| --- | --- | --- |
| 重新下载官方 PDF | **未执行** | 复用 3B-6.1.0.1 已下载文件，sha256 已记录 |
| 独立第二数据源交叉验证 | **未执行** | 东财限流未解决 |
| 中债债券指数接口探测 | **未执行** | 超出本轮一致性修正范围 |
| 历史权重官方文件检索 | **未执行** | 同上 |
| 补充 000051 合同原文核验 | **未执行** | 沿用平台基准文本 |

---

## 6. 正式数据库只读验证

| 项 | 值 |
| --- | --- |
| 内容指纹（本轮前） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| 内容指纹（本轮后） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| **是否变化** | **✅ 未变** |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

| 表 | 行数 |
| --- | ---: |
| `index_master` | 10 |
| `index_daily` | 50,603 |
| `benchmark_composite` | 15 |
| `benchmark_composite_component` | 34 |
| `fund_master` | 120 |

---

## 7. 文件改动清单

| 文件 | 类型 |
| --- | --- |
| `tests/test_3b6_1_0_3_coverage.py` | **新增**（22 项） |
| `tests/test_3b6_1_0_2_consistency.py` | **修改**（三层→五态，仍 27 项） |
| `tests/test_3b6_1_0_2_hist_evidence.py` | **修改**（改读新证据段，仍 7 项） |
| `reports/evidence/phase3B6_1_0_index_probe_evidence.json` | **修改**（新增 `coverage_quality_probe`，27 个代码） |
| `reports/phase3B6_1_0_00/01/04/05` | **修改** |
| `app/**` 业务代码 | **未改** |
| Schema / 迁移 | **未改** |

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
