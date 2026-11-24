# 阶段3B-6.1.0.3.1 测试报告

- 本轮基线 HEAD：`51bb73073fca0e0840e3d3b490ea893866558844`
- 执行时间：2026-11-24 18:51

> **严格区分**：真实执行 pytest / 静态检查 / 数据源调用 / **未实际执行**的检查。

---

## 0. 本轮的核心：测试具备真正的独立复算能力

### 0.1 修正前的问题

原 `test_3b6_1_0_3_coverage.py` 主要**读取证据里已算好的状态字段**，
再与报告做一致性比对。这只证明了「两个文件写得一样」，
**不能证明状态计算逻辑本身正确**。

### 0.2 修正后：从最原始字段独立复算

新增 `tests/test_3b6_1_0_3_1_recompute.py`（17 项）：

```bash
$ pytest tests/test_3b6_1_0_3_1_recompute.py -q
17 passed in 0.52s
```

| 状态 | 独立复算依据 |
| --- | --- |
| `history_retrieved` | 实际 `rows` > 0 |
| `history_range_verified` | `date_min`/`date_max` 可解析且 `date_max >= date_min` |
| `history_coverage_adequate` | **从 `real_start_date`/`date_max`/请求起点重算比率**，**不复用 `coverage_ratio`** |
| `history_quality_adequate` | 从 `duplicate_dates`/`null_close`/`non_positive_close`/`max_interior_gap_days` 重算 |
| `backtest_usable` | 前四项 **且** `return_basis != unknown` |

### 0.3 复算与证据/报告逐项一致

| 测试 | 校验对象 |
| --- | --- |
| `test_recompute_retrieved` | 27 个代码的 `history_retrieved` |
| `test_recompute_range_verified` | 27 个代码的 `history_range_verified` |
| `test_recompute_coverage_independently` | 27 个代码的覆盖率与达标判定 |
| `test_recompute_quality_independently` | 27 个代码的质量达标判定 |
| `test_recompute_backtest_usable` | 全部必须为 false |
| `test_report_states_match_recompute` | 10 个指数的五态与复算一致 |
| `test_report_price_and_net_quality_match_recompute` | 价格/净收益层也复算 |
| `test_summary_counts_match_recompute` | summary 统计 == 独立重数结果 |

### 0.4 阈值不得偷偷放宽

```python
COVERAGE_MIN_RATIO = 0.95
INTERIOR_GAP_MAX_DAYS = 20
REQUEST_START = "2004-01-01"
```

`test_thresholds_match_evidence_declaration` 校验这三个常量
**必须与证据声明的标准一致**——改测试常量会立刻失败。

### 0.5 五态不得退化为单向继承

`test_five_states_not_single_chain` 要求证据中存在：

- `retrieved=true` 但 `coverage=false` 的实例（`399997`/`930930`）
- `range=true` 但 `quality=false` 的实例（`H20184` 等）
- 覆盖质量全过但 `backtest_usable=false` 的实例

**如果五态被简化成自动继承，这三点必然失败。**

---

## 1. 新增文档口径测试（16 项）

```bash
$ pytest tests/test_3b6_1_0_3_1_docs.py -q
16 passed in 0.62s
```

| 测试 | 断言 |
| --- | --- |
| `test_deprecated_field_marked_in_design` | `00_design` 中旧字段带废弃标记 |
| `test_deprecated_field_marked_in_ingestion` | `05_ingestion` 同上 |
| `test_deprecated_field_marked_in_readme` | README 同上 |
| `test_deprecated_marked_in_changelog` | CHANGELOG 同上 |
| `test_no_blanket_row_count_claim` | 无「2004年至今 5,318 行/序列」笼统结论 |
| `test_real_per_index_coverage_documented` | 逐指数真实起点与行数都在文档里 |
| `test_readme_documents_per_index_coverage` | README 含 52.5% / 78.2% |
| `test_399997_930930_not_described_as_long_term_usable` | 不得描述为可长周期回测 |
| `test_ingestion_keeps_original_blockers` | 原有阻断结论保留 |
| `test_research_vs_backtest_distinction` | 未把研究可用写成回测可用 |
| `test_non_positive_register_complete` | 非正值覆盖三层 |
| `test_non_positive_documented_in_source_quality` | 5 个代码都在 04 里 |
| `test_non_positive_documented_in_readme` | 同上 README |
| `test_anomaly_layer_separation_in_json` | JSON 三层字段齐全 |
| `test_gate_unchanged` | 门禁三值 |
| `test_return_basis_all_unknown` | 口径全 unknown |

---

## 2. 测试卫生清理

| 项 | 位置 | 处理 |
| --- | --- | --- |
| `or True` 恒真断言 | `test_3b6_1_0_3_coverage.py` 1 处 | **改为真断言** `< 0.95` |
| 未使用变量 `std` | 同上 | 删除 |
| 未使用变量 `layer` | `test_3b6_1_0_3_1_recompute.py` | 删除 |
| 未使用变量 `code` | 同上 | 改为 `.values()` |
| 未使用变量 `md` | `test_3b6_1_0_2_consistency.py` | 删除 |
| 未使用变量 `fa`/`fr` | `test_3b6_1_0_1_audit_fix.py` | 改为直接判断 |

`test_no_vacuous_assertions` 会扫描本测试文件，防止再引入恒真断言。

---

## 3. 全量 pytest（真实执行）

```bash
$ pytest -q
2034 passed, 1 warning in 825.16s (0:13:45)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **2034** |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | **0** |
| 耗时 | 825.16 秒 |

**演进**：2001（3B-6.1.0.3）→ **2034**（+33）

| 新增来源 | 数量 |
| --- | ---: |
| `test_3b6_1_0_3_1_recompute.py` | 17 |
| `test_3b6_1_0_3_1_docs.py` | 16 |
| **合计** | **33** |

---

## 4. 相关回归（真实执行）

```bash
$ pytest tests/test_3b6_1_0_audit.py tests/test_3b6_1_0_1_audit_fix.py \
        tests/test_3b6_1_0_2_consistency.py tests/test_3b6_1_0_2_hist_evidence.py \
        tests/test_3b6_1_0_3_coverage.py tests/test_3b6_1_0_3_1_recompute.py \
        tests/test_3b6_1_0_3_1_docs.py -q
132 passed in 1.49s
```

```bash
$ pytest tests/test_3b6_0_4_1_lof_and_grade.py tests/test_3b6_0_4_peer_comparison.py \
        tests/test_3b6_0_4_share_cost_and_groups.py -q
88 passed
```

---

## 5. 静态检查（**不计入** 2034）

| 项 | 性质 | 是否执行 |
| --- | --- | --- |
| `python -m compileall` | 静态 | ✅ |
| JSON 合法性校验（8 份） | 静态 | ✅ |
| AST 未使用变量扫描 | 静态 | ✅（发现 6 处已修） |
| PDF 文本提取 | 静态解析 | 复用上轮 |

---

## 6. 数据源实际调用（真实执行，非测试）

| 项 | 次数 |
| --- | ---: |
| 指数接口调用 | **0** |

**本轮未调用任何数据接口**——全部复用 3B-6.1.0.3 已入库的证据附件。

---

## 7. 未实际执行的检查（如实声明）

| 检查项 | 状态 | 原因 |
| --- | --- | --- |
| 重新探测指数历史 | **未执行** | 复用已入库证据附件 |
| 重新下载官方 PDF | **未执行** | 同上 |
| 独立第二数据源交叉验证 | **未执行** | 东财限流未解决 |
| 中债债券指数接口探测 | **未执行** | 超出本轮范围 |
| 历史权重官方文件检索 | **未执行** | 同上 |

---

## 8. 正式数据库只读验证

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

## 9. 文件改动清单

| 文件 | 类型 |
| --- | --- |
| `tests/test_3b6_1_0_3_1_recompute.py` | **新增**（17 项独立复算） |
| `tests/test_3b6_1_0_3_1_docs.py` | **新增**（16 项文档口径） |
| `tests/test_3b6_1_0_3_coverage.py` | **修改**（清 `or True` 与未用变量） |
| `tests/test_3b6_1_0_2_consistency.py` | **修改**（清未用变量） |
| `tests/test_3b6_1_0_1_audit_fix.py` | **修改**（清未用变量） |
| `reports/phase3B6_1_0_01_index_return_basis.json` | **修改**（补 `anomaly_by_series` + 非正值登记表） |
| `reports/phase3B6_1_0_00/04/05` | **修改**（清理过时结论） |
| `README.md`、`CHANGELOG.md` | **修改** |
| `app/**` 业务代码 | **未改** |
| Schema / 迁移 | **未改** |
| 证据附件 | **未改**（复用） |

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
