# 阶段3B-6.2.3.1.2 测试报告

> **真实操作数据库、真实调用审计函数、真实计算 SHA256。**

**本轮任务基线 HEAD**：`6a76d2890ddd5ec21d97d90ed1ab4b07d3ea168a`
**本轮最终 HEAD**：见提交记录（**与基线不同，不得混淆**）

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
| 专项测试 | **41 passed / 0 failed / 0 skipped** |
| 全量测试 | 2973 → **3014**（**+41**） |

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

