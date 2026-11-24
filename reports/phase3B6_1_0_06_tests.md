# 阶段3B-6.1.0.2 测试报告

- 本轮基线 HEAD：`f570012330e650f219acebe1f37cfe934c141475`
- 执行时间：2026-11-24 17:08

> **严格区分**：真实执行 pytest / 静态检查 / 数据源调用 / **未实际执行**的检查。

---

## 0. 本轮新增的两组一致性测试（34 项）

### 0.1 `tests/test_3b6_1_0_2_consistency.py`（27 项）

```bash
$ pytest tests/test_3b6_1_0_2_consistency.py -q
27 passed in 0.76s
```

| 覆盖要求 | 对应测试 |
| --- | --- |
| 1. summary 数量与明细数组一致 | `test_summary_counts_equal_detail_lengths`、`test_summary_total_matches_indexes`、`test_summary_numbers_not_handwritten` |
| | `test_summary_categories_are_exhaustive_and_exclusive` |
| 2. Markdown 统计与 JSON 一致 | `test_markdown_category_counts_match_json`、`test_markdown_three_layers_match_json` |
| 3. factsheet 字段与证据一致 | `test_factsheet_fields_match_evidence`、`test_markdown_factsheet_table_matches_json` |
| 4. 下载状态有真实元数据 | `test_factsheet_download_backed_by_real_metadata` |
| 5. 代码存在 ≠ 完整历史 | `test_code_identified_does_not_imply_full_history` |
| 6. 短窗口 ≠ 完整历史 | `test_short_probe_does_not_imply_full_history` |
| 7. 不可用不得标可用 | `test_unavailable_history_not_marked_available`、`test_specific_indexes_history_status_accurate` |
| 8. 000051 无无证据表述 | `test_000051_no_unsupported_interpretation`、`test_000051_requires_accurate_description` |
| | `test_000051_declares_not_stateable`、`test_markdown_000051_uses_accurate_wording` |
| 9. 固定收益率不入权重和 | `test_000051_fixed_rate_not_in_weight_sum` |
| 10. return_basis 全 unknown | `test_all_return_basis_still_unknown` |
| 11-12. 门禁不变 | `test_gates_unchanged` |
| 附加：三层独立复算 | `test_three_layers_are_not_conflated`、`test_layers_derived_from_real_evidence` |
| 附加：只读 | `test_no_database_write`、`test_reports_have_no_deprecated_category_names` |

**测试未硬编码统计数字**，全部分类数量由 `detail` 数组长度复算。

### 0.2 `tests/test_3b6_1_0_2_hist_evidence.py`（7 项）

```bash
$ pytest tests/test_3b6_1_0_2_hist_evidence.py -q
7 passed in 0.46s
```

| 测试 | 断言 |
| --- | --- |
| `test_hist_evidence_exists` | 证据附件含 `full_history_probe` 段 |
| `test_total_history_matches_evidence` | 全收益历史状态/行数/起止与证据逐项一致 |
| `test_net_history_matches_evidence` | 净收益历史状态与证据一致 |
| `test_price_history_matches_evidence` | 价格行数与缺口与证据一致 |
| `test_no_placeholder_rows_in_evidence` | 证据里无占位行、无重复日期 |
| `test_evidenced_differences_documented` | 已知非正值异常留痕 |
| `test_gate_still_closed` | 门禁三值 |

**这组测试让第三层（完整历史）也能在干净仓库复核，不依赖本地缓存。**

---

## 1. 全量 pytest（真实执行）

```bash
$ pytest -q
1979 passed, 1 warning in 827.01s (0:13:47)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1979** |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | **0** |
| 耗时 | 827.01 秒 |

**演进**：1945（3B-6.1.0.1）→ **1979**（+34 本轮新增）

---

## 2. 相关回归（真实执行）

```bash
$ pytest tests/test_3b6_1_0_audit.py tests/test_3b6_1_0_1_audit_fix.py -q
43 passed
```

```bash
$ pytest tests/test_3b6_0_4_1_lof_and_grade.py tests/test_3b6_0_4_peer_comparison.py \
        tests/test_3b6_0_4_share_cost_and_groups.py -q
88 passed
```

---

## 3. 静态检查（**不计入** 1979）

| 项 | 性质 | 是否执行 |
| --- | --- | --- |
| `python -m compileall` 脚本语法 | 静态 | ✅ 执行 |
| JSON 合法性校验（7 份报告 + 1 份证据） | 静态 | ✅ 执行 |
| PDF 文本提取（18 份官方文件） | 静态解析 | ✅ 执行 |

**这些不是测试，不计入 1979。**

---

## 4. 数据源实际调用（真实执行，非测试）

| 接口 / 动作 | 次数 | 用途 |
| --- | ---: | --- |
| `stock_zh_index_hist_csindex`（完整历史） | **17** | 补探测全收益/净收益/价格完整历史 |
| `stock_zh_index_hist_csindex`（短窗口） | 0 | 本轮未重跑（复用 3B-6.1.0.1 证据） |
| 官方 PDF HTTP 下载 | 0 | 本轮未下载（复用 3B-6.1.0.1 已下载文件） |
| **合计** | **17** | |

---

## 5. 未实际执行的检查（如实声明）

| 检查项 | 状态 | 原因 |
| --- | --- | --- |
| 重新下载并核验官方 PDF | **未执行** | 复用 3B-6.1.0.1 已下载文件（sha256 已记录，可校验） |
| 用独立第二数据源交叉验证指数点位 | **未执行** | 上轮已确认东财限流，本轮无新增来源 |
| 中债债券指数接口探测 | **未执行** | 本轮范围限定为一致性问题修正 |
| 历史权重官方文件检索 | **未执行** | 同上 |

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
| `tests/test_3b6_1_0_2_consistency.py` | **新增**（27 项） |
| `tests/test_3b6_1_0_2_hist_evidence.py` | **新增**（7 项） |
| `reports/evidence/phase3B6_1_0_index_probe_evidence.json` | **修改**（新增 `full_history_probe`） |
| `reports/phase3B6_1_0_00/01/02/04/05/06` | **修改**（一致性修正） |
| `app/**` 业务代码 | **未改** |
| Schema / 迁移 | **未改** |
| 既有测试 | **零删除、零弱化** |

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
