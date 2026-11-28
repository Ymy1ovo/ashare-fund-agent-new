# 阶段3B-6.2.3.1.1.1.2 修正报告：迁移部分状态幂等性与审计基线元数据

> **只修两个边界问题。不重新下载，不重建数据层，不改任何行情数据。**

**本轮任务基线 HEAD**：`cdbdbf0284c8cf9f356fa4d298fd29f03169a014`
**本轮最终 HEAD**：见文末「Git」一节（**与基线不同，不得混淆**）

---

## 1. 问题 1：UP 迁移不支持部分列已存在

### 1.1 缺陷

原 `migrate_raw_record_columns()` 虽先检查缺失列，但**执行时仍执行完整 UP SQL 文件**：

```python
missing = [c for c in ("raw_record_json", "raw_record_sha256")
           if c not in before]
if not missing:
    return {...}                    # 只有「两列都在」才跳过
for stmt in _split_sql(UP_SQL.read_text()):
    conn.execute(stmt)              # ← 执行**完整**文件
```

**失败场景**：

| 场景 | 结果 |
| --- | --- |
| 两列都在 | ✅ 跳过 |
| 两列都不在 | ✅ 成功 |
| **只有 `raw_record_json`** | ❌ 第一条 `ADD COLUMN raw_record_json` 报重复列 |
| **只有 `raw_record_sha256`** | ❌ 第一条 `ADD COLUMN raw_record_json` 会成功，但语义混乱 |

### 1.2 修正：逐列执行

```python
for col in ("raw_record_json", "raw_record_sha256"):
    if col in _raw_record_columns(conn):
        continue                        # 已存在 → 跳过
    stmts = _statements_for_column(UP_SQL, col, "ADD")
    for stmt in stmts:
        conn.execute(stmt)              # 只执行该列对应的 DDL
    added.append(col)
```

**DDL 仍来自 SQL 文件**——`_statements_for_column()` 从文件中筛选
`add column <col>` 语句，**没有改回 Python 硬编码**。

### 1.3 DOWN 同样逐列

```python
for col in ("raw_record_sha256", "raw_record_json"):
    if col not in _raw_record_columns(conn):
        continue                        # 不存在 → 跳过
    stmts = _statements_for_column(DOWN_SQL, col, "DROP")
    for stmt in stmts:
        conn.execute(stmt)
    dropped.append(col)
```

---

## 2. 八种部分状态验证

用**真实构造只有一列存在的数据库**测试（非检查源码）：

| # | 初始状态 | 操作 | 结果 |
| ---: | --- | --- | --- |
| 1 | 两列都不存在 | UP | 新增两列 ✅ |
| 2 | 两列都存在 | UP | `added=[]`，`executed=False` ✅ |
| 3 | **仅 `raw_record_json`** | UP | 只新增 `raw_record_sha256` ✅ |
| 4 | **仅 `raw_record_sha256`** | UP | 只新增 `raw_record_json` ✅ |
| 5 | 两列都存在 | DOWN | 删除两列 ✅ |
| 6 | **仅 `raw_record_json`** | DOWN | 只删该列 ✅ |
| 7 | **仅 `raw_record_sha256`** | DOWN | 只删该列 ✅ |
| 8 | 两列都不存在 | DOWN | `dropped=[]`，`executed=False` ✅ |

**全部 8 种场景均不删表、不丢数据、不动其他字段**（4×2 参数化测试验证）。

---

## 3. 问题 2：审计基线元数据不一致

### 3.1 缺陷

`scripts/fix_3b6_2_3_1_1_1.py` 中的 `baseline_head` 写的是：

```python
"baseline_head": "9cf46ab084e7ecc6e51e60572c770e698b83ad7c"   # ❌ 3B-6.2.3.1.1 的基线
```

但本轮（3B-6.2.3.1.1.1.1）的实际基线是 `cdbdbf0284c8cf9f356fa4d298fd29f03169a014`。

### 3.2 修正

| 文件 | 修正 |
| --- | --- |
| `scripts/fix_3b6_2_3_1_1_1.py` | `baseline_head` → `cdbdbf0284c8cf9f356fa4d298fd29f03169a014` |
| `reports/phase3B6_2_3_1_1_1_1_fix_report.md` | 标注为「本轮任务基线 HEAD」 |
| `reports/phase3B6_2_3_1_1_1_1_test_report.md` | 同上 |
| 审计 JSON | 重生成，新增 `final_head_note` 字段 |

### 3.3 基线与最终 HEAD 严格分开

```json
{
  "baseline_head": "cdbdbf0284c8cf9f356fa4d298fd29f03169a014",
  "final_head_note": "本轮最终 HEAD 见 fix_report；baseline_head 为本轮任务起点，两者不得混淆"
}
```

**`baseline_head` 只表示任务起点，不表示最终提交。**

---

## 4. 数据保护核验

| 项 | 要求 | 实际 | 结果 |
| --- | --- | --- | --- |
| `tr_index_daily_raw` 行数 | 55,942 | **55,942** | ✅ |
| `raw_record_json` / SHA 数据 | 不变 | **不变**（抽样真实复核通过） | ✅ |
| `index_daily` 行数 | 50,603 | **50,603** | ✅ |
| `index_daily` 内容指纹 | `dbbd07c1…e61f6` | **一致** | ✅ |
| 证据文件 SHA256 | 34 份不变 | **34 / 34 通过** | ✅ |
| `integrity_check` | ok | **ok** | ✅ |
| `foreign_key_check` | 0 | **0** | ✅ |

### 准入状态

| 状态 | 值 |
| --- | ---: |
| `raw_data_layer_ingest_candidate` | **12** |
| `validated_series_candidate` | **0** |
| `proxy_qualified_series_candidate` | **0** |
| `formal_series_admitted` | **0** |

### 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

---

## 5. 本轮未重跑 55,942 条回填

任务明确「不需要重新运行 55,942 条数据回填」。本轮：

- 未重新回填 `raw_record_json`
- 未重新计算 `row_fingerprint`
- 未重新下载任何数据

审计脚本仍会执行核验（只读），但数据本身未被改写。

---

## 6. Git

| 项 | 值 |
| --- | --- |
| 本轮任务基线 HEAD | `cdbdbf0284c8cf9f356fa4d298fd29f03169a014` |
| 本轮最终 HEAD | 见提交记录 |

**两者不得混淆。**

