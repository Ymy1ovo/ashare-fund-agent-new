# 阶段3B-6.2.3.1.1.1 测试报告

> **真实操作数据库与业务函数**，不使用文本断言。

**基线 HEAD**：`9cf46ab084e7ecc6e51e60572c770e698b83ad7c`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_1_1_integrity.py`

---

## 2. 覆盖任务要求 12 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 证据计数 = 实际唯一证据文件数 | `test_evidence_count_matches_unique_files`、`test_no_duplicate_evidence_paths` | ✅ |
| 2 | 证据计数 = manifest | `test_evidence_count_matches_manifest` | ✅ |
| 3 | `cons_number` 改变会改变指纹 | `test_fingerprint_covers_cons_number` | ✅ |
| 4 | `peg` 改变会改变指纹 | `test_fingerprint_covers_peg` | ✅ |
| 5 | 其他原始字段改变会改变指纹 | `test_fingerprint_covers_every_field` | ✅ |
| 6 | 相同记录产生稳定指纹 | `test_fingerprint_stable` | ✅ |
| 7 | 12 个候选逐行核对 | `test_all_candidates_verified`、`test_cons_number_and_peg_verified` | ✅ |
| 8 | 55,942 条无遗漏无多余 | `test_total_rows_no_missing_no_extra` | ✅ |
| 9 | 原始文件与 DB 字段值一致 | `test_field_values_match_raw_file` | ✅ |
| 10 | 行指纹更新不修改数值 | `test_values_untouched`、`test_abnormal_rows_still_present` | ✅ |
| 11 | 重复执行不产生重复记录 | `test_rerun_no_duplicates`、`test_migration_idempotent` | ✅ |
| 12 | 完整性、外键、隔离检查 | `test_integrity_ok`、`test_fk_zero`、`test_isolation_ok` | ✅ |

---

## 3. 测试设计要点

### 3.1 指纹测试用真实函数

```python
a = tr_layer.row_fingerprint(_mk_rec())
b = tr_layer.row_fingerprint(_mk_rec(cons_number=301.0))
assert a != b
```

`test_fingerprint_covers_every_field` 遍历全部 14 个字段逐一改动，
断言每个字段变化都会改变指纹。

### 3.2 全量重算验证

```python
for r in rows:   # 55,942 行
    rec = {k: r[k] for k in tr_layer.FINGERPRINT_FIELDS}
    assert tr_layer.row_fingerprint(rec) == r["row_fingerprint"]
```

**不是抽样。**

### 3.3 逐行核对不依赖数据库自身

`test_field_values_match_raw_file` 调用 `verify_raw_records()`，
以**原始 JSON 文件**为唯一依据重新比对，不使用数据库生成的数据作对照。

### 3.4 区分两种 SHA

```python
assert r["evidence_sha256"] != r["raw_record_sha256"]
```

证明规范化记录 SHA 未替代原始文件 SHA。

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **32 passed / 0 failed / 0 skipped** |
| 全量测试 | 2879 → **2911**（**+32**） |

---

## 5. 关键测试证据

### 5.1 自校验（真实输出）

```
{
 "evidence_count_consistent": true,
 "fingerprint_covers_all_fields": true,
 "all_records_verified": true,
 "no_missing_no_extra": true,
 "values_untouched": true,
 "index_daily_unchanged": true,
 "evidence_sha256_ok": true,
 "no_validated": true,
 "no_formal_admitted": true,
 "real_start_all_unknown": true
}
```

### 5.2 逐行核对汇总

```
匹配 55942 / 不符 0 / 缺失 0 / 多余 0
```

### 5.3 指纹与计数

```
证据唯一数: 34（批次记录 34）
指纹更新: 55942 行
指纹字段数: 14（含 cons_number、peg）
```

---

## 6. 未覆盖的事项（如实说明）

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

