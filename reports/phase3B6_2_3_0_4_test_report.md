# 阶段3B-6.2.3.0.4 测试报告：10 条 2004-01-01 占位记录溯源

> **所有测试真实读取数据库、真实证据文件、真实项目代码。**

**基线 HEAD**：`759bcabaae6efee26abfbe056e4978d3d16e15c6`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_0_4_placeholder.py` — **62 项**

---

## 2. 覆盖任务要求 17 项

| # | 任务要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 目标记录恰好 10 条 | `test_target_count_is_exactly_10`、`test_target_codes_match_expected` | ✅ |
| 2 | 目标日期全部为 2004-01-01 | `test_all_target_date_is_2004_01_01` | ✅ |
| 3 | 10 条全部保持 suspect | `test_all_still_suspect`、`test_all_have_quality_note` | ✅ |
| 4 | 逐条记录字段完整 | `test_all_fields_complete` | ✅ |
| 5 | 每条记录均有独立审计结论 | `test_every_record_has_conclusion`、`test_conclusions_are_distinct_per_index` | ✅ |
| 6 | 不得把基日误认为发布日 | `test_base_date_not_confused_with_publish_date`、`test_base_date_values_are_real` | ✅ |
| 7 | 不得把基点值误认为真实行情 | `test_base_value_not_treated_as_quote`、`test_non_confused_rows_are_not_base_values` | ✅ |
| 8 | 不得将日历代理描述为官方日历 | `test_calendar_proxy_not_official` | ✅ |
| 9 | 无证据时必须保留 unknown | `test_unknown_kept_when_no_evidence` | ✅ |
| 10 | 不得将第三方资料冒充官方证据 | `test_no_l3_dressed_as_official`、`test_all_evidence_is_L1` | ✅ |
| 11 | 原始证据 SHA256 可复核 | `test_evidence_sha256_verifiable` | ✅ |
| 12 | 正式数据库只读 | `test_database_read_only_sha_unchanged` | ✅ |
| 13 | 数据库前后 SHA256 一致 | `test_database_sha_matches_baseline_json` | ✅ |
| 14 | `integrity_check` 正常 | `test_integrity_check_ok` | ✅ |
| 15 | `foreign_key_check` 为 0 | `test_foreign_key_check_zero` | ✅ |
| 16 | 其他指数指纹不变 | `test_other_indexes_untouched`、`test_total_rows_unchanged` | ✅ |
| 17 | 不修改 H30184 修复结果 | `test_h30184_repair_not_rerun`、`test_suspect_total_still_11` | ✅ |

---

## 3. 测试清单（37 项，按类别）

### 3.1 目标记录（6 项）

| 测试 | 断言 |
| --- | --- |
| `test_target_count_is_exactly_10` | 恰好 10 条 |
| `test_target_codes_match_expected` | 指数集合与任务一致 |
| `test_all_target_date_is_2004_01_01` | 日期全部为 `2004-01-01` |
| `test_all_still_suspect` | 全部仍为 `suspect` |
| `test_all_have_quality_note` | 全部带「基线占位行」说明 |
| `test_all_fields_complete` | 15 个字段齐全，`source`/`run_id`/`collected_at`/`row_fingerprint` 非空 |

### 3.2 逐条结论（2 项）

| 测试 | 断言 |
| --- | --- |
| `test_every_record_has_conclusion` | 每条有结论、等级、动作、来源键 |
| `test_conclusions_are_distinct_per_index` | 结论不重复（按指数+基日+发布日+close 去重） |

### 3.3 基日 vs 发布日（2 项）

| 测试 | 断言 |
| --- | --- |
| `test_base_date_not_confused_with_publish_date` | 10 个指数基日 ≠ 发布日 |
| `test_base_date_values_are_real` | 逐指数对照官方基本信息接口的基日值 |

### 3.4 基点 vs 行情（2 项）

| 测试 | 断言 |
| --- | --- |
| `test_base_value_not_treated_as_quote` | 5 个基点混淆的指数，close == basicIndex 且仍标合成行 |
| `test_non_confused_rows_are_not_base_values` | 另 5 个 close ≠ basicIndex，但**同样是合成行** |

> 第二项是防止「简单归结为基点误写」的关键——证明另 5 条不是基点值，机制相同。

### 3.5 日历代理（1 项）

| 测试 | 断言 |
| --- | --- |
| `test_calendar_proxy_not_official` | 每条记录的 note 含「代理」且含「不是指数官方发布日历」；`trade_calendar` 无 `2004-01-01` |

### 3.6 证据与 unknown（3 项）

| 测试 | 断言 |
| --- | --- |
| `test_unknown_kept_when_no_evidence` | `historical_availability == "unknown"` 且有「不能证明」说明 |
| `test_no_l3_dressed_as_official` | L1 必须有官方 URL（`csindex.com.cn`）+ SHA256 |
| `test_all_evidence_is_L1` | L1=10，L3=0，insufficient=0 |

### 3.7 证据可复核（1 项）

| 测试 | 断言 |
| --- | --- |
| `test_evidence_sha256_verifiable` | 10 份证据文件存在，SHA256 与记录一致，长度 64 |

### 3.8 来源溯源（6 项）

| 测试 | 断言 |
| --- | --- |
| `test_source_is_official_api_not_internal` | 来源键为 `official_api_synthetic_start_row`，DB 值 == 官方值 |
| `test_all_synthetic_start_rows` | 10/10 合成行，10/10 改起始日后消失 |
| `test_row_equals_second_row_all` | 10/10 数值等于第二行 |
| `test_no_hardcoded_value_in_production_code` | 5 个真实行情值在生产代码命中 0 次 |
| `test_ingest_start_date_causes_synthetic_row` | `DEFAULT_START = "20040101"` 存在 |
| `test_ingest_marks_baseline_as_suspect` | 采集脚本含 baseline/suspect/占位 逻辑 |
| `test_run_records_requested_from_20040101` | 采集批次 `request_start_date == 20040101` |

### 3.9 数据库不变性（8 项）

| 测试 | 断言 |
| --- | --- |
| `test_database_read_only_sha_unchanged` | SHA256 == `1671e403…e873` |
| `test_database_sha_matches_baseline_json` | 审计 JSON 基线 SHA 一致 |
| `test_integrity_check_ok` | `ok` |
| `test_foreign_key_check_zero` | 0 |
| `test_total_rows_unchanged` | 50,603 |
| `test_other_indexes_untouched` | 其他指数行数+指纹与基线快照完全一致 |
| `test_h30184_repair_not_rerun` | `2013-06-28` 仍 `suspect` 且 `close=0.0` |
| `test_suspect_total_still_11` | suspect 总数仍 11 |

### 3.10 门禁与报告（5 项）

| 测试 | 断言 |
| --- | --- |
| `test_gates_all_closed` | 四项门禁值正确 |
| `test_reports_exist` | 三份报告存在 |
| `test_audit_report_has_per_record_conclusions` | 审计报告含全部 10 个指数代码 |
| `test_self_check_all_pass` | 审计自校验 6 项全 True |
| `test_no_vacuous_assertion` | 无恒真断言 |

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **62 passed / 0 failed / 0 skipped** |
| 全量测试 | 2594 → **2656**（+62） |

---

## 5. 关键测试证据（真实执行输出）

### 5.1 目标记录

```
000300   close=1204.61    grade=L1  synth=True  origin=official_api_synthetic_start_row
000905   close=1000.0     grade=L1  synth=True  origin=official_api_synthetic_start_row
000906   close=1000.0     grade=L1  synth=True  origin=official_api_synthetic_start_row
000922   close=1000.0     grade=L1  synth=True  origin=official_api_synthetic_start_row
000942   close=1000.0     grade=L1  synth=True  origin=official_api_synthetic_start_row
399997   close=1028.64    grade=L1  synth=True  origin=official_api_synthetic_start_row
930930   close=3000.0     grade=L1  synth=True  origin=official_api_synthetic_start_row
H30184   close=994.47     grade=L1  synth=True  origin=official_api_synthetic_start_row
```

### 5.2 汇总

```
target_count: 10
official_evidence_obtained: 10
synthetic_start_row_count: 10
disappears_from_20040102_count: 10
db_matches_official_close: 10
row_equals_second_row: 10
row_zero_volume_amount: 5
base_value_confusion: 5
all_still_suspect: 10
evidence_grade_counts: {"L1": 10}
historical_availability_unknown: 10
```

### 5.3 内部代码扫描

```
994.47   生产代码命中=0
1204.61  生产代码命中=0
1028.64  生产代码命中=0
1011.35  生产代码命中=0
99.22    生产代码命中=0
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | `2004-01-01` 真实历史时点可用性 | 官方无历史快照，无法测试「当时已公开」路径 |
| 2 | 官方为何合成起始日行 | 无官方说明，无法验证 |
| 3 | 5 个基点值是否为官方刻意填充 | 无法证实也无法证伪 |
| 4 | 官方历史数据是否被修订 | 无历史版本归档 |
| 5 | 采集脚本改用 `20040102` 后是否完全不产生合成行 | 需修改采集逻辑（本轮禁止），仅做只读对照实验 |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

---

## 8. 3B-6.2.3.0.4.1 追加：字段语义纠偏与证据 SHA256 补强（+25 项）

### 8.1 修正的问题

| # | 问题 | 修正 |
| ---: | --- | --- |
| 1 | `earliest_official_history` 把 API 响应首日说成「官方最早历史日期」 | 改名为 `earliest_response_date`，并新增 `actual_earliest_historical_quote_date = unknown` |
| 2 | `test_evidence_sha256_verifiable` 只覆盖 10 份基本信息文件 | 改为覆盖 **30 份**（10 基本 + 10 历史 + 10 对照），真实计算二进制哈希 |
| 3 | 报告第 3 节把 10 个指数的 `2004-01-01` 统一写成「官方最早历史」 | 重写为「四类日期严格区分」 |

### 8.2 新增测试（25 项）

**字段语义（5 项）**

| 测试 | 断言 |
| --- | --- |
| `test_no_earliest_official_history_field` | 旧字段已从所有记录移除 |
| `test_earliest_response_date_matches_real_json` | 逐条与真实 JSON 首行日期比对 |
| `test_actual_earliest_quote_date_unknown` | 10/10 为 `unknown` 且有依据说明 |
| `test_four_date_concepts_distinguished` | 四类日期字段均存在且不互相替代 |
| `test_date_semantics_declared` | 审计 JSON 显式声明四类语义 |

**报告措辞（1 项）**

| 测试 | 断言 |
| --- | --- |
| `test_report_not_claiming_20040101_as_real_history` | 报告中「官方最早历史」已消失，`**unknown**` 出现 ≥10 次 |

**30 份证据 SHA256（5 项）**

| 测试 | 断言 |
| --- | --- |
| `test_30_evidence_files_exist` | 30 份文件全部存在且非空 |
| `test_30_evidence_sha256_matches_manifest` | 真实计算二进制 SHA256 与 manifest 逐一比对 |
| `test_30_evidence_sha256_matches_audit_json` | 与审计 JSON 记录逐一比对（含字节数） |
| `test_evidence_sha256_cross_check_three_sources` | 文件实际哈希 == manifest == 审计 JSON 三方一致 |
| `test_no_sha256_string_length_only_check` | 测试代码本身必须含真实哈希计算 |

**URL 与日期集合（4 项）**

| 测试 | 断言 |
| --- | --- |
| `test_hist_url_start_param_is_20040101` | 10/10 历史请求 `startDate=20040101` |
| `test_ctrl_url_start_param_is_20040102` | 10/10 对照请求 `startDate=20040102` |
| `test_hist_contains_20040101_ctrl_does_not` | 历史响应含 10/10，对照响应含 0/10 |
| `test_first_date_consistent_with_parsed` | 记录的首日/行数与实际 JSON 解析一致 |

**原结论不变（2 项）**

| 测试 | 断言 |
| --- | --- |
| `test_original_conclusions_unchanged` | 10 条目标、10 合成行、5 基点混淆、L1=10 等全部不变 |
| `test_synthetic_mechanism_not_claimed_as_official_announcement` | 报告明确说明是技术判断，非官方公告 |

**数据库与门禁（8 项）**

| 测试 | 断言 |
| --- | --- |
| `test_db_sha256_unchanged_again` | SHA256 仍为 `1671e403…e873` |
| `test_integrity_ok_again` | `ok` |
| `test_fk_zero_again` | 0 |
| `test_targets_still_10_suspect` | 10 条仍全部 suspect |
| `test_suspect_total_11` | suspect 总数仍 11 |
| `test_h30184_still_suspect_zero` | `2013-06-28` 仍 `(0.0, 'suspect')` |
| `test_gates_unchanged_again` | 四项门禁不变 |
| `test_self_check_includes_new_assertions` | 新增 7 项自校验全部 True |

### 8.3 修正过程中发现并修复的两个自身缺陷

| # | 缺陷 | 修复 |
| ---: | --- | --- |
| 1 | 离线模式下 `official_basic` 缺 `url` 字段，导致 L1 来源校验失败 | `load_saved_basic()` 补 `url = CSI_BASIC + code` |
| 2 | 代码扫描把 `tests/` 与**扫描器自身**的 `MAGIC_VALUES` 常量算作「生产代码硬编码」 | 扫描范围排除 `tests/` 与扫描器自身，并分别统计 `production_code_hits` / `test_code_hits` |

> 第 2 项是真实的逻辑缺陷：扫描器的目标清单本身就是这些数值，
> 若不排除自身会产生「自己检测到自己」的假阳性。

### 8.4 30 份证据 SHA256 验证结果

| 类别 | 文件数 | 存在 | SHA256 匹配 manifest | 匹配审计 JSON |
| --- | ---: | ---: | ---: | ---: |
| `csindex_basic_<code>.json` | 10 | 10 | 10 | 10 |
| `csindex_hist_<code>_from20040101.json` | 10 | 10 | 10 | 10 |
| `csindex_ctrl_<code>_from20040102.json` | 10 | 10 | 10 | 10 |
| **合计** | **30** | **30** | **30** | **30** |

### 8.5 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |
