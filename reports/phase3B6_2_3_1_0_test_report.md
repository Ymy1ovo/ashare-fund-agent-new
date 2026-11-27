# 阶段3B-6.2.3.1.0 测试报告

> **所有测试真实读取原始证据文件并重新计算 SHA256。**

**基线 HEAD**：`3ca4d733c753898e5778767a3a89a521ae7ef58d`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_0_total_return.py`

---

## 2. 测试覆盖矩阵

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 分组隔离 | `test_three_groups_disjoint`、`test_bond_and_hk_counted_separately` | ✅ |
| 2 | 8 个价格指数全覆盖 | `test_stock_price_indexes_all_covered` | ✅ |
| 3 | 官方身份核验 | `test_all_candidates_identity_verified`、`test_identity_evidence_from_official_host` | ✅ |
| 4 | 基日≠发布日 | `test_base_date_not_confused_with_publish_date` | ✅ |
| 5 | 收益口径 | `test_return_basis_from_official_name`、`test_bond_basis_not_stock_total_return` | ✅ |
| 6 | 历史接口完整 | `test_history_api_available_for_all` | ✅ |
| 7 | 证据 SHA256 真实计算 | `test_history_raw_files_exist_and_sha256`、`test_manifest_covers_all_evidence` | ✅ |
| 8 | URL 参数真实 | `test_history_url_contains_real_params` | ✅ |
| 9 | 缺失交易日为 0 | `test_no_missing_trading_days_for_stock` | ✅ |
| 10 | 真实起点识别 | `test_real_history_start_not_20040101` | ✅ |
| 11 | 日历代理声明 | `test_calendar_source_declared_as_proxy` | ✅ |
| 12 | 数据质量项齐全 | `test_data_quality_checks_present` | ✅ |
| 13 | `H20184` 零值记录 | `test_h20184_zero_value_recorded` | ✅ |
| 14 | 跨年份样本 | `test_cross_year_samples_multiple_years` | ✅ |
| 15 | 比值关系检查 | `test_ratio_relationship_checked` | ✅ |
| 16 | 早期比值=1 记录 | `test_ratio_equals_one_early_period_recorded` | ✅ |
| 17 | 技术判断声明 | `test_mapping_note_admits_technical_judgement` | ✅ |
| 18 | 时点可用性 unknown | `test_point_in_time_all_unknown`、`test_point_in_time_reason_present` | ✅ |
| 19 | 九维齐全 | `test_nine_dimensions_all_present` | ✅ |
| 20 | 无候选准入 | `test_no_candidate_admitted` | ✅ |
| 21 | 准入需八维全通过 | `test_admission_requires_all_eight` | ✅ |
| 22 | 身份通过≠准入 | `test_identity_pass_not_equal_admission` | ✅ |
| 23 | 汇总自动计算 | `test_summary_auto_computed` | ✅ |
| 24 | 数据库未变 | `test_db_sha256_unchanged`、`test_db_unchanged_flag` | ✅ |
| 25 | 完整性检查 | `test_integrity_ok`、`test_fk_zero` | ✅ |
| 26 | 行数未变 | `test_index_daily_rows_unchanged` | ✅ |
| 27 | 全收益未写入库 | `test_no_tr_written_to_db` | ✅ |
| 28 | 门禁关闭 | `test_gates_all_closed` | ✅ |
| 29 | 报告齐全 | `test_reports_exist`、`test_audit_report_answers_eight_questions` | ✅ |
| 30 | 无恒真断言 | `test_no_vacuous_assertion` | ✅ |

---

## 3. 测试设计要点

### 3.1 不使用恒真断言

`test_no_vacuous_assertion` 通过字符串拼接（`"or " + "True"`）检测，
避免自伤。

### 3.2 SHA256 必须真实计算

```python
actual = hashlib.sha256(p.read_bytes()).hexdigest()
assert actual == r["tr_history_meta"]["sha256"]
assert actual == m_files[p.name]["sha256"]
```

**三方交叉核对**：文件实际哈希 == 审计 JSON == manifest。
**不得只检查字符串长度。**

### 3.3 分组隔离必须验证

```python
for c in list(BOND_INDEXES.values())[0]:
    assert c not in stock_codes, f"{c} 债券序列混入股票集合"
```

### 3.4 全收益不得入库必须验证

```python
n = conn.execute(
    "select count(*) from index_daily where index_code=?",
    (r["tr_candidate"],)).fetchone()[0]
assert n == 0
```

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **39 passed / 0 failed / 0 skipped** |
| 全量测试 | 2656 → **2695**（**+39**） |

> 全量测试数由上一阶段 2656 加上本轮新增 39 项得出；
> 实际执行结果见提交前的完整 `pytest -q` 输出。

---

## 5. 关键测试证据

### 5.1 九维汇总（真实输出）

```
stock_total_return: n=9  身份=9 映射=9 口径=9 接口=9 覆盖=9 质量=8 连续=1 时点=0 准入=0
bond_derivative:    n=2  身份=2 映射=0 口径=0 接口=2 覆盖=2 质量=2 连续=2 时点=0 准入=0
hk_derivative:      n=1  身份=1 映射=1 口径=1 接口=1 覆盖=0 质量=1 连续=0 时点=0 准入=0
```

### 5.2 可进入下一阶段独立数据层

```
11 / 12（H20930 除外）
```

### 5.3 正式准入

```
0 / 12
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 历史时点可用性 | 官方无历史快照，无法测试 |
| 2 | 港股日历核验 | 未取得港交所日历 |
| 3 | `H20184` 零值真实值 | 官方该日仅返回 0.0 |
| 4 | 早期比值=1 的官方解释 | 无官方说明 |
| 5 | 债券序列的正确判据 | 未取得债券口径文件 |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

