# 阶段3B-6.2.3.0.3 测试报告：H30184 零值修复

> **所有测试直接调用真实修复函数与真实数据库，不使用预生成报告自证。**

**基线 HEAD**：`8fdc51df2c9cd31f321041f9ff3dfc3d8d6f5de3`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_0_3_h30184_repair.py` — **28 项**

---

## 2. 覆盖任务要求 10 项

| # | 任务要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 目标异常记录准确识别 | `test_target_anomaly_identified`、`test_only_one_zero_row_in_db`、`test_is_anomaly_rejects_normal_row` | ✅ |
| 2 | 证据不足时不允许填补点位 | `test_insufficient_evidence_blocks_repair`、`test_decision_b_rejects_when_official_has_value`、`test_unknown_decision_rejected` | ✅ |
| 3 | 证据充分时只允许修复目标记录 | `test_apply_repair_dry_run_does_not_write`、`test_target_marked_suspect`、`test_total_rows_unchanged` | ✅ |
| 4 | OHLC 缺失时不得凭空补造 | `test_ohlc_not_fabricated` | ✅ |
| 5 | 其他指数记录不受影响 | `test_other_indexes_unaffected` | ✅ |
| 6 | 10 条 suspect 占位记录不受影响 | `test_placeholder_rows_intact` | ✅ |
| 7 | 修改事务失败时能回滚 | `test_transaction_rollback_on_wrong_scope` | ✅ |
| 8 | 修改前后完整性检查正常 | `test_integrity_and_fk_ok`、`test_db_sha256_is_64_hex` | ✅ |
| 9 | 异常记录不再进入有效收益计算 | `test_anomaly_excluded_from_valid_series`、`test_no_zero_close_in_valid_series` | ✅ |
| 10 | 报告记录证据等级和处理依据 | `test_repair_report_exists`、`test_report_distinguishes_fact_vs_action` | ✅ |

---

## 3. 测试清单（28 项）

### 3.1 异常识别（3 项）

| 测试 | 断言 |
| --- | --- |
| `test_target_anomaly_identified` | 目标记录 `close=0.0`、OHLC 全 null、`is_anomaly=True` |
| `test_is_anomaly_rejects_normal_row` | 正常值/None 不得误判为异常 |
| `test_only_one_zero_row_in_db` | 全库仅 1 条非正收盘，且就是目标记录 |

### 3.2 官方证据（4 项）

| 测试 | 断言 |
| --- | --- |
| `test_official_evidence_complete` | L1 等级、官方指数名、`close=0.0`、两个 64 位 SHA256 |
| `test_official_raw_files_exist` | 原始响应文件存在且 SHA256 一致 |
| `test_official_single_date_returns_empty` | 单日查询返回 0 行 |
| `test_official_range_shows_zero` | 区间查询目标日 `close=0.0`，前后日有正值 |

### 3.3 决策约束（5 项）

| 测试 | 断言 |
| --- | --- |
| `test_insufficient_evidence_blocks_repair` | 证据不足时情况 A 抛 `ValueError` |
| `test_decision_b_rejects_when_official_has_value` | 官方有正值时不得走 B |
| `test_unknown_decision_rejected` | 未知决策抛错 |
| `test_apply_repair_dry_run_does_not_write` | `dry_run` 不改数据库（SHA256 不变） |
| `test_decision_is_b` | 本轮决策为 B |

### 3.4 修复后状态（7 项）

| 测试 | 断言 |
| --- | --- |
| `test_target_marked_suspect` | `quality_status='suspect'`，`close` 原值保留 |
| `test_ohlc_not_fabricated` | OHLC 仍为 null |
| `test_original_fields_preserved` | `source`/`run_id`/`row_fingerprint`/`collected_at` 未改 |
| `test_other_indexes_unaffected` | 其他 9 个指数行数+指纹完全不变 |
| `test_placeholder_rows_intact` | 10 条占位行全部仍为 `suspect` |
| `test_total_rows_unchanged` | 总行数仍 50,603 |
| `test_suspect_count_is_11` | suspect 由 10 增至 11 |

### 3.5 事务与完整性（3 项）

| 测试 | 断言 |
| --- | --- |
| `test_transaction_rollback_on_wrong_scope` | 影响行数≠1 时抛 `RuntimeError`，总行数不变 |
| `test_integrity_and_fk_ok` | `integrity_check=ok`、`foreign_key_check=0` |
| `test_db_sha256_is_64_hex` | SHA256 为完整 64 位十六进制 |

### 3.6 收益计算影响（2 项）

| 测试 | 断言 |
| --- | --- |
| `test_anomaly_excluded_from_valid_series` | `2013-06-28` 不在 `valid` 序列；有效行数 5,314 |
| `test_no_zero_close_in_valid_series` | 全库 `valid` 且 `close<=0` 的记录数 = 0 |

### 3.7 报告与门禁（4 项）

| 测试 | 断言 |
| --- | --- |
| `test_repair_report_exists` | 三份报告存在，含 L1/情况 B/suspect |
| `test_report_distinguishes_fact_vs_action` | 报告含四段：官方确认事实/数据库实际状态/修复动作/未能确认 |
| `test_gates_unchanged` | 四个门禁均在报告中 |
| `test_no_vacuous_assertion` | 无恒真断言 |

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **38 passed / 0 failed / 0 skipped** |
| 全量测试 | 2556 → **2594**（+38） |

> 3B-6.2.3.0.3.1 追加 10 项证据来源一致性测试（详见第 8 节）。

### 4.1 因本轮修复而同步修正的既有测试（5 项）

本轮修改正式库后，有 5 个既有测试的断言前提发生变化，均已**如实更新为修复后的事实**，
不是删除测试或放宽标准：

| 测试文件 | 测试 | 原断言 | 修正后 | 修正原因 |
| --- | --- | --- | --- | --- |
| `test_3b6_0_2_3_finite_positive_close.py` | `test_production_no_infinite_close` | `non_positive == [("H30184","2013-06-28",0.0)]` | `non_positive == []` | 该行已标记 suspect，不再属 valid 序列 |
| 同上 | `test_production_zero_close_never_counted` | `total == 5315` | `total == 5314` | suspect 由 1 条增至 2 条 |
| `test_3b6_2_1_benchmark_taxonomy.py` | `test_fingerprint_unchanged` | 当前库指纹 == 3B-6.2.1 审计指纹 | 校验审计自身 before/after 一致 + 当前指纹与修复报告一致 | 本轮是授权修复，库指纹必然变化 |
| `test_3b6_2_3_0_2_continuity.py` | `test_suspect_rows_still_exist` | `suspect == 10` | `suspect == 11` 且占位行仍为 10 | 新增 1 条 suspect（目标记录） |
| 同上 | `test_h30184_zero_still_present` | `quality_status == 'valid'` | `quality_status == 'suspect'` 且 `close` 仍为 0.0 | 本轮修复动作本身 |

**关键：所有修正都保持了原有校验强度**——例如 `close` 原值仍被断言必须为 `0.0`，
占位行仍被断言必须为 10 条且状态为 `suspect`。

---

## 5. 关键测试证据

### 5.1 其他指数指纹对比（真实执行）

```
000012   rows 5558->5558 fp_same=True OK
000016   rows 5559->5559 fp_same=True OK
000300   rows 5558->5558 fp_same=True OK
000905   rows 5317->5317 fp_same=True OK
000906   rows 5317->5317 fp_same=True OK
000922   rows 5317->5317 fp_same=True OK
000942   rows 5317->5317 fp_same=True OK
399997   rows 4345->4345 fp_same=True OK
930930   rows 2999->2999 fp_same=True OK
H30184   rows 5316->5316 fp_changed=False  <- close 未改，指纹不变（符合预期）
```

### 5.2 10 条占位行（真实执行）

```
000012   2004-01-01 suspect
000016   2004-01-01 suspect
000300   2004-01-01 suspect
000905   2004-01-01 suspect
000906   2004-01-01 suspect
000922   2004-01-01 suspect
000942   2004-01-01 suspect
399997   2004-01-01 suspect
930930   2004-01-01 suspect
H30184   2004-01-01 suspect
```

**全部 10 条保留，状态未变。**

### 5.3 数据库完整性（真实执行）

```
integrity: ok
fk: 0
index_daily total: 50603
suspect rows: 11
valid & close<=0: 0
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | `2013-06-28` 真实收盘点位 | 官方无证据，无法测试「修复为真实值」路径 |
| 2 | 情况 A 的实际写入路径 | 无正值官方证据，仅测试了「证据不足时拒绝」 |
| 3 | `2013-07-01` 起 OHLC 全 null 的影响 | 超出本轮范围（只处理一条记录） |
| 4 | 其他指数是否有类似零值 | 已确认全库仅 1 条，但未逐日扫描 OHLC null |

**情况 A 的写入路径已实现且通过 `validate_decision` 的准入校验，但本轮未实际执行**——
因为没有正值官方证据，强行执行会违反「不得插值/推算」的硬约束。

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

---

## 8. 3B-6.2.3.0.3.1 追加：证据来源一致性测试（10 项）

**背景**：原报告 1.2 节的逐日表格列出了 `2013-07-03`，但
`range_20130624_20130703.json` 实际只有 7 行、截止 `2013-07-02`。
`2013-07-03` 的数据来自宽区间证据 `h30184_wide.json`。
报告未标注来源，造成「7 行区间响应含 2013-07-03」的错觉。

**修正**：表格新增「来源文件」列，逐行标注；并补充区间响应实际覆盖范围说明。

### 8.1 新增测试（全部读取真实证据文件）

| 测试 | 断言 | 数据来源 |
| --- | --- | --- |
| `test_range_evidence_row_count_is_7` | 区间响应 7 行 | 真实 JSON |
| `test_range_evidence_last_date_is_0702` | 末行为 `20130702`，且不含 `20130703` | 真实 JSON |
| `test_0703_only_in_wide_evidence` | `2013-07-03` 只在宽区间文件，`close=1569.54` | 两份 JSON |
| `test_wide_evidence_row_count_is_41` | 宽区间 41 行 | 真实 JSON |
| `test_report_does_not_attribute_0703_to_range` | 逐日表格中 `2013-07-03` 行的来源列必须是 `h30184_wide` | 报告 + 表格解析 |
| `test_report_states_range_is_7_rows` | 报告明确写出 7 行、`2013-07-02`、`h30184_wide.json` | 报告 |
| `test_report_marks_source_per_row` | 表格必须有「来源文件」列 | 报告 |
| `test_evidence_sha256_unchanged` | 三份证据 SHA256 不变 | 真实文件 + 模块常量 |
| `test_decision_and_evidence_grade_unchanged` | 证据等级仍 L1、决策仍 B | 模块常量 |
| `test_db_sha256_unchanged_by_doc_fix` | 库 SHA256 仍为修复后值 | 真实数据库 |

### 8.2 测试设计要点

**避免恒真断言**：所有断言都读取**真实证据文件**并解析 JSON，
再与报告文本/模块常量交叉比对，而不是只检查报告里是否有某个固定字符串。

**避免误判**：`test_report_does_not_attribute_0703_to_range` 只检查
「逐日数据表格中日期单元格恰为 `2013-07-03` 的行」，不会把以下合法情况判为错误：

- URL 中的 `endDate=20130703`（请求参数，非数据归属）
- 证据文件名 `range_20130624_20130703.json`（文件名含该数字）

### 8.3 证据文件 SHA256（未修改）

| 文件 | SHA256 |
| --- | --- |
| `single_20130628.json` | `8309cff714d5f872cea03bfa413b0270b30b5db6545e99d9dd2b59bc489344eb` |
| `range_20130624_20130703.json` | `ccbbb38316fab0f9c24a56d79a7c15af7559e114399253da4b5cbbb660b609e5` |
| `h30184_wide.json` | `858ecda87ee336bb0568f9bfeb9ba895f54c01eecc44b28a46e934d1614d7e26` |

**三份原始证据均未修改。**

### 8.4 本轮未改动的事项

| 项 | 状态 |
| --- | --- |
| 正式数据库 | **未修改**（SHA256 仍为 `1671e403…e873`） |
| H30184 修复动作 | **未重跑** |
| 情况 B 决策 | **未改变** |
| 证据等级 L1 | **未改变** |
| 原始证据文件 | **未修改** |
