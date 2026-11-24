# 阶段3B-6.1.0.1 测试报告

- 本轮基线 HEAD：`6b0dbafd1466c9def6f11b3c89fbe21122294dda`
- 执行时间：2026-11-24 16:23

> **严格区分**：真实执行 pytest / 静态检查 / 数据源调用。

---

## 0. 本轮修正的核心：测试可复现性

3B-6.1.0 有 **3 项测试依赖 `.tmp610/raw/`（本地临时缓存）**，
在干净检出时会跳过，**其他环境无法复核**。

### 0.1 修正前

```bash
$ pytest tests/test_3b6_1_0_audit.py -q
14 passed, 3 skipped
```

| 测试 | 跳过原因 |
| --- | --- |
| `test_all_10_indexes_probed` | 依赖 `.tmp610/raw/index_basis.json` |
| `test_total_return_variants_actually_returned_by_source` | 同上 |
| `test_price_and_total_are_different_series` | 同上 |

### 0.2 修正后

```bash
$ pytest tests/test_3b6_1_0_audit.py tests/test_3b6_1_0_1_audit_fix.py -q
43 passed in 0.58s
```

**0 skipped。** 3 项测试改为读取仓库内正式证据附件：

```
reports/evidence/phase3B6_1_0_index_probe_evidence.json
```

### 0.3 证据附件内容

| 项 | 内容 |
| --- | --- |
| 10 个指数 × 各自变体 | 每次调用的请求代码 / 区间 / 来源 / 状态 |
| 返回值 | 指数代码、指数中文全称、行数、首末日期 |
| 质量 | 重复日期数、空收盘数、非正收盘数 |
| 样例 | 前 3 条日期的收盘值（不含完整序列） |
| 同日对比 | 沪深300 价格 vs 全收益；上证国债三变体 |
| 官方文档 | 8 份编制方案 + 10 份 factsheet 的 URL/字节/sha256/页数 |
| 修正记录 | 3B-6.1.0 误判的成因与更正 |

**不含完整行情序列、不含密钥、不含个人信息。**

### 0.4 缓存移除验证

把 `.tmp610` 目录临时改名后复测：

```bash
$ mv .tmp610 .tmp610_bak
$ pytest tests/test_3b6_1_0_audit.py tests/test_3b6_1_0_1_audit_fix.py -q
43 passed in 0.58s
```

**确认不再依赖本地缓存。**

---

## 1. 新增专项测试（26 项）

```bash
$ pytest tests/test_3b6_1_0_1_audit_fix.py -q
26 passed in 0.76s
```

### 1.1 问题1：000012 语义分离（6 项）

| 测试 | 断言 |
| --- | --- |
| `test_000012_clean_price_is_not_net_total_return` | `H00012` 不得填入 `net_total_return_index_code` |
| `test_000012_net_return_semantically_separated` | 净价与净收益是两个不同 semantic |
| `test_000012_interest_and_reinvestment_code` | `N00012` 才是利息及再投资 |
| `test_000012_has_naming_convention_warning` | 必须有前缀惯例警告 |
| `test_000012_return_basis_still_unknown` | 修正不改 `return_basis` |
| `test_000012_field_mapping_matches_evidence` | 报告字段与证据附件一致 |

### 1.2 问题2：000051 固定收益率（7 项）

| 测试 | 断言 |
| --- | --- |
| `test_000051_fixed_rate_is_not_weight` | `weight=null`，`annual_rate=0.01` |
| `test_000051_no_stale_weight_component` | 旧 `fixed_rate_components` 已清空 |
| `test_000051_asset_weight_sum_is_0_95` | 资产权重合计 = **0.95**，不是 0.96 |
| `test_000051_period_conversion_method_unknown` | 折算方法未知时不得 reproducible |
| `test_fixed_rate_semantics_declared` | `annual_return_not_weight` |
| `test_other_composites_have_no_fixed_rate_confusion` | 其余 14 条无同类混淆 |

### 1.3 问题3：官方证据（6 项）

| 测试 | 断言 |
| --- | --- |
| `test_all_10_indexes_have_official_evidence` | 10/10 有证据记录 |
| `test_methodology_docs_actually_downloaded` | **8 份**方案真实下载（bytes>0, pages>=2, sha16 长度 16） |
| `test_missing_methodology_reported_honestly` | 缺的 2 份如实记录原因 |
| `test_search_log_is_traceable` | 搜索时间/URL/模式/关键词齐全 |
| `test_all_10_have_factsheet` | 10/10 factsheet |
| `test_no_basis_upgraded` | **无 return_basis 升级** |

### 1.4 问题4 + 门禁（7 项）

| 测试 | 断言 |
| --- | --- |
| `test_evidence_file_in_repo` | 证据附件在 `reports/evidence/` |
| `test_evidence_covers_all_10_indexes` | 覆盖 10 个 |
| `test_evidence_has_full_call_metadata` | 每个变体有完整元数据 |
| `test_evidence_price_and_total_are_different` | 价格≠全收益 |
| `test_no_local_cache_dependency` | 不依赖 `.tmp` |
| `test_gate_unchanged` | 门禁三值 |
| `test_no_index_written_to_db` / `test_no_composite_modified` | 只读 |

---

## 2. 全量 pytest（真实执行）

```bash
$ pytest -q
1945 passed, 1 warning in 752.80s (0:12:32)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1945** |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | **0** |
| 耗时 | 752.80 秒 |

**演进**：1919（3B-6.1.0）→ **1945**（+26 本轮新增，且原 3 项 skip 已消除）

### 2.1 测试数变化解析

| 变化 | 数量 |
| --- | ---: |
| 3B-6.1.0 | 1919（含 3 skip） |
| 本轮新增 `test_3b6_1_0_1_audit_fix.py` | **+26** |
| 原 3 项 skip 转为真实执行 | 0（本来也算在 1919 里） |
| **本轮** | **1945（0 skip）** |

---

## 3. 相关回归（真实执行）

```bash
$ pytest tests/test_3b6_1_0_audit.py -q
17 passed in 0.46s
```

```bash
$ pytest tests/test_3b6_0_4_1_lof_and_grade.py tests/test_3b6_0_4_peer_comparison.py \
        tests/test_3b6_0_4_share_cost_and_groups.py -q
88 passed
```

---

## 4. 静态检查（**不计入** 1945）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 脚本语法 | 静态 |
| JSON 合法性校验（7 个 JSON + 1 个证据附件） | 静态 |
| PDF 文本提取 | 静态解析 |

**不是测试。**

---

## 5. 数据源调用（真实执行，非测试）

| 接口 | 次数 | 用途 |
| --- | ---: | --- |
| `stock_zh_index_hist_csindex` | **30** | 证据附件重建 |
| `stock_zh_index_hist_csindex` | 4 | 验证 factsheet 披露的新代码 |
| 官方 PDF HTTP 下载 | **18** | 8 份方案 + 10 份 factsheet |
| **合计** | **52** | |

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

## 7. 代码与文件改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `scripts/build_3b6_1_0_1_evidence.py` | **新增** | 证据附件生成脚本 |
| `reports/evidence/phase3B6_1_0_index_probe_evidence.json` | **新增** | 仓库级证据附件 |
| `tests/test_3b6_1_0_1_audit_fix.py` | **新增** | 26 项专项测试 |
| `tests/test_3b6_1_0_audit.py` | **修改** | 3 项缓存依赖 → 仓库证据 |
| `reports/phase3B6_1_0_*.md/json` | **修改** | 6 对报告语义修正 |
| `app/**` 业务代码 | **未改** | — |
| Schema / 迁移 | **未改** | — |

**既有测试：0 删除、0 跳过、0 弱化。**
唯一修改是把 3 项 skip 改成真实执行——**加强而非削弱**。

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
