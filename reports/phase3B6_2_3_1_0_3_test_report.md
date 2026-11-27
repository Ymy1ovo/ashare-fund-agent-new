# 阶段3B-6.2.3.1.0.3 测试报告

> **真实调用准入计算函数 + 真实读取三方 JSON + 真实计算 SHA256。**

**基线 HEAD**：`03f72f061ce16bd1f8d21c8847d7dca3a2052194`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_0_3_consistency.py`

---

## 2. 覆盖任务要求 13 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 代理日历不能生成 `verified_official_calendar` | `test_proxy_calendar_cannot_yield_official_verified`、`test_no_official_calendar_verified_in_result`、`test_only_official_calendar_allows_validated` | ✅ |
| 2 | `399997CNY02` 标记为代理验证 | `test_399997cny02_marked_as_proxy` | ✅ |
| 3 | 8 只疑似占位候选不得标记已验证 | `test_eight_suspicion_not_verified` | ✅ |
| 4 | `H20184` 仍然质量不通过 | `test_h20184_quality_still_failed` | ✅ |
| 5 | 债券 2 只、港股 1 只仍为 unknown | `test_bond_hk_still_unknown` | ✅ |
| 6 | 010 与 020 JSON 无冲突 | `test_no_conflict_between_010_and_020`、`test_010_preserves_original_snapshot`、`test_020_preserves_original_status` | ✅ |
| 7 | `validated_series_candidate` 重算 | `test_validated_recomputed` | ✅ |
| 8 | `proxy_qualified_series_candidate` 独立统计 | `test_proxy_qualified_counted_separately` | ✅ |
| 9 | JSON、主报告、两份修正报告数量一致 | `test_all_json_counts_consistent`、`test_reports_mention_same_numbers`、`test_010_report_marked_superseded` | ✅ |
| 10 | `formal_series_admitted=0` | `test_formal_admitted_zero` | ✅ |
| 11 | 原始官方证据 SHA256 不变 | `test_original_evidence_sha256_unchanged` | ✅ |
| 12 | 正式数据库 SHA256 不变 | `test_db_sha256_unchanged`、`test_db_unchanged_flag` | ✅ |
| 13 | 门禁没有被意外开放 | `test_gates_not_opened` | ✅ |

---

## 3. 测试设计要点

### 3.1 真实调用准入计算函数

`test_admission_computed_by_real_function` 对每个候选：

1. 从 JSON 重建 `cand` 结构；
2. 调用真实 `compute_admission(cand)`；
3. 与 JSON 中记录的四个状态逐一比对。

**不是只检查 Markdown 字符串。**

### 3.2 五态映射函数必须直接测试

```python
assert map_continuity_level("verified", False) == "verified_against_proxy_calendar"
assert map_continuity_level("verified", True) == "verified_official_calendar"
```

**代理日历永不产出 `verified_official_calendar`。**

### 3.3 三方一致性必须验证

```python
l1 = d1候选["quality"]["continuity_status"]
l2 = d2候选["quality"]["continuity_level"]
l3 = d3候选["continuity_level"]
assert l1 == l2 == l3
```

### 3.4 负向测试

| 测试 | 负向条件 |
| --- | --- |
| `test_eight_suspicion_not_verified` | 疑似占位 → 不得 validated/proxy |
| `test_h20184_quality_still_failed` | 零值 → 不得 validated |
| `test_bond_hk_still_unknown` | 无日历 → 不得 validated |
| `test_formal_admitted_zero` | 全部不得正式准入 |

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **32 passed / 0 failed / 0 skipped** |
| 全量测试 | 2783 → **2815**（**+32**） |

---

## 5. 关键测试证据

### 5.1 五态统计（真实输出）

```
continuity_verified_official_calendar: 0
continuity_verified_against_proxy_calendar: 1
continuity_has_unresolved_suspicion: 8
continuity_has_issues: 0
continuity_unknown: 3
```

### 5.2 四状态统计

```
raw_data_layer_ingest_candidate: 12
validated_series_candidate: 0
proxy_qualified_series_candidate: 1
formal_series_admitted: 0
```

### 5.3 自校验

```
{
 "no_official_calendar_verified": true,
 "proxy_only_399997CNY02": true,
 "eight_suspicion_not_verified": true,
 "h20184_quality_failed": true,
 "bond_hk_unknown": true,
 "no_formal_admitted": true,
 "ingest_all_12": true
}
```

### 5.4 三方一致性

```
H00300       010=has_unresolved_suspicion  020=has_unresolved_suspicion  030=has_unresolved_suspicion  OK
399997CNY02  010=verified_against_proxy     020=verified_against_proxy     030=verified_against_proxy     OK
...
三方完全一致: True
```

---

## 6. 未覆盖的事项

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 官方指数发布日历 | 未取得（全部为代理或 unknown） |
| 2 | 全收益候选自身对照实验 | 未下载 |
| 3 | 真实历史起点 | 12/12 unknown |
| 4 | 历史时点可用性 | 官方无历史快照 |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

