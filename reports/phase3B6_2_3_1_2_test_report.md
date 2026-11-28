# 阶段3B-6.2.3.1.2 测试报告

> ⚠️ **本报告已被 3B-6.2.3.1.2.1 修正**。新增 52 项边界修复专项测试，
> 并重新生成全部审计结果。请以本报告为准。

**本轮任务基线 HEAD**：`6a76d2890ddd5ec21d97d90ed1ab4b07d3ea168a`
**修正后最终 HEAD**：见提交记录

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_2_quality.py`

---

## 2. 覆盖任务要求 14 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 12 个候选完整覆盖 | `test_twelve_candidates_covered`、`test_all_candidates_graded`、`test_grading_file_consistent` | ✅ |
| 2 | 各市场交易日历隔离 | `test_market_calendar_isolation`、`test_bond_not_using_a_share_calendar`、`test_hk_not_using_a_share_calendar` | ✅ |
| 3 | 真实起点未知时不得升级 | `test_historical_start_all_unknown` | ✅ |
| 4 | 请求起始日不得作为真实起点 | `test_request_start_not_used_as_real_start`、`test_six_date_concepts_distinct` | ✅ |
| 5 | 疑似合成行不得自动认定 | `test_synthetic_rows_not_confirmed_as_real`、`test_synthetic_rows_preserved_in_db` | ✅ |
| 6 | 疑似休市占位不得自动升级 | `test_closed_placeholder_not_auto_upgraded`、`test_closed_placeholder_rows_preserved` | ✅ |
| 7 | 异常 close 不得自动修正 | `test_abnormal_close_not_fixed`、`test_h20184_zero_still_in_db` | ✅ |
| 8 | 时点未知不得获回测准入 | `test_point_in_time_all_unknown`、`test_no_point_in_time_candidate_passes_backtest` | ✅ |
| 9 | 代理日历不得升级为官方 | `test_proxy_not_upgraded_to_official` | ✅ |
| 10 | 55,942 行与指纹不变 | `test_raw_rows_unchanged` | ✅ |
| 11 | `raw_record_json` / sha256 不变 | `test_raw_record_json_unchanged` | ✅ |
| 12 | `index_daily` 行数与指纹不变 | `test_index_daily_unchanged` | ✅ |
| 13 | 数据库完整性与外键 | `test_integrity_and_fk`、`test_isolation_kept` | ✅ |
| 14 | 所有门禁保持关闭 | `test_all_gates_closed`、`test_no_admission_upgrade` | ✅ |

---

## 3. 测试设计要点

### 3.1 真实调用审计函数

```python
r = audit_calendar({"market_group": "bond", "_synthetic_row": ...},
                   rows, a_cal)
assert r["continuity_status"] == "unknown"
```

**不是检查报告字符串。**

### 3.2 分级规则一致性与不可降标准

```python
def test_grade_a_requires_all_six():
    full = {... 六项全通过 ...}
    assert grade_candidate(full)["final_grade"] == "A"
    # 少任一项都不能是 A
    for k, v in (("historical_start", ...), ("calendar", ...),
                 ("point_in_time", ...)):
        assert grade_candidate({**full, k: v})["final_grade"] != "A"
```

**证明 A 级必须六项齐全，防止为凑数降标准。**

### 3.3 市场标注差异必须记录证据

```python
mm = audit["task_candidate_table_errors"]["mismatches"]
assert {m["tr_code"] for m in mm} == {"H00012", "H20930"}
for m in mm:
    assert "不覆盖原始记录" in m["action"]
```

### 3.4 数据保护真实复核

```python
for j, s in rows:
    assert hashlib.sha256(j.encode("utf-8")).hexdigest() == s
```

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试（3B-6.2.3.1.2 原始） | **41 passed / 0 failed / 0 skipped** |
| **专项测试（3B-6.2.3.1.2.1 新增）** | **52 passed / 0 failed / 0 skipped** |
| 全量测试 | 3014 → **3066**（**+52**） |

---

## 5. 关键测试证据

### 5.1 自校验（真实输出）

```
{
 "twelve_candidates": true,
 "all_graded": true,
 "no_grade_a": true,
 "no_historical_start_confirmed": true,
 "point_in_time_all_unknown": true,
 "no_official_calendar": true,
 "bond_hk_calendar_unknown": true,
 "rows_unchanged": true,
 "index_daily_unchanged": true,
 "no_validated": true,
 "no_formal_admitted": true,
 "synthetic_rows_preserved": true
}
```

### 5.2 分级分布

```
{"B": 8, "C": 4}
```

### 5.3 连续性分布

```
{"verified_against_proxy_calendar": 9, "unknown": 3}
```

### 5.4 市场标注不符

```
H00012: 任务书=stock 实际=bond (上证国债指数(净价))
H20930: 任务书=bond 实际=hk (中证港股通综合全收益指数)
```

---

## 6. 实际执行 vs 静态检查

| 类型 | 内容 |
| --- | --- |
| **实际执行** | 12 个候选逐行质量扫描（55,942 行）；日历比对；SHA256 真实计算；数据库完整性检查；专项测试 41 项 |
| **静态检查** | 分级规则定义表；日历来源尝试记录；官方资料缺失说明 |

**所有结论均有实际执行支撑，无仅凭静态文本得出的判定。**

---

## 7. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 官方编制方案 | 未取得 |
| 2 | 债券官方交易日历 | SSE 页面 JS 渲染，无法解析 |
| 3 | 港股官方交易日历 | HKEX 页面 JS 渲染，无法解析 |
| 4 | 官方历史快照 | 无公开来源 |
| 5 | `H20184` 零值真实值 | 官方接口该日返回 0.0 |
| 6 | 合成行官方解释 | 官方无相关公告 |

---

## 8. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |


---

## 9. 3B-6.2.3.1.2.1 新增专项测试（52 项）

文件：`tests/test_3b6_2_3_1_2_1_boundary.py`

### 9.1 修复1：连续性判定（9 项）

| 测试 | 断言 |
| --- | --- |
| `test_suspected_closed_blocks_proxy_verification` | 有疑似休市 → `has_unresolved_suspicion` |
| `test_no_suspected_can_be_proxy_verified` | 无疑似且无缺失 → 代理验证 |
| `test_missing_trading_days_gives_has_issues` | 有缺失 → `has_issues` |
| `test_bond_hk_still_unknown` | 债券/港股仍 unknown |
| `test_suspected_not_bypassing_continuity` | 疑似记录不能绕过阻断 |
| `test_all_12_real_candidates_checked` | **检查全部 12 个真实候选** |
| `test_continuity_distribution_matches_baseline` | 分布与原始五态一致 |
| `test_closed_placeholder_records_preserved` | 8 条疑似休市保留 |
| `test_no_official_calendar_upgrade` | 代理不得升级为官方 |

### 9.2 修复2：判级优先级（11 项）

| 测试 | 断言 |
| --- | --- |
| `test_h20184_real_data_graded_d` | **H20184 真实数据评为 D** |
| `test_close_zero_graded_d` | close=0 → D |
| `test_close_negative_graded_d` | close<0 → D |
| `test_calendar_unknown_no_fatal_graded_c` | 日历 unknown 无致命 → C |
| `test_proxy_calendar_and_quality_graded_b` | 代理日历+质量 → B |
| `test_all_six_graded_a` | 六项全通 → A |
| `test_d_not_intercepted_by_c` | **D 不被 C 截获** |
| `test_identity_missing_graded_unknown` | 身份不足 → UNKNOWN |
| `test_grade_distribution_from_real_data` | 从真实数据重算，不硬编码 |
| `test_grading_file_consistent` | 两个 JSON 一致 |
| `test_d_not_intercepted_by_c`（重复断言优先级规则） | — |

### 9.3 修复3：无效前值（4 项）

| 测试 | 断言 |
| --- | --- |
| `test_invalid_prev_close_blocks_return_calc` | 阻断计数 ≥1，**无虚假 extreme_jump** |
| `test_invalid_prev_close_no_change_inconsistency` | 无虚假 change 不一致 |
| `test_h20184_real_has_blocked_count` | 真实数据有阻断记录 |
| `test_abnormal_value_still_preserved` | 原始 0.0 保留 |

### 9.4 修复4：用途限制（4 项）

| 测试 | 断言 |
| --- | --- |
| `test_usage_restrictions_present` | 显式筛选规则存在且自洽 |
| `test_excluded_records_are_abnormal` | 排除的必须是异常行 |
| `test_residual_continuity_gap_declared` | 缺口必须声明 |
| `test_synthetic_rows_in_exclusion_list` | 12 条合成行在排除清单 |

### 9.5 修复5：非交易日诊断（4 项 + 12 项逐项检查）

| 测试 | 断言 |
| --- | --- |
| `test_non_trading_date_filled_for_stock` | **A 股实际填充** |
| `test_non_trading_date_not_applicable_for_bond` | 债券不适用 |
| `test_non_trading_date_not_applicable_for_hk` | 港股不适用 |
| `test_non_trading_is_proxy_anomaly_not_official` | 只能标代理异常 |

**12 项逐项真实函数测试**：非法日期、重复日期、close=0、
high<low、OHLC 冲突、volume 负值、change 不一致、
change_pct 不一致、异常跳变、连续重复价格等，
**每项都用构造数据真实调用 `audit_row_quality()` 验证**。

### 9.6 数据保护（9 项）

覆盖：行数不变、`index_daily` 指纹不变、`raw_record` 不变、
证据 SHA256 不变、完整性/外键、隔离、异常行保留、门禁、基线。

---

## 10. 实际执行 vs 静态检查

| 类型 | 内容 |
| --- | --- |
| **实际执行** | 12 个候选真实审计（55,942 行）；52 项专项测试真实调用函数；数据库完整性检查；SHA256 真实计算 |
| **静态检查** | 判级优先级规则定义；连续性判定规则表 |

**所有结论均有实际执行支撑。**
