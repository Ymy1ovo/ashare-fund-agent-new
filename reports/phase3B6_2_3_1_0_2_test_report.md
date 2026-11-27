# 阶段3B-6.2.3.1.0.2 测试报告

> **真实调用业务函数 + 真实读取文件 + 真实计算 SHA256。**

**基线 HEAD**：`35f056c8aefe1408e239d1e5b226d8c5531c86b0`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_0_2_evidence_fix.py`

---

## 2. 覆盖任务要求 20 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | H00016 映射到 000016 | `test_h00016_maps_to_000016` | ✅ |
| 2 | H00300 映射到 000300 | `test_h00300_maps_to_000300` | ✅ |
| 3 | H20184 映射到 H30184 | `test_h20184_maps_to_h30184` | ✅ |
| 4 | 债券不用 A 股日历判断合成行 | `test_bond_not_using_a_calendar_for_synthetic` | ✅ |
| 5 | 港股不用 A 股日历判断合成行 | `test_hk_not_using_a_calendar_for_synthetic` | ✅ |
| 6 | 原指数对照≠候选自身对照 | `test_price_control_not_equal_candidate_control` | ✅ |
| 7 | 无对照文件时必须 unknown | `test_no_candidate_has_own_control` | ✅ |
| 8 | control=None 不得声称通过 | `test_control_none_not_claiming_pass`、`test_evidence_has_no_fabricated_control` | ✅ |
| 9 | 三种状态边界 | `test_three_synthetic_statuses_defined`、`test_no_confirmed_without_own_control` | ✅ |
| 10 | 证据不足时真实起点 unknown | `test_real_start_unknown_when_not_confirmed` | ✅ |
| 11 | 对照文件真实 SHA256 | `test_control_files_sha256_verified` | ✅ |
| 12 | manifest 数量与实际一致 | `test_manifest_count_matches_actual` | ✅ |
| 13 | manifest 文件存在或记录缺失 | `test_manifest_files_exist_or_recorded_missing`、`test_missing_control_files_recorded` | ✅ |
| 14 | 零成交量但收盘变化不得确认 | `test_zero_volume_alone_not_confirmed` | ✅ |
| 15 | changePct 小但收盘变化不得确认 | `test_tiny_pct_with_close_change_not_confirmed` | ✅ |
| 16 | 收盘相同但缺官方日历不得冒充 | `test_same_close_without_official_calendar_not_confirmed` | ✅ |
| 17 | suspected 不能使连续性 verified | `test_suspected_does_not_make_continuity_verified` | ✅ |
| 18 | JSON 与报告状态一致 | `test_json_and_report_consistent` | ✅ |
| 19 | 原始 44 份证据不变 | `test_original_44_evidence_unchanged` | ✅ |
| 20 | 数据库 SHA256 不变 | `test_db_sha256_unchanged` | ✅ |

---

## 3. 测试设计要点

### 3.1 真实调用业务函数

| 测试 | 调用 |
| --- | --- |
| 对照映射 | `price_code_of()`、`control_evidence()` |
| 合成行分级 | `detect_synthetic_start()` |
| 休市分类 | `classify_outside_calendar()`、`continuity_after_classification()` |

### 3.2 负向测试必须存在

| 测试 | 负向条件 |
| --- | --- |
| `test_zero_volume_alone_not_confirmed` | 零成交 + close 变化 → 不得 confirmed |
| `test_tiny_pct_with_close_change_not_confirmed` | changePct 小 + close 变化 → 不得 confirmed |
| `test_same_close_without_official_calendar_not_confirmed` | close 相同但无官方日历 → 不得 confirmed |
| `test_suspected_does_not_make_continuity_verified` | suspected → 连续性不得 verified |
| `test_control_none_not_claiming_pass` | 无对照 → 不得声称通过 |
| `test_no_confirmed_without_own_control` | 无自身对照 → 不得 confirmed |

### 3.3 2018-06-18 证据不一致必须验证

`test_2018_06_18_per_index_evidence_differs` 断言：

- `H00300` 的 `same_as_prev` 为 `False`（close 变化）
- `H20539` 的 `same_as_prev` 为 `True`（close 相同）
- `H20184` 的 `same_as_prev` 为 `True`

**证明不能把一个指数的证据推广到全部指数。**

### 3.4 SHA256 真实计算

```python
actual = hashlib.sha256(f.read_bytes()).hexdigest()
assert actual == info["sha256"]
assert info["bytes"] == f.stat().st_size
```

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **42 passed / 0 failed / 0 skipped** |
| 全量测试 | 2741 → **2783**（**+42**） |

---

## 5. 关键测试证据

### 5.1 合成行分级（真实输出）

```
synthetic_confirmed: 0
synthetic_strong_inference: 12
synthetic_unknown: 0
tr_candidate_control_available: 0
price_index_control_available: 12
real_history_start_unknown: 12
```

### 5.2 自校验

```
{
 "no_candidate_has_own_control": true,
 "price_controls_found": true,
 "no_confirmed_without_own_control": true,
 "real_start_unknown_when_not_confirmed": true,
 "bond_hk_no_a_calendar_evidence": true,
 "no_continuity_verified_with_suspicion": true
}
```

### 5.3 manifest

```
referenced_total: 66
missing_count: 12（全收益候选对照文件）
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 全收益候选自身对照实验 | 本轮未下载，仅有原指数对照 |
| 2 | 官方交易日历（债券/港股） | 未取得 |
| 3 | 2018-06-18 是否为休市占位 | 无官方日历证据，只能 suspected |
| 4 | 真实历史起点 | 12/12 unknown |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

