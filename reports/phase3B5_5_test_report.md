# 阶段3B-5.5 测试报告

- 基线 HEAD：`8c42dec82bcb35393193b70ab033dbda41a6c143`
- 执行日期：2026-11-23
- Python 3.11.2 / pytest / SQLite

> 以下全部为**实际执行**结果。静态检查单独标注，不冒充测试通过。

---

## 1. 新增专项测试

```bash
$ pytest tests/test_3b5_5_quality_framework.py -q
60 passed in 72.06s (0:01:12)
```

| 覆盖项（任务书第九节） | 用例数 | 对应用例 |
| --- | ---: | --- |
| 1. A/B/C/D 四级 | 6 | `test_grade_a_clean_long_history` 等 |
| 2. 收益好坏与数据质量独立 | 2 | `test_return_level_independent_from_quality` / `test_fund_grade_states_not_returns` |
| 3. 缺口导致指标降级 | 3 | `test_gap_degrades_annualized` / `..._volatility` / `test_daily_volatility_reads_daily_vol_not_value` |
| 4. 最大回撤不完整覆盖标记 | 3 | `test_max_drawdown_degraded_marked` 等 |
| 5. Sharpe 缺利率拒绝 | 2 | `test_sharpe_rejected_without_riskfree` / `test_sharpe_never_zero_filled` |
| 6. 缺基准拒绝超额收益 | 2 | `test_excess_return_rejected_without_benchmark` / `test_excess_return_not_zero` |
| 7. 同类样本不足拒绝比较 | 6 | `test_peer_insufficient_sample` 等 |
| 8. A/C 费率不完整拒绝推荐 | 4 | `test_share_cost_insufficient_evidence` 等 |
| 9. 货币独立分组与口径 | 3 | `test_money_indicators_not_applicable` 等 |
| 10. 不同产品类型分级 | 3 | `test_grades_differ_by_product_type` 等 |
| 11. 报告字段完整性 | 3 × 6 参数 | `test_real_report_has_all_sections` 等 |
| 12. JSON 与 Markdown 一致 | 3 | `test_markdown_matches_json` 等 |
| 附加：只读守恒 | 2 | `test_production_untouched_by_readonly` / `test_source_grade_third_party` |

---

## 2. 回归测试

### 2.1 3B-5.1 / 3B-5.2 研究引擎

```bash
$ pytest tests/test_3b5_1_fund_research.py tests/test_3b5_2_code_lookup.py -q
135 passed in 63.13s (0:01:03)
```

### 2.2 3B-5.3 系列接入 + 3B-5.4 多类型

```bash
$ pytest tests/test_3b5_3_2_fk_serialization.py \
        tests/test_3b5_3_1_atomic.py \
        tests/test_3b5_3_user_ingest.py \
        tests/test_3b5_4_multi_type.py -q
99 passed in 95.36s (0:01:35)
```

---

## 3. 全量测试

```bash
$ pytest -q
1577 passed, 1 warning in 520.63s (0:08:40)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1577** |
| 失败 | **0** |
| 错误 | **0** |
| 耗时 | **520.63 秒** |

### 3.1 数量演进

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-5.3.2 | 1482 |
| 3B-5.4 | 1517 |
| **3B-5.5** | **1577** |

1517 + 60 = 1577，增量与新增用例数一致。

---

## 4. 真实研究报告实际生成记录

```bash
$ python -m app.fund.research --code 050002
# 等价脚本调用 build_practical_report('050002')
```

| 代码 | 类型 | 数据质量 | 可算 | 不适用 | 算不出 |
| --- | --- | --- | ---: | ---: | ---: |
| `050002` | 普通指数基金 | **B** | 7 | 1 | 5 |
| `001052` | ETF联接基金 | **B** | 9 | 1 | 3 |
| `001938` | 主动权益基金 | **B** | 10 | 1 | 2 |
| `000032` | 债券基金 | **B** | 10 | 0 | 3 |
| `000509` | 货币基金 | **B** | 1 | 12 | 0 |
| `001548` | ETF联接 A/C 组（A 类） | **B** | 9 | 0 | 4 |
| `001549` | ETF联接 A/C 组（C 类） | **B** | 9 | 0 | 4 |

全部来自正式库真实数据，**未使用模拟数据**。

---

## 5. 测试环境说明

| 项 | 说明 |
| --- | --- |
| 需要临时库的用例 | 自建 `ensure_fund_schema` + `ensure_3b4_2_schema` + `ensure_3b4_4_schema` |
| 需要正式库的用例 | **只读**（`build_practical_report` 不写库） |
| 网络 | 单元测试**完全不联网** |
| 故障注入 | 全部在临时库 |
| 正式库写入 | **零**（有守恒测试断言行数不变） |

---

## 6. 静态检查（不计入测试通过）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | **静态** |
| 报告数据与库查询比对 | **静态核对** |

**不计入 1577**。

---

## 7. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/research/quality.py` | **新增** | 质量分级与指标评级（只读） |
| `app/fund/research/practical_report.py` | **新增** | 12 节报告组装 + Markdown 渲染（只读） |
| `tests/test_3b5_5_quality_framework.py` | **新增** | 60 项专项测试 |
| `app/fund/research/engine.py` | **未改** | 计算逻辑零改动 |
| `app/fund/research/indicators.py` | **未改** | 计算逻辑零改动 |
| `app/fund/research/classification.py` | **未改** | 分组逻辑零改动 |
| Schema / 迁移 | **未改** | — |

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
