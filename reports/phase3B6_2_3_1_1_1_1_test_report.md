# 阶段3B-6.2.3.1.1.1.1 测试报告

> **真实操作数据库、真实执行 SQL 迁移、真实调用业务函数。**

**本轮任务基线 HEAD**：`cdbdbf0284c8cf9f356fa4d298fd29f03169a014`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_1_1_1_verify.py`

---

## 2. 覆盖任务要求 12 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 改 JSON 不改 SHA → 检测失败 | `test_detect_json_tampered_sha_kept` | ✅ |
| 2 | 改 SHA → 检测失败 | `test_detect_sha_tampered` | ✅ |
| 3 | JSON 置 NULL → 检测失败 | `test_detect_json_null` | ✅ |
| 4 | SHA 置 NULL → 检测失败 | `test_detect_sha_null` | ✅ |
| 5 | 原始 JSON 字段变化 → 检测失败 | `test_detect_raw_json_field_changed`、`test_detect_field_changed` | ✅ |
| 6 | 完全一致时通过 | `test_passes_when_all_match` | ✅ |
| 7 | 55,942 条全量核验 | `test_full_55942_verified`、`test_per_candidate_reported` | ✅ |
| 8 | UP 可执行且幂等 | `test_up_adds_columns`、`test_up_idempotent` | ✅ |
| 9 | DOWN 可执行且幂等 | `test_down_drops_columns`、`test_down_idempotent` | ✅ |
| 10 | UP→DOWN→UP 生命周期 | `test_up_down_up_lifecycle` | ✅ |
| 11 | `index_daily` 隔离与指纹不变 | `test_index_daily_unchanged` | ✅ |
| 12 | 准入状态不变 | `test_admission_unchanged` | ✅ |

---

## 3. 测试设计要点

### 3.1 篡改检测用真实数据库副本

```python
shutil.copy2(ROOT / "data" / "fund_agent.db", db)
# 篡改 raw_record_json 但保留 SHA
c.execute("update tr_index_daily_raw set raw_record_json=? ...",
          ('{"tampered":1}', code, d))
r = tr_layer.verify_raw_records(c, EVID_TR)[code]
assert r["raw_record_json_mismatch"] >= 1
assert r["stored_json_sha_mismatch"] >= 1
assert r["complete"] is False
```

**在副本上测试，不碰正式库。**

### 3.2 原始 JSON 篡改检测

复制证据目录，修改其中一条记录的 `consNumber`：

```python
doc["data"][100]["consNumber"] = 999999.0
v = tr_layer.verify_raw_records(conn, ev)   # 指向被篡改的目录
assert v["H00300"]["field_mismatch"] >= 1
assert v["H00300"]["raw_record_json_mismatch"] >= 1
```

### 3.3 迁移生命周期真实 SQL

```python
tr_layer.migrate_raw_record_columns(c)      # UP
assert "raw_record_json" in _cols(c)
tr_layer.rollback_raw_record_columns(c)     # DOWN
assert "raw_record_json" not in _cols(c)
tr_layer.migrate_raw_record_columns(c)      # UP again
```

**UP/DOWN 执行的是真实 SQL 文件，不是 Python 硬编码 DDL。**

### 3.4 SQL 文件必须含真实 DDL

```python
assert "ALTER TABLE tr_index_daily_raw ADD COLUMN raw_record_json" in up
assert "DROP COLUMN raw_record_json" in down
assert "DROP TABLE" not in down.upper()   # 不得删表
```

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **28 passed / 0 failed / 0 skipped** |
| 全量测试 | 2911 → **2939**（**+28**） |

---

## 5. 关键测试证据

### 5.1 自校验（真实输出）

```
{
 "evidence_count_consistent": true,
 "fingerprint_covers_all_fields": true,
 "all_records_verified": true,
 "all_anomalies_zero": true,
 "no_missing_no_extra": true,
 "values_untouched": true,
 "index_daily_unchanged": true,
 "evidence_sha256_ok": true,
 "no_validated": true,
 "no_formal_admitted": true,
 "real_start_all_unknown": true
}
```

### 5.2 八类异常汇总

```
{
 "field_mismatch": 0,
 "raw_record_json_missing": 0,
 "raw_record_json_mismatch": 0,
 "raw_record_sha256_missing": 0,
 "raw_record_sha256_mismatch": 0,
 "stored_json_sha_mismatch": 0,
 "missing_in_db": 0,
 "extra_in_db": 0
}
```

### 5.3 迁移生命周期

```
初始列: ['close', 'tr_code', 'trade_date']
UP 1: ['raw_record_json', 'raw_record_sha256'] executed=True
UP 2 (幂等): [] executed=False
DOWN 1: ['raw_record_json', 'raw_record_sha256'] executed=True
DOWN 2 (幂等): [] executed=False
UP again: ['raw_record_json', 'raw_record_sha256'] executed=True
数据仍在: 1
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 官方指数发布日历 | 未取得 |
| 2 | 全收益候选自身对照实验 | 未下载 |
| 3 | 真实历史起点 | 12/12 unknown |
| 4 | 历史时点可用性 | 官方无历史快照 |

**原始归档完整 ≠ 序列已验证。**

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

