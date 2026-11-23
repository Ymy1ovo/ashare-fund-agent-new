# 阶段3B-6.0.1.1 测试报告

- 基线 HEAD：`3c2185a2f3d223d281ab1fd12e4d2b8175c6305c`
- 执行日期：2026-11-23
- 修正轮：3B-6.0.1.1（指数验证范围 + 中债覆盖结论修正）

> 以下全部为**实际执行**结果。静态检查单独标注，不冒充测试通过。

---

## 1. 本轮新增专项测试

```bash
$ pytest tests/test_3b6_0_1_1_index_verify.py -q
28 passed in 9.94s
```

| 覆盖项（任务书第五节） | 用例数 |
| --- | ---: |
| 1. 未执行历史调用不能标 `history_api_verified` | 2 |
| 2. 代码映射成功 ≠ 历史质量通过 | 3 |
| 3. 日期重复必须被发现 | 1 |
| 4. 日期倒序必须被发现 | 1 |
| 5. OHLC 空值必须被发现（且只算警告） | 2 |
| 6. 收盘值空值必须被发现 | 2 |
| 7. 缺口保留不确定性标记 | 3 |
| 8. 复合基准不能因一个成分可用就宣称可复现 | 2 |
| 9. 中债短窗口不能推断长期覆盖 | 2 |
| 10. 正式数据库只读 | 2 |
| 附加：基线行探测 / 状态定义 / 门禁 | 8 |

### 1.1 关键断言

| 断言 | 说明 |
| --- | --- |
| `test_mapping_does_not_imply_history_verified` | 接口失败时三个状态全 false |
| `test_api_verified_but_quality_failed` | 有重复日期 → 停在 `history_api_verified` |
| `test_all_pass_reaches_quality_verified` | 全通过才到 `history_quality_verified` |
| `test_duplicate_dates_detected` | 重复 1 条即被发现 |
| `test_out_of_order_detected` | 倒序被发现 |
| `test_null_close_detected` | 收盘空值 → 硬性失败 |
| `test_null_ohlc_is_warning_not_blocking` | OHLC 空值只警告 |
| `test_gap_keeps_uncertainty_marker` | `is_real_missing is None` |
| `test_gap_never_filled` | 行数不变，不填充 |
| `test_baseline_row_detected_by_non_trading_day` | 元旦首行也判基线 |
| `test_composite_not_reproducible_from_one_component` | 复合不给 `index_only` |
| `test_index_verified_does_not_imply_benchmark_reproducible` | 当前 0 只可复现 |
| `test_short_window_does_not_imply_long_coverage` | `history_coverage_verified=false` |
| `test_production_db_readonly_untouched` | 指纹完全一致 |

---

## 2. 3B-6.0.1 原有专项回归

```bash
$ pytest tests/test_3b6_0_1_1_index_verify.py \
        tests/test_3b6_0_1_benchmark_audit.py -q
61 passed in 18.16s
```

| 文件 | 用例数 |
| --- | ---: |
| `test_3b6_0_1_benchmark_audit.py`（原有） | 33 |
| `test_3b6_0_1_1_index_verify.py`（本轮新增） | 28 |

**原有 33 项全部保留且通过，未删除、未弱化任何断言。**

---

## 3. 3B-5.5 系列回归

```bash
$ pytest tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
112 passed in 109.81s (0:01:49)
```

---

## 4. 全量测试

```bash
$ pytest -q
1690 passed, 1 warning in 590.78s (0:09:50)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1690** |
| 失败 | **0** |
| 错误 | **0** |
| 耗时 | **590.78 秒** |

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-5.5.1 | 1629 |
| 3B-6.0.1 | 1662 |
| **3B-6.0.1.1** | **1690** |

1662 + 28 = 1690。

---

## 5. 数据源审计实跑记录

本轮跑了三个脚本，全部真实调用：

```bash
$ python scripts/audit_3b6_0_1_index_sources.py --json ...
$ python scripts/audit_3b6_0_1_1_index_verify.py --json ...
$ python scripts/audit_3b6_0_1_1_bond_coverage.py --json ...
```

| 脚本 | 用途 |
| --- | --- |
| `audit_3b6_0_1_index_sources.py` | 基础连通性（原有） |
| `audit_3b6_0_1_1_index_verify.py` | **逐指数**三步验证（本轮新增） |
| `audit_3b6_0_1_1_bond_coverage.py` | 中债分段覆盖验证（本轮新增） |

---

## 6. 正式数据库只读验证

| 检查 | 结果 |
| --- | --- |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0 违规** |
| `fund_master` | 60 |
| 清盘本体 | 41 |
| 生命周期事件 | 49 |
| 内容指纹 | `11c56eba1489976fa35be92586a99bc21a27e20c06e95cacab5c8ca553c05116` |
| ETF 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

**与 3B-6.0.1 完全一致，本轮零写入。**

---

## 7. 测试环境说明

| 项 | 说明 |
| --- | --- |
| 单元测试 | **完全不联网**（DataFrame 用 pandas 构造） |
| 数据源验证 | 由脚本单独实跑 |
| 正式库 | **只读** |
| 正式库写入 | **零** |
| 数据采集 | **零** |

---

## 8. 静态检查（不计入测试通过）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | **静态** |
| 报告数据与实跑结果比对 | **静态核对** |

**不计入 1690**。

---

## 9. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/research/index_verify.py` | **新增** | 三层状态验证 + 质量检查 + 基线行探测 |
| `scripts/audit_3b6_0_1_1_index_verify.py` | **新增** | 逐指数实调脚本 |
| `scripts/audit_3b6_0_1_1_bond_coverage.py` | **新增** | 中债分段覆盖脚本 |
| `tests/test_3b6_0_1_1_index_verify.py` | **新增** | 28 项专项测试 |
| `app/fund/research/benchmark_audit.py` | **未改** | — |
| `app/fund/research/engine.py` / `indicators.py` | **未改** | — |
| `app/fund/research/quality.py` | **未改** | 评级逻辑不变 |
| Schema / 迁移 | **未改** | — |

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
