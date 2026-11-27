# 阶段3B-6.2.3.1.0.1 测试报告

> **真实调用业务函数 + 真实读取证据文件 + 真实计算 SHA256。**

**基线 HEAD**：`3a85bd6dc12dbd73ad497d5af62337dc8e2245a2`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_0_1_fix.py`

---

## 2. 覆盖任务要求 18 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | H00016 合成起始行识别 | `test_h00016_synthetic_start_detected`、`test_h00016_contradiction_resolved` | ✅ |
| 2 | 2004-01-01 非交易日处理 | `test_20040101_not_in_a_calendar` | ✅ |
| 3 | 未确认真实起点时标记 unknown | `test_unknown_start_when_evidence_insufficient` | ✅ |
| 4 | 基日相同/不同的映射判定 | `test_base_date_match_true_when_equal`、`test_base_date_match_false_when_different`、`test_base_date_null_not_passed` | ✅ |
| 5 | 映射 JSON 基日字段不为 null | `test_mapping_base_date_never_null_in_json` | ✅ |
| 6 | 技术判断与官方映射区分 | `test_mapping_is_technical_not_official` | ✅ |
| 7 | 债券不用 A 股日历 | `test_bond_not_using_a_share_calendar` | ✅ |
| 8 | 港股不用 A 股日历 | `test_hk_not_using_a_share_calendar` | ✅ |
| 9 | 无日历时覆盖为 unknown | `test_no_calendar_means_coverage_unknown`、`test_unknown_not_interpreted_as_gap`、`test_unknown_not_interpreted_as_pass` | ✅ |
| 10 | 字符串 NaN 检查 | `test_string_nan_detected` | ✅ |
| 11 | 字符串 Infinity 检查 | `test_string_infinity_detected`、`test_float_nan_inf_detected` | ✅ |
| 12 | 非法/缺失日期检查 | `test_invalid_dates_detected`、`test_nan_does_not_bypass_quality` | ✅ |
| 13 | 三类状态分别计算 | `test_three_states_computed`、`test_state_rules_declared` | ✅ |
| 14 | JSON 与报告准入一致 | `test_json_and_report_admission_consistent`、`test_h20184_not_in_validated_list_in_report` | ✅ |
| 15 | 正式准入仍为 0 | `test_formal_admitted_still_zero` | ✅ |
| 16 | 全部证据 SHA256 复核 | `test_all_evidence_sha256_verified` | ✅ |
| 17 | manifest 与实际文件一致 | `test_manifest_matches_actual_files`、`test_old_evidence_unmodified` | ✅ |
| 18 | 数据库前后 SHA256 一致 | `test_db_sha256_unchanged`、`test_db_unchanged_flag` | ✅ |

---

## 3. 测试设计要点

### 3.1 真实调用业务函数

| 测试 | 调用的真实函数 |
| --- | --- |
| 合成行识别 | `detect_synthetic_start()` |
| 映射判定 | `build_mapping_evidence()` |
| 数值转换 | `to_number()` |
| 质量审计 | `audit_quality()` |
| 三类状态 | `compute_three_states()` |
| 日历分类 | `_classify_outside_calendar()` |

### 3.2 不使用恒真断言

`test_no_vacuous_assertion` 用字符串拼接检测，避免自伤。
编写过程中发现一处 `assert doc["candidates"] and True` 占位，
已改为真实断言。

### 3.3 负向测试必须存在

| 测试 | 验证的负向条件 |
| --- | --- |
| `test_base_date_match_false_when_different` | 基日不同 → 失败 |
| `test_base_date_null_not_passed` | 基日为 null → 失败 |
| `test_unknown_start_when_evidence_insufficient` | 证据不足 → unknown |
| `test_nan_does_not_bypass_quality` | 字符串 NaN → 质量不通过 |
| `test_h20184_raw_ok_but_not_validated` | 零值 → 不得评为质量通过 |

### 3.4 SHA256 真实计算

```python
actual = hashlib.sha256(f.read_bytes()).hexdigest()
assert actual == info["sha256"]
assert len(actual) == 64
```

**不得只检查字符串长度。**

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **46 passed / 0 failed / 0 skipped** |
| 全量测试 | 2695 → **2741**（**+46**） |

---

## 5. 关键测试证据

### 5.1 三类状态（真实输出）

```
{"raw_data_layer_ingest_candidate": 12, "validated_series_candidate": 8, "formal_series_admitted": 0}
```

### 5.2 自校验

```
{
 "three_groups_present": true,
 "no_bond_hk_using_a_calendar": true,
 "bond_hk_coverage_unknown": true,
 "no_formal_admitted": true,
 "mapping_base_date_never_null": true,
 "h20184_not_validated": true
}
```

### 5.3 原始证据完整性

```
{"checked": 44, "matched": 44, "mismatched": [], "all_match": true}
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 债券市场官方交易日历 | 未取得 |
| 2 | 港股官方交易日历 | 未取得 |
| 3 | 历史时点可用性 | 官方无历史快照 |
| 4 | `H20184` 零值真实值 | 官方该日仅返回 0.0 |
| 5 | 官方映射关系文件 | 未取得 |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

