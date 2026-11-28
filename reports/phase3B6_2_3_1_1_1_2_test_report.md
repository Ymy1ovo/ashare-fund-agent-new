# 阶段3B-6.2.3.1.1.1.2 测试报告

> **真实构造只有一列存在的数据库结构，真实执行 SQL。**

**本轮任务基线 HEAD**：`cdbdbf0284c8cf9f356fa4d298fd29f03169a014`
**本轮最终 HEAD**：见提交记录（**与基线不同，不得混淆**）

---

## 1. 专项测试文件

`tests/test_3b6_2_3_1_1_1_2_migration.py`

---

## 2. 覆盖任务要求 9 项

| # | 要求 | 对应测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 两列都不存在，UP 后两列均存在 | `test_up_from_none` | ✅ |
| 2 | 两列都存在，UP 重复无异常 | `test_up_idempotent_when_both_exist` | ✅ |
| 3 | 仅 `raw_record_json` 存在，UP 后两列均存在 | `test_up_when_only_json_exists` | ✅ |
| 4 | 仅 `raw_record_sha256` 存在，UP 后两列均存在 | `test_up_when_only_sha_exists` | ✅ |
| 5 | 两列都存在，DOWN 后两列均不存在 | `test_down_when_both_exist` | ✅ |
| 6 | 仅 `raw_record_json` 存在，DOWN 后两列均不存在 | `test_down_when_only_json_exists` | ✅ |
| 7 | 仅 `raw_record_sha256` 存在，DOWN 后两列均不存在 | `test_down_when_only_sha_exists` | ✅ |
| 8 | 两列都不存在，DOWN 重复无异常 | `test_down_idempotent_when_none` | ✅ |
| 9 | 不删表、不影响其他字段与数据行 | `test_no_table_drop_no_data_loss_up`、`test_no_table_drop_no_data_loss_down`（各 4 种状态参数化） | ✅ |

---

## 3. 测试设计要点

### 3.1 真实构造部分列状态

```python
def _add_only(c, col):
    """真实构造「只有一列存在」的结构。"""
    c.execute(f"alter table tr_index_daily_raw add column {col} text")
    c.commit()
```

**不是检查源码字符串，是真的建出只有一列的表。**

### 3.2 每种状态都验证不丢数据

```python
@pytest.mark.parametrize("pre", ["none", "json", "sha", "both"])
def test_no_table_drop_no_data_loss_up(tmp_path, pre):
    other_before = _cols(c) - {COL_JSON, COL_SHA}
    rows_before = _row_count(c)
    tr_layer.migrate_raw_record_columns(c)
    assert 表仍存在
    assert _cols(c) - {COL_JSON, COL_SHA} == other_before
    assert _row_count(c) == rows_before
```

### 3.3 DDL 必须仍来自 SQL 文件

```python
src = Path(tr_layer.__file__).read_text(encoding="utf-8")
assert "add column raw_record_json text" not in src.lower()   # 无硬编码
assert "RAW_RECORD_MIGRATION_UP" in src                        # 读文件
```

### 3.4 逐列筛选函数单独测试

```python
up_json = tr_layer._statements_for_column(UP_SQL, "raw_record_json", "ADD")
assert len(up_json) == 1 and "raw_record_json" in up_json[0]
assert "raw_record_sha256" not in up_json[0]     # 不串列
```

### 3.5 基线一致性测试

```python
def test_audit_baseline_head_correct(audit):
    assert audit["baseline_head"] == "cdbdbf0284c8cf9f356fa4d298fd29f03169a014"

def test_audit_baseline_not_earlier_phase(audit):
    assert audit["baseline_head"] != "9cf46ab084e7ecc6e51e60572c770e698b83ad7c"
```

---

## 4. 测试结果

| 项目 | 结果 |
| --- | --- |
| 专项测试（本轮新增） | **34 passed / 0 failed / 0 skipped** |
| 上一轮专项（28 项） | 全部通过 |
| 全量测试 | 2939 → **2973**（**+34**） |

---

## 5. 关键测试证据

### 5.1 八种部分状态（真实输出）

```
=== 场景1: 两列都不存在 -> UP ===
  前: ['close', 'tr_code', 'trade_date']
  added: ['raw_record_json', 'raw_record_sha256']

=== 场景2: 两列都存在 -> UP 重复 ===
  added: [] executed: False

=== 场景3: 仅 raw_record_json 存在 -> UP ===
  前: ['close', 'raw_record_json', 'tr_code', 'trade_date']
  added: ['raw_record_sha256']

=== 场景4: 仅 raw_record_sha256 存在 -> UP ===
  前: ['close', 'raw_record_sha256', 'tr_code', 'trade_date']
  added: ['raw_record_json']

=== 场景5: 两列都存在 -> DOWN ===
  dropped: ['raw_record_json', 'raw_record_sha256']
  数据行: 1

=== 场景6: 仅 raw_record_json 存在 -> DOWN ===
  dropped: ['raw_record_json']

=== 场景7: 仅 raw_record_sha256 存在 -> DOWN ===
  dropped: ['raw_record_sha256']

=== 场景8: 两列都不存在 -> DOWN 重复 ===
  dropped: [] executed: False
```

### 5.2 基线一致性

```
审计 JSON baseline_head: cdbdbf0284c8cf9f356fa4d298fd29f03169a014
与本轮任务基线一致（旧阶段基线已从全部报告中移除）
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

