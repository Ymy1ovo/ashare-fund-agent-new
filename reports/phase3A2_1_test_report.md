# 阶段3A.2.1 测试报告

- 执行时间：2026-11-11
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 执行方式：DSH 在当前工作区实际运行，非静态推断

## 一、全量测试结果（DSH 实际执行）

```powershell
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

| 项目 | 数值 |
| --- | ---: |
| 测试总数 | **249** |
| 通过 | **249** |
| 失败 | **0** |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 23.85s |

### 数量构成

| 来源 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过，无回退 |
| 阶段3A.2（`test_validation.py`） | 55 | 全部通过，无删减 |
| 阶段3A.2.1（`test_validation_fix.py`） | 40 | 全部通过 |
| **合计** | **249** | **全部通过** |

未删除任何原有测试，未降低任何断言标准。

## 二、阶段3A.2.1 新增测试清单（40 项）

### 任务1：市场环境预热（9 项）

| 测试 | 验证内容 | 结果 |
| --- | --- | --- |
| `test_regime_warmup_enables_ma250_on_first_oos_day` | OOS 首日可靠 250 个预热交易日完成 MA250 | 通过 |
| `test_regime_without_warmup_cannot_classify` | 无预热且不足 250 天时抛错，不硬编 | 通过 |
| `test_regime_warmup_does_not_enter_output` | 预热日不进入输出 labels | 通过 |
| `test_regime_future_data_does_not_change_past_labels` | 改未来价格不影响历史分类 | 通过 |
| `test_regime_insufficient_warmup_marks_partial` | 预热不足时前段保持 unclassified | 通过 |
| `test_regime_alignment_uses_trading_days_not_calendar_days` | 按交易日对齐，不用自然日 | 通过 |
| `test_regime_output_dates_match_oos_one_to_one` | OOS 日期与结果一一对应 | 通过 |
| `test_regime_summary_reports_warmup_and_range` | 摘要含预热天数与输出范围 | 通过 |
| `test_regime_empty_series_still_raises` | 空序列报错 | 通过 |

### 任务2：数据指纹（15 项）

| 测试 | 验证内容 | 结果 |
| --- | --- | --- |
| `test_fingerprint_version_and_fields_declared` | 算法有版本号与字段清单 | 通过 |
| `test_fingerprint_is_reproducible` | 重复计算一致 | 通过 |
| `test_fingerprint_row_order_independent` | 行顺序变化指纹不变 | 通过 |
| `test_fingerprint_detects_each_price_field` | open/high/low/close/volume/adjusted_close 各自变化均被识别 | 通过 |
| `test_fingerprint_detects_date_and_symbol_change` | trade_date / code 变化被识别 | 通过 |
| `test_fingerprint_detects_snapshot_change` | adjustment_snapshot_id 变化被识别 | 通过 |
| `test_fingerprint_null_encoding_stable` | None 与 NaN 编码一致 | 通过 |
| `test_fingerprint_float_precision_normalized` | 1.1 与 1.100000 视为同值 | 通过 |
| `test_fingerprint_rejects_wrong_field_count` | 字段数不匹配报错 | 通过 |
| `test_fingerprint_compare_reports_diff` | 内容变化被正确报告 | 通过 |
| `test_fingerprint_compare_detects_row_count_change` | 行数变化被正确报告 | 通过 |
| `test_fingerprint_normalize_rows_sorts_by_code_and_date` | 排序规则正确 | 通过 |
| `test_input_hash_changes_with_fingerprint` | 指纹变化传导到 input_hash | 通过 |
| `test_fingerprint_db_readonly_does_not_change_data` | 读指纹不修改数据 | 通过 |
| `test_fingerprint_detects_db_change` | 数据库字段变化被识别 | 通过 |

### 任务3：数据压力测试（8 项）

| 测试 | 验证内容 | 结果 |
| --- | --- | --- |
| `test_sparse_copy_does_not_modify_source` | 副本生成后源库行数不变 | 通过 |
| `test_sparse_copy_actually_removes_rows` | 副本确实删除了行情行 | 通过 |
| `test_sparse_evaluation_flags_bad_counts` | 计数异常被判失败 | 通过 |
| `test_insufficient_evaluation_requires_low_sample` | 区间过长不算数据不足 | 通过 |
| `test_insufficient_evaluation_rejects_metrics_when_short` | 未隐藏指标时判失败 | 通过 |
| `test_insufficient_evaluation_accepts_withheld_metrics` | 指标已隐藏时判定成立 | 通过 |
| `test_sparse_and_insufficient_are_not_skipped_in_scenario_set` | 两个场景在默认集中且为 data 类型 | 通过 |
| `test_stress_assert_no_data_mutation_still_works` | 数据变更检测生效 | 通过 |

### 任务4：缺失日收益（6 项）

| 测试 | 验证内容 | 结果 |
| --- | --- | --- |
| `test_regime_stats_keeps_nan_and_counts_missing` | NaN 保留并被计数 | 通过 |
| `test_regime_stats_does_not_compress_cross_gap_return` | 跨缺口收益不当单日收益 | 通过 |
| `test_regime_stats_missing_label_not_counted_as_other_regime` | 无分类日进 unclassified | 通过 |
| `test_regime_stats_insufficient_returns_clear_status` | 观测不足返回明确状态 | 通过 |
| `test_regime_stats_accepts_dict_and_series_equally` | 两种输入口径一致 | 通过 |
| `test_regime_stats_cumulative_return_excludes_missing` | 累计收益只按有效日复利 | 通过 |

### 配置与隔离（2 项）

| 测试 | 结果 |
| --- | --- |
| `test_validation_config_declares_regime_ma_window` | 通过 |
| `test_validation_config_rejects_bad_regime_window` | 通过 |

## 三、实际运行验证（DSH 实际执行）

### 3.1 代表性池验证

```
python scripts\run_validation.py
```

| 项目 | 结果 |
| --- | --- |
| validation_id | `f07b281c296841a4` |
| 状态 | success |
| ETF 数 | 6 |
| 结论 | 不通过 |
| 市场环境预热 | 3,064 个交易日，状态 ok |
| OOS unclassified 天数 | **0**（整改前 246） |
| 分类 | bull 324 / range 97 / bear 26 |
| OOS 有效日收益 | 446 / 447 |
| sparse_data 场景 | **success**（整改前 skipped） |
| insufficient 场景 | **insufficient**（整改前 skipped） |
| 数据指纹前后 | 一致（`394024221c09d310...`，116,609 行） |

### 3.2 全池验证

见 `reports/phase3A2_1_validation_report.md` 第 6 节。

### 3.3 数据类压力场景实测明细

| 场景 | 状态 | 实测数据 |
| --- | --- | --- |
| `sparse_data` | success | 副本删除零散 4,047 行 + 连续缺失 32 行；剩 112,438 行；447 天快照中 270 天有效日收益、176 天缺口、1 天 NaN |
| `insufficient` | insufficient | 区间 41 个交易日 < 需求 120；引擎算出的 Sharpe 4.0184 / CAGR 78.44% 已隐藏；`metrics={}` |

### 3.4 API 与看板

| 检查 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/{id}` | 200 |
| `GET /api/validations/not_exist` | 404（期望） |
| Streamlit 验证页 AppTest | 0 异常 |

## 四、数据库检查（DSH 实际执行）

| 项目 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | ok |
| 行情行数 | 116,609（整改前后一致） |
| 指标行数 | 350,292（未变） |
| 复权快照 | 139（未变） |
| 历史回测 run | 11（未变） |
| 历史 validation 记录 | 全部保留（含 failed 与 success） |
| 行情指纹 v2 | `394024221c09d310f520e3e39cdd83faca944b7f5f89e3eec0a2c0835b92084a` |

## 五、静态代码检查（非运行测试）

以下项目通过阅读代码确认，未单独构造运行用例：

- `_load_regime_warmup()` 使用 `trade_date < oos_start` 条件，逻辑上不会读到 OOS 之后的数据。
- `build_sparse_copy()` 使用 `sqlite3.backup()`，不执行任何写源库的 SQL。
- `evaluate_insufficient_result()` 在 `metrics_withheld=True` 时对外返回 `None`。
- 报告生成中广义异常均被 `except Exception` 捕获并写入 `reason`，不会静默吞掉。

## 六、尚未验证的事项

1. **未构造「预热不足 250 天」的真实数据场景**：单测用人工序列覆盖，真实库中 510300 有 3,064 天预热，不会触发 partial 分支。
2. **未测试并发运行两个验证任务**。
3. **`sparse_data` 的删除比例未做敏感性扫描**（当前固定每 5 天删 1 天 + 2 只连续缺 20 天）。
4. **全池 MA5 组合仍因引擎现金精度边界失败**，本阶段按约束未修改 `app/backtest/`。
5. **未验证 data-snapshot 包在另一台机器的可恢复性**。

## 七、结论

| 项目 | 结果 |
| --- | --- |
| 原有 154 项 | 全部通过 |
| 阶段3A.2 的 55 项 | 全部通过 |
| 新增 40 项 | 全部通过 |
| 全量 249 项 | 全部通过 |
| 市场环境预热 | 实测生效，unclassified 从 246 → 0 |
| 数据指纹 | 实测生效，10 个字段全覆盖 |
| sparse_data | 实际执行并通过 |
| insufficient | 实际执行并正确识别 |
| 真实行情隔离 | 指纹前后一致 |
