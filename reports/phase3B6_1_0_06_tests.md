# 阶段3B-6.1.0 测试报告

- 基线 HEAD：`eeb83bc2803d56b84986dce9d1cd93f0cb8dc1d4`  执行时间：2026-11-24 15:11

> **严格区分**：真实执行 pytest / 静态检查 / 数据源调用 / 报告生成。

---

## 1. 新增审计测试（真实执行 pytest）

```bash
# 有探测缓存时（.tmp610/raw 存在）
$ pytest tests/test_3b6_1_0_audit.py -q
17 passed in 0.52s

# 清理缓存后（干净检出，缓存不入 Git）
$ pytest tests/test_3b6_1_0_audit.py -q
14 passed, 3 skipped in 0.51s
```

### 1.1 测试覆盖

| 类别 | 测试 |
| --- | --- |
| 口径不可混用 | `test_price_basis_never_usable_for_excess` |
| | `test_net_basis_is_distinct_from_total` |
| | `test_unknown_basis_stays_unknown` |
| 复合基准阻断 | `test_composite_with_missing_cash_not_reproducible` |
| | `test_composite_with_missing_bond_not_reproducible` |
| | `test_single_component_cannot_stand_for_composite` |
| | `test_unknown_weight_blocks_even_if_data_available` |
| 实测数据校验 | `test_all_10_indexes_probed` |
| | `test_total_return_variants_actually_returned_by_source` |
| | `test_price_and_total_are_different_series` |
| 报告一致性 | `test_index_report_covers_all_10` |
| | `test_index_report_no_basis_upgraded_without_evidence` |
| | `test_composite_report_covers_all_15` |
| | `test_composite_none_reproducible_currently` |
| | `test_gate_unchanged_in_all_reports` |
| 只读保证 | `test_no_index_written_to_db` |
| | `test_no_composite_modified` |

### 1.2 skip 的准确说明

| 状态 | 结果 | 说明 |
| --- | --- | --- |
| 有缓存（`pytest -q` 全量那次） | **17 passed** | 全部真实执行 |
| 无缓存（清理后复测） | **14 passed, 3 skipped** | 3 项依赖探测缓存 |

被 skip 的 3 项：

| 测试 | 依赖 |
| --- | --- |
| `test_all_10_indexes_probed` | `.tmp610/raw/index_basis.json` |
| `test_total_return_variants_actually_returned_by_source` | 同上 |
| `test_price_and_total_are_different_series` | 同上 |

**这不是弱化断言，是环境依赖保护**——`scripts/audit_3b6_1_0_index_basis.py --probe`
可随时重建该缓存。有缓存时 17 项全部通过。

---

## 2. 全量 pytest（真实执行）

```bash
$ pytest -q
1919 passed, 1 warning in 823.28s (0:13:43)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1919** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 823.28 秒 |

**演进**：1902（3B-6.0.4.1）→ **1919**（+17 本轮新增）

---

## 3. 静态检查（**不计入** pytest）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 审计脚本 | 静态 |
| JSON 合法性校验（6 个 JSON） | 静态 |
| PDF 文本提取 | 静态解析（非测试） |

**这些不是测试。**

---

## 4. 数据源调用（真实执行，非测试）

| 接口 | 次数 |
| --- | ---: |
| `akshare.stock_zh_index_hist_csindex` | 40 |
| `akshare.bond_china_yield` | 8 |
| `akshare.macro_china_shibor_all` | 1 |
| `akshare.bond_zh_us_rate` | 1 |
| `akshare.stock_zh_index_daily` | 1 |
| `akshare.stock_zh_index_daily_em` | 1（失败，限流） |
| 官方 PDF HTTP 下载 | 1 |
| **合计** | **53** |

---

## 5. 报告生成（真实执行）

| 脚本 | 产物 |
| --- | --- |
| `scripts/audit_3b6_1_0_index_basis.py --probe` | 22 次调用 → `index_basis.json` |
| 历史覆盖探测 | 18 + 4 次调用 → `hist_full.json` |
| 报告生成脚本 | 6 对 MD + JSON |

---

## 6. 正式数据库只读验证

| 项 | 值 |
| --- | --- |
| 内容指纹（本轮前） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| 内容指纹（本轮后） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| **是否变化** | **✅ 未变** |
| ETF 指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

| 表 | 行数 | 与上轮对比 |
| --- | ---: | --- |
| `fund_master` | 120 | 未变 |
| `fund_share_classes` | 149 | 未变 |
| `fund_nav_daily` | 245,656 | 未变 |
| `fund_dividends` | 376 | 未变 |
| `fund_lifecycle_events` | 49 | 未变 |
| `fund_fee_rules` | 90 | 未变 |
| `index_master` | 10 | 未变 |
| `index_daily` | 50,603 | 未变 |
| `index_quality_checks` | 10 | 未变 |
| `benchmark_composite` | 15 | 未变 |
| `benchmark_composite_component` | 34 | 未变 |

**关键**：`index_daily` 仍为 **50,603** 行、`index_master` 仍 10 行、
`benchmark_composite` 仍 15 条、成分仍 34 条——**本轮未写入任何指数数据**。

---

## 7. 代码改动清单

| 文件 | 类型 |
| --- | --- |
| `scripts/audit_3b6_1_0_index_basis.py` | **新增**（只读审计脚本） |
| `tests/test_3b6_1_0_audit.py` | **新增**（17 项测试） |
| `reports/phase3B6_1_0_*.md/json` | **新增**（6 对） |
| `app/**` 业务代码 | **未改** |
| Schema / 迁移 | **未改** |
| 既有测试 | **未改** |

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
