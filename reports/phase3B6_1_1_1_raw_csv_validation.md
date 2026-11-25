# 阶段3B-6.1.1.1 原始 CSV 重复记录与异常行独立校验

- 任务基线：`2ea53601ad84f74877a9f44c8c3d4048f0d4ec52`

> 本轮只增强测试的独立校验能力，**不重新下载数据、不改审计结论、不动数据库**。

---

## 0. 原测试为什么不可靠

### 0.1 重复记录检测失效

原测试这样解析原始 CSV：

```python
series[(date, tenor)] = value   # 字典赋值
```

**字典赋值会覆盖同键的前一条记录。** 重复行在进入检查之前就已经消失，
因此后续 `len(dates) - len(set(dates))` 必然等于 0——**这不是「没有重复」，
而是「重复被吞掉了」。**

本轮用临时 CSV 做了反证：

| 构造 | 字典法结果 | 逐行扫描结果 |
| --- | --- | --- |
| 两条完全相同的行（同日期同期限同数值） | **8 条记录**（重复消失） | **16 条记录，8 对重复** |

### 0.2 异常行被静默跳过

原解析器：

```python
try:
    d = date.fromisoformat(ds)
except ValueError:
    continue          # 坏日期静默跳过
v = (row.get(t) or "").strip()
if not v or v.lower() == "nan":
    continue          # 空值/NaN 静默跳过
try:
    series[(d, t)] = float(v)
except ValueError:
    pass              # 非数值静默跳过
```

**三类问题全部被 `continue` / `pass` 吞掉**，从统计上无法区分
「数据干净」与「数据有问题但被跳过」。

---

## 1. 修正后的逐行扫描

新增 `scripts/scan_3b6_1_1_1_raw_csv.py`：

```
逐行读取 → 记录原始行 → 检查日期 → 逐期限检查单元格 → 汇总
         （不去重，不去异常，全部计数）
```

**先计数，后判断**——顺序与原测试相反。

---

## 2. 真实数据扫描结果

### 2.1 行级统计

| 项 | 数量 |
| --- | ---: |
| 扫描文件数 | **42** |
| 原始数据行数（仅国债曲线） | **5,185** |
| 日期可解析行 | **5,185** |
| 日期不可解析行 | **0** |

### 2.2 单元格级统计

| 项 | 数量 |
| --- | ---: |
| 有效记录（行 × 8 期限） | **41,480** |
| 空值单元格 | **0** |
| 非数值单元格 | **0** |
| NaN 单元格 | **0** |
| Inf 单元格 | **0** |
| 超出合理范围（<0 或 >15） | **0** |

### 2.3 重复与冲突

| 项 | 数量 |
| --- | ---: |
| 唯一 `(日期, 期限)` 组合 | **41,480** |
| **重复对数** | **0** |
| **同键数值冲突** | **0** |

**唯一组合数 = 有效记录数（41,480），说明零重复。**
若存在重复，唯一数会小于有效记录数。

### 2.4 各期限记录数

| 期限 | 逐行扫描 | coverage_quality.json | 一致 |
| --- | ---: | ---: | --- |
| `3月` | 5,185 | 5,185 | ✅ |
| `6月` | 5,185 | 5,185 | ✅ |
| `1年` | 5,185 | 5,185 | ✅ |
| `3年` | 5,185 | 5,185 | ✅ |
| `5年` | 5,185 | 5,185 | ✅ |
| `7年` | 5,185 | 5,185 | ✅ |
| `10年` | 5,185 | 5,185 | ✅ |
| `30年` | 5,185 | 5,185 | ✅ |

---

## 3. 交叉复算（与既有审计结论比对）

| 项 | 逐行扫描 | 现有报告 | 一致 |
| --- | ---: | ---: | --- |
| 有效记录总数 | 41,480 | 41,480（source_audit） | ✅ |
| 原始行数 / 独立日期 | 5,185 | 5,185（source_audit） | ✅ |
| 各期限记录数 | 均为 5,185 | 均为 5,185 | ✅ |

**结论：现有审计统计数字全部经独立复算确认无误。**

---

## 4. 新测试（25 项）

### 4.1 反证：字典法必然失效

| 测试 | 断言 |
| --- | --- |
| `test_dict_parsing_hides_duplicates` | 构造 2 条完全相同的行 → 字典法只得到 8 条且查重为 0；逐行扫描发现 16 条、8 对重复 |

### 4.2 真实数据校验

| 测试 | 断言 |
| --- | --- |
| `test_raw_rows_counted_before_dedup` | 42 文件、行数 > 0、日期全部可解析 |
| `test_valid_records_equal_rows_times_tenors` | 有效记录 = 行数 × 8 |
| `test_no_duplicate_pairs_in_real_data` | 重复对数 = 0，唯一组合 = 有效记录 |
| `test_conflict_count_zero` | 冲突 = 0 |
| `test_records_per_tenor_match_coverage_json` | 逐期限与报告一致 |
| `test_total_records_match_source_audit` | 41,480 与 source_audit 一致 |
| `test_distinct_dates_match_source_audit` | 5,185 与 source_audit 一致 |
| `test_zero_defects_in_real_data` | 全部缺陷计数为 0 |

### 4.3 构造用例：发现问题能力验证

| 构造 | 测试 | 期望 |
| --- | --- | --- |
| 同日期同期限**同数值**重复 | `test_duplicate_same_value_detected` | ✅ 发现 2 次，非冲突 |
| 同日期同期限**异数值**重复 | `test_duplicate_different_value_detected_as_conflict` | ✅ 识别为冲突 |
| 空值 | `test_empty_value_detected` | ✅ `empty_value_cells >= 1` |
| 非数值 `abc` | `test_non_numeric_detected` | ✅ 计数 1 + 样本 |
| 错误格式 `2024/01/02` | `test_bad_date_detected` | ✅ 计数 1 |
| 不可能日期 `2024-02-31` | `test_impossible_date_detected` | ✅ 计数 1 |
| 空日期 | `test_empty_date_detected` | ✅ 计数 1 |
| NaN | `test_nan_detected` | ✅ 计数 ≥ 1 |
| 超范围 `999.0` | `test_out_of_range_detected` | ✅ 计数 1 |
| **正常记录** | `test_normal_records_not_flagged` | ✅ **零误判** |
| 非国债曲线行 | `test_non_curve_rows_ignored` | ✅ 不计入 |

**`test_normal_records_not_flagged` 是反向验证的关键**——
只证明「能发现问题」不够，还必须证明「不会把正常数据判成问题」。

---

## 5. 结论

### 5.1 真实数据：无新发现的异常

| 缺陷类型 | 实测 |
| --- | ---: |
| 日期不可解析 | **0** |
| 空值 | **0** |
| 非数值 | **0** |
| NaN / Inf | **0 / 0** |
| 超范围 | **0** |
| 重复记录 | **0** |
| 数值冲突 | **0** |

**现有审计统计数字（41,480 条有效记录、8 × 5,185、5,185 独立日期）全部确认无误。**

### 5.2 但原测试的证明力确实不足

原测试得出的「无重复」结论**恰好正确，但推理过程不可靠**——
它无法区分「真的没有重复」与「重复被字典吞掉」。
本轮通过逐行扫描 + 反证用例，把这个结论**重新建立在可验证的基础上**。

---

## 7. 3B-6.1.1.1.1 修正：七类互斥 + 缺失字段显式报错

### 7.1 修正前的两个边界问题

| # | 问题 | 后果 |
| ---: | --- | --- |
| 1 | `_is_number()` 把 NaN、Inf 一并判为「非数值」 | `inf_cells` **永远统计不到**，NaN 与 Inf 混作一类 |
| 2 | 用 `if t in header` 过滤期限列 | CSV 缺列时**静默跳过**，仍输出看似完整的 8 期限统计 |

### 7.2 修正后：七类互斥分类

`classify_cell()` 返回七类之一，**优先级固定**：

| 序 | 类别 | 判定 | 计入字段 |
| ---: | --- | --- | --- |
| 1 | `empty` | 空串 / `None` / `null` | `empty_value_cells` |
| 2 | `nan` | `nan` / `NaN` / `-nan` | `nan_cells` |
| 3 | `inf` | `inf` / `-inf` / `Infinity` / `1e999` | `inf_cells` |
| 4 | `non_numeric` | `abc` 等无法转 float | `non_numeric_cells` |
| 5 | `out_of_range` | 有限但 < 0 或 > 15 | `out_of_range_cells` |
| 6 | `valid` | 有限且在 [0, 15] | `valid_cells` |

**关键约束**：

| 约束 | 验证测试 |
| --- | --- |
| NaN **只**计 nan，不计 empty | `test_nan_counted_only_as_nan` |
| Inf **只**计 inf，不计 non_numeric | `test_inf_counted_only_as_inf` |
| `-inf` 同样计 inf | `test_neg_inf_counted_as_inf` |
| `abc` 计 non_numeric | `test_abc_counted_as_non_numeric` |
| 三者同现互不混淆 | `test_mixed_nan_inf_abc_not_confused` |
| 异常样本保留行号/期限/原值 | `test_bad_samples_keep_line_tenor_raw` |

### 7.3 缺失期限字段显式报错

| 项 | 实现 |
| --- | --- |
| 必需列 | `曲线名称`、`日期` + **8 个期限** |
| 检查时机 | 读取 header 后立即检查 |
| 记录内容 | `missing_columns`（文件名 + 缺失字段名）、`tenor_presence`（逐期限是否存在） |
| 结构标记 | `structure_ok=False` |
| 汇总 | `structure_all_ok`、`files_with_missing_columns`、`missing_columns_union` |

**缺列时不得把其余字段统计伪装成完整的 8 期限结果。**

| 验证测试 | 断言 |
| --- | --- |
| `test_missing_tenor_column_detected` | 删 `5年` → `structure_ok=False`，`missing_columns` 含 `5年` |
| `test_missing_multiple_columns_detected` | 删 `3月`+`30年` → 两者都记录 |
| `test_missing_date_column_detected` | 删 `日期` → 记录 |
| `test_complete_8_tenor_csv_passes` | 完整 CSV → `structure_ok=True`，零缺陷 |

### 7.4 真实数据复核（修正后重跑 42 份）

| 项 | 修正后 | 与既有报告 |
| --- | ---: | --- |
| 扫描文件数 | **42** | 一致 |
| **结构全部正常** | **True** | 新增检查，全部通过 |
| 缺失字段并集 | **[]** | 无 |
| 原始数据行数 | **5,185** | 与 `distinct_dates` 一致 |
| 日期不可解析行 | **0** | — |
| 空值单元格 | **0** | — |
| **NaN 单元格** | **0** | 修正后可独立统计 |
| **Inf 单元格** | **0** | 修正后可独立统计 |
| 非数值单元格 | **0** | 修正后不含 NaN/Inf |
| 超范围单元格 | **0** | — |
| 有效单元格 | **41,480** | — |
| 有效记录 | **41,480** | 与 `rows_after_dedup` 一致 |
| 唯一 `(日期, 期限)` | **41,480** | — |
| 重复对数 | **0** | 一致 |
| 数值冲突 | **0** | 一致 |
| 各期限记录数 | **均 5,185** | 与 `coverage_quality` 一致 |

**真实数据无新增异常，既有审计结论不变。**

### 7.5 新增测试（13 项）

| 测试 | 断言 |
| --- | --- |
| `test_classify_cell_seven_categories` | 17 个输入逐一验证七类归属 |
| `test_nan_counted_only_as_nan` | nan + empty 合计 = 8，无重复计数 |
| `test_inf_counted_only_as_inf` | inf 计 1，non_numeric 计 0 |
| `test_neg_inf_counted_as_inf` | `-inf` 也计 inf |
| `test_abc_counted_as_non_numeric` | abc 计 non_numeric，不污染 nan/inf |
| `test_mixed_nan_inf_abc_not_confused` | 同行四类各自计数正确 |
| `test_bad_samples_keep_line_tenor_raw` | 样本含 line/tenor/raw |
| `test_missing_tenor_column_detected` | 删一列即报警 |
| `test_missing_multiple_columns_detected` | 删两列都记录 |
| `test_missing_date_column_detected` | 删日期列报警 |
| `test_complete_8_tenor_csv_passes` | 完整 CSV 零误判 |
| `test_scan_all_reports_structure_status` | 真实 42 份结构全 OK |
| `test_scanner_version_marked` | 版本标记 `3B-6.1.1.1.1` |

**全部调用真实扫描器逻辑**（`scanner.scan_file()` / `scanner.classify_cell()`），
不是检查源码字符串。

---

## 6. 边界

| 项 | 状态 |
| --- | --- |
| 重新请求 AKShare | **否** |
| 修改 42 份原始 CSV | **否** |
| 改变覆盖口径 | **否** |
| 改变收益率单位 | **否** |
| 改变日度化公式 | **否** |
| 修改 Sharpe | **否** |
| 写正式数据库 | **否** |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
