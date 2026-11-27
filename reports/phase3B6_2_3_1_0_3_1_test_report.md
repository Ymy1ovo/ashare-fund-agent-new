# 阶段3B-6.2.3.1.0.3.1 测试报告

> **真实调用 `compute_admission()`**，不使用固定文本自证。

**基线 HEAD**：`586cd83b5a86728c10556079ac69fde4c66b3007`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_0_3_1_proxy_start.py`

---

## 2. 覆盖任务要求 10 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 代理连续但真实起点 unknown → 代理准入 false | `test_proxy_true_requires_known_start`、`test_proxy_rejects_none_start` | ✅ |
| 2 | 代理连续且起点已知 → 允许 true | `test_proxy_true_when_start_known` | ✅ |
| 3 | 官方连续但起点 unknown → validated false | `test_official_continuity_still_needs_known_start` | ✅ |
| 4 | 两类准入均须检查真实起点 | `test_both_admissions_check_real_start` | ✅ |
| 5 | 12 只重新计算后代理验证为 0 | `test_proxy_qualified_zero_in_result` | ✅ |
| 6 | `399997CNY02` 保留代理等级但准入 false | `test_399997cny02_keeps_level_but_not_admitted` | ✅ |
| 7 | 三份 JSON 与报告统计一致 | `test_three_json_consistent`、`test_reports_match_json`、`test_admission_recomputed_matches_json` | ✅ |
| 8 | 原始证据 SHA256 不变 | `test_original_evidence_sha256_unchanged` | ✅ |
| 9 | 数据库 SHA256 不变 | `test_db_sha256_unchanged`、`test_db_unchanged_flag` | ✅ |
| 10 | 所有门禁保持关闭 | `test_gates_all_closed` | ✅ |

---

## 3. 测试设计要点

### 3.1 真实调用 `compute_admission()`

所有准入判定测试都构造最小候选结构后**真实调用函数**：

```python
r = compute_admission(_mk("verified_against_proxy_calendar",
                          real_start="unknown"))
assert r["proxy_qualified_series_candidate"] is False
```

**不检查 Markdown 文本。**

### 3.2 对称性测试

`test_both_admissions_check_real_start` 同时验证两种连续性等级：

| 连续性等级 | 起点 unknown | 起点已知 |
| --- | --- | --- |
| `verified_official_calendar` | validated=F, proxy=F | validated=**T**, proxy=T |
| `verified_against_proxy_calendar` | validated=F, proxy=F | validated=F, proxy=**T** |

**证明两类准入都检查真实起点，且只有官方等级才允许 validated。**

### 3.3 其他条件不得被忽略

`test_proxy_still_requires_other_conditions` 逐个关闭身份/口径/映射/质量/覆盖，
验证代理准入仍然拒绝——**放宽的只有连续性门槛，不是全部条件。**

### 3.4 重算与 JSON 一致

`test_admission_recomputed_matches_json` 对 12 只候选逐一重算四个状态，
与 JSON 记录比对。

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **28 passed / 0 failed / 0 skipped** |
| 全量测试 | 2815 → **2843**（**+28**） |

---

## 5. 关键测试证据

### 5.1 四状态（真实输出）

```
raw_data_layer_ingest_candidate: 12
validated_series_candidate: 0
proxy_qualified_series_candidate: 0
formal_series_admitted: 0
```

### 5.2 五态连续性（未变）

```
continuity_verified_official_calendar: 0
continuity_verified_against_proxy_calendar: 1
continuity_has_unresolved_suspicion: 8
continuity_has_issues: 0
continuity_unknown: 3
```

### 5.3 `399997CNY02` 阻断明细

```
continuity_level: verified_against_proxy_calendar
raw_data_layer_ingest_candidate: True
validated_series_candidate: False
proxy_qualified_series_candidate: False
formal_series_admitted: False
blockers: ['连续性=verified_against_proxy_calendar', '真实历史起点未知', '时点可用性']
proxy_blockers: ['真实历史起点未知']
note: 可进原始隔离层；连续性已达代理等级，但**代理验证候选仍未通过**；不得正式准入
```

---

## 6. 未覆盖的事项

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 官方指数发布日历 | 未取得 |
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

