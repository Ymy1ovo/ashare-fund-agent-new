# 阶段3B-6.0.1 测试报告

- 基线 HEAD：`c34d867b95db71cd82e16edfb4bbdaeaa530e594`
- 执行日期：2026-11-23
- Python 3.11.2 / pytest / SQLite

> 以下全部为**实际执行**结果。静态检查单独标注，不冒充测试通过。

---

## 1. 新增专项测试

```bash
$ pytest tests/test_3b6_0_1_benchmark_audit.py -q
33 passed in 8.81s
```

| 覆盖项（任务书第四 / 七节） | 用例数 |
| --- | ---: |
| 四类证据严格区分 | 5 |
| 基准解析（单指数/复合/债券/现金/权重/未识别） | 9 |
| 指数代码映射与 unknown 不猜 | 5 |
| 全量审计（含清盘、份额数、A/C 归并） | 5 |
| unknown 不被提升 / 复合不退化 | 2 |
| 状态取值合法 / 汇总自洽 | 3 |
| 货币基金隔离 | 1 |
| 只读守恒 + 指纹一致 + 无 Schema 变更 | 2 |
| 门禁不变 | 1 |

### 1.1 关键断言

| 断言 | 说明 |
| --- | --- |
| `test_audit_covers_all_funds` | `scanned_fund_count == len(rows)`，证明**全量**不是抽样 |
| `test_audit_includes_terminated` | 41 个清盘本体全部在扫描范围内 |
| `test_composite_not_reduced_to_single_index` | 复合基准 `single_index_family is None` |
| `test_unknown_index_not_resolved` | 未知族 `index_code is None`，不猜 |
| `test_bond_families_have_no_code` | 全部中债族无代码 |
| `test_external_catalog_marked_partial` | 恒生走新浪，标 `external_partial` + `partial` |
| `test_audit_unknown_never_promoted` | 无基准的基金绝不被提升为可验证基准 |
| `test_audit_ac_shares_grouped` | fund_id 唯一，A/C 归并 |
| `test_database_untouched_and_fingerprint_same` | 指纹 bytes 完全一致 |
| `test_no_schema_change` | 未新增任何表 |

---

## 2. 回归测试

### 2.1 3B-5.5 系列（质量分级 + 同类/年化修正）

```bash
$ pytest tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
112 passed
```

### 2.2 合并（3B-6.0.1 + 3B-5.5 全部）

```bash
$ pytest tests/test_3b6_0_1_benchmark_audit.py \
        tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
145 passed in 160.71s (0:02:40)
```

---

## 3. 全量测试

```bash
$ pytest -q
1662 passed, 1 warning in 549.38s (0:09:09)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1662** |
| 失败 | **0** |
| 错误 | **0** |
| 耗时 | **549.38 秒** |

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-5.5 | 1577 |
| 3B-5.5.1 | 1629 |
| **3B-6.0.1** | **1662** |

1629 + 33 = 1662。

---

## 4. 数据源审计的实跑记录

```bash
$ python scripts/audit_3b6_0_1_index_sources.py --json .tmp601/sources.json
```

结果摘要（详见 `phase3B6_0_1_index_data_source_audit.md`）：

| 数据源 | 结果 |
| --- | --- |
| 中证官网（6 个指数） | ✅ 全部可取，含 OHLC |
| 新浪（3 个） | ✅ 可取 |
| 中债新综合 | ✅ 6223 行，仅收盘值 |
| 国证申万 | ✅ 6496 行 |
| 东方财富 | ❌ `Push2RateLimitError` |
| 中美国债收益率 | ✅ 4503 行，2/5/10/30 年 |
| 中债曲线 | ✅ 多期限 |
| Shibor | ✅ 2405 行 |

---

## 5. 正式数据库只读验证

| 检查 | 结果 |
| --- | --- |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0 违规** |
| `fund_master` | 60 |
| 清盘本体 | 41 |
| 生命周期事件 | 49 |
| 内容指纹 | `11c56eba1489976fa35be92586a99bc21a27e20c06e95cacab5c8ca553c05116` |
| ETF 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

**与 3B-5.5.1 完全一致，本轮零写入。**

---

## 6. 测试环境说明

| 项 | 说明 |
| --- | --- |
| 单元测试 | **完全不联网**（数据源连通性由脚本单独实跑） |
| 正式库 | **只读** |
| 正式库写入 | **零**（有守恒测试 + 指纹断言） |
| 数据采集 | **零** |

---

## 7. 静态检查（不计入测试通过）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | **静态** |
| 报告数据与库查询比对 | **静态核对** |

**不计入 1662**。

---

## 8. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/research/benchmark_audit.py` | **新增** | 基准解析 + 四类证据判定 + 全量审计 |
| `scripts/audit_3b6_0_1_index_sources.py` | **新增** | 数据源连通性实跑脚本 |
| `tests/test_3b6_0_1_benchmark_audit.py` | **新增** | 33 项专项测试 |
| `app/fund/research/engine.py` | **未改** | — |
| `app/fund/research/indicators.py` | **未改** | — |
| `app/fund/research/classification.py` | **未改** | — |
| `app/fund/research/quality.py` | **未改** | 3B-5.5 评级逻辑不变 |
| Schema / 迁移 | **未改** | — |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
