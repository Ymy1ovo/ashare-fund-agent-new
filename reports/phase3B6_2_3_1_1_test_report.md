# 阶段3B-6.2.3.1.1 测试报告

> **真实操作数据库与业务函数**，不使用文本断言。

**基线 HEAD**：`3aae887da4a82ba77481c0efdb2f32c11feef618`

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_1_tr_layer.py`

---

## 2. 覆盖任务要求 16 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 与 `index_daily` 完全隔离 | `test_tr_tables_all_prefixed`、`test_no_tr_data_in_index_daily`、`test_isolated_helper_true`、`test_index_daily_row_count_unchanged`、`test_ingest_run_proves_index_daily_untouched` | ✅ |
| 2 | 12 个候选注册信息完整 | `test_twelve_candidates_registered`、`test_candidate_fields_complete`、`test_base_date_not_publish_date`、`test_market_groups_separated`、`test_bond_basis_not_stock_total_return` | ✅ |
| 3 | 原始行情可追溯 | `test_raw_rows_traceable_to_evidence`、`test_raw_row_sha_matches_evidence` | ✅ |
| 4 | 原始文件 SHA256 校验正确 | `test_evidence_sha256_real` | ✅ |
| 5 | 重复导入不产生重复 | `test_reimport_no_duplicates`、`test_reimport_idempotent_on_copy` | ✅ |
| 6 | 导入失败可回滚 | `test_rollback_and_reinit`、`test_failed_import_rolls_back` | ✅ |
| 7 | 20040101 合成行保留并标记 | `test_synthetic_row_preserved_and_marked`、`test_synthetic_row_original_value_kept` | ✅ |
| 8 | 2018-06-18 疑似休市保留并标记 | `test_closed_placeholder_preserved_and_marked` | ✅ |
| 9 | H20184 零值保留并标记 | `test_h20184_zero_preserved_and_marked` | ✅ |
| 10 | 真实起点 unknown 不自动转已知 | `test_real_history_start_stays_unknown` | ✅ |
| 11 | 债券/港股日历不替换为 A 股 | `test_bond_hk_calendar_not_replaced` | ✅ |
| 12 | 代理连续性不提升为官方 | `test_proxy_not_promoted_to_official` | ✅ |
| 13 | 未验证序列不能被回测读取 | `test_no_formal_engine_can_read` | ✅ |
| 14 | 未验证序列不能进入排名 | `test_no_formal_ranking_use` | ✅ |
| 15 | 完整性与外键检查 | `test_integrity_ok`、`test_fk_check_ok` | ✅ |
| 16 | 迁移可重复且可回滚 | `test_migration_repeatable`、`test_rollback_and_reinit` | ✅ |

---

## 3. 测试设计要点

### 3.1 真实数据库操作

所有测试都通过 `tr_layer.get_tr_connection()` 真实读写 SQLite：

```python
rows = _rows(conn, "select tr_code, close, row_quality_status "
                   "from tr_index_daily_raw where trade_date='20040101'")
assert len(rows) == 12
```

**不检查 Markdown 或源码字符串。**

### 3.2 不写正式库

`tests/conftest.py` 有全局守卫：测试期间修改正式数据库会导致失败。

因此幂等测试在**数据库副本**上执行：

```python
shutil.copy2(src, dst)
env["TR_LAYER_DB_OVERRIDE"] = str(dst)
subprocess.run([...], env=env)
```

### 3.3 负向测试

| 测试 | 负向条件 |
| --- | --- |
| `test_no_tr_data_in_index_daily` | 全收益代码在 `index_daily` 必须 0 行 |
| `test_no_row_defaults_to_verified` | 质量状态集合不含 `verified`/`valid` |
| `test_no_cleaning_applied` | 每候选 DB 行数 == 原始 JSON 行数 |
| `test_real_history_start_stays_unknown` | 12/12 起点必须 `unknown` |
| `test_proxy_not_promoted_to_official` | 官方连续性计数必须 0 |
| `test_admission_states_not_upgraded` | validated/proxy/formal 必须 0 |

### 3.4 回滚测试

```python
tr_layer.init_tr_layer(c)      # 建表
tr_layer.init_tr_layer(c)      # 重复执行（幂等）
tr_layer.rollback_tr_layer(c)  # 回滚
assert 表已删除 and index_daily 仍在
```

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试 | **36 passed / 0 failed / 0 skipped** |
| 全量测试 | 2843 → **2879**（**+36**） |

---

## 5. 关键测试证据

### 5.1 自校验（真实输出）

```
{
 "twelve_candidates": true,
 "index_daily_unchanged": true,
 "isolated": true,
 "all_evidence_sha256_ok": true,
 "no_validated": true,
 "no_formal_admitted": true,
 "continuity_matches_audit": true,
 "no_verified_row_state": true
}
```

### 5.2 异常行标记

```
20040101 合成行: 12 行，全部 suspected_synthetic
2018-06-18 疑似休市: 8 行，全部 suspected_market_closed_placeholder
H20184 2013-06-28: close=0.0, invalid_value
```

### 5.3 质量分布

```
normal_unverified                      55921
suspected_synthetic                       12
suspected_market_closed_placeholder        8
invalid_value                              1
verified                                   0
```

---

## 6. 未覆盖的事项（如实说明）

| # | 事项 | 原因 |
| ---: | --- | --- |
| 1 | 官方指数发布日历 | 未取得 |
| 2 | 全收益候选自身对照实验 | 未下载 |
| 3 | 真实历史起点 | 12/12 unknown |
| 4 | 历史时点可用性 | 官方无历史快照 |
| 5 | 复合基准官方权重 | 前置阶段未解决 |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

