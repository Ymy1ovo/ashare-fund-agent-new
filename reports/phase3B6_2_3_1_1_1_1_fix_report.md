# 阶段3B-6.2.3.1.1.1.1 修正报告：原始 JSON 逐行核验闭环与迁移脚本规范化

> **只修核验逻辑与迁移规范。不重建数据层，不重新下载，不改任何行情数值。**

**基线 HEAD**：`cdbdbf0284c8cf9f356fa4d298fd29f03169a014`

---

## 1. 问题 1：verify_raw_records() 未核验数据库实际保存的 JSON

### 1.1 修正前的缺口

原实现：

| 步骤 | 是否执行 |
| --- | --- |
| 从原始 JSON 读记录 | ✅ |
| 逐项比对行情字段 | ✅ |
| 比对 `raw_record_sha256` 列与原始规范化 SHA | ✅ |
| **读取数据库 `raw_record_json` 内容并比对** | **❌ 缺失** |

**后果**：无法证明数据库实际保存的 JSON 内容与原始文件一致。
理论上可能出现「SHA 列正确但 JSON 内容被篡改」而不被发现。

### 1.2 修正后：四层核验

| 层 | 内容 |
| ---: | --- |
| 1 | **行情字段**逐项比对（`open`/`close`/`cons_number`/`peg`/…） |
| 2 | **数据库实际 `raw_record_json`** vs 原始 JSON 规范化结果（逐字符） |
| 3 | `raw_record_sha256` 列 vs **原始规范化 SHA** |
| 4 | `raw_record_sha256` 列 vs **数据库实际 JSON 自身的 SHA** |

### 1.3 八类异常分别统计

| 异常 | 含义 |
| --- | --- |
| `field_mismatch` | 行情字段不一致 |
| `raw_record_json_missing` | JSON 列为 NULL |
| `raw_record_json_mismatch` | JSON 内容与原始规范化结果不同 |
| `raw_record_sha256_missing` | SHA 列为 NULL |
| `raw_record_sha256_mismatch` | SHA 列 ≠ 原始规范化 SHA |
| `stored_json_sha_mismatch` | SHA 列 ≠ 数据库实际 JSON 的 SHA |
| `missing_in_db` | 原始有、DB 无 |
| `extra_in_db` | DB 有、原始无 |

**`complete = true` 要求八类全为 0 且匹配数等于原始行数。**

每种异常保留最多 **10 条**明细样本，避免报告膨胀。

---

## 2. 问题 2：迁移 SQL 文件只有注释

### 2.1 修正前

`migrations/phase3b6_2_3_1_1_1_raw_record.sql` 与 `_down.sql`
**只有说明性注释**，实际 DDL 硬编码在 Python 函数里。

### 2.2 修正后：真实 SQL

**UP 文件**：

```sql
ALTER TABLE tr_index_daily_raw ADD COLUMN raw_record_json TEXT;
ALTER TABLE tr_index_daily_raw ADD COLUMN raw_record_sha256 TEXT;
```

**DOWN 文件**：

```sql
ALTER TABLE tr_index_daily_raw DROP COLUMN raw_record_sha256;
ALTER TABLE tr_index_daily_raw DROP COLUMN raw_record_json;
```

### 2.3 Python 函数执行真实 SQL 并保持幂等

```python
def migrate_raw_record_columns(conn):
    before = _raw_record_columns(conn)
    missing = [c for c in ("raw_record_json", "raw_record_sha256")
               if c not in before]
    if not missing:
        return {"added": [], "executed": False}   # 已存在 → 不执行
    for stmt in _split_sql(UP_SQL.read_text()):
        conn.execute(stmt)
```

**已存在列时不执行 SQL；不存在列时不执行删除。**

### 2.4 迁移生命周期验证

| 步骤 | 结果 |
| --- | --- |
| UP 首次 | 新增 2 列，`executed=True` |
| UP 重复 | `added=[]`，`executed=False` |
| DOWN 首次 | 删除 2 列，`executed=True` |
| DOWN 重复 | `dropped=[]`，`executed=False` |
| UP→DOWN→UP | 正常，数据行数不变 |

**DOWN 只删这两列，不删表、不动其他字段。**

---

## 3. 全量核验结果（55,942 条）

### 3.1 逐候选明细

| 候选 | 原始 | DB | 匹配 | 字段 | JSON缺 | JSON异 | SHA缺 | SHA异 | 自身SHA | DB缺 | 多余 | 完整 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `399997CNY02` | 4,349 | 4,349 | **4,349** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00012` | 3,376 | 3,376 | **3,376** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00016` | 5,563 | 5,563 | **5,563** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00300` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00905` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00906` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00922` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H00942` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H20184` | 5,320 | 5,320 | **5,320** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H20539` | 4,350 | 4,350 | **4,350** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `H20930` | 3,003 | 3,003 | **3,003** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| `N00012` | 3,376 | 3,376 | **3,376** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | ✅ |
| **合计** | **55,942** | **55,942** | **55,942** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **12/12** |

### 3.2 四层核验汇总

| 层 | 结果 |
| --- | --- |
| 原始记录总数 | **55,942** |
| DB 记录总数 | **55,942** |
| **`raw_record_json` 逐行一致** | **55,942 / 55,942** |
| **`raw_record_sha256` 逐行一致** | **55,942 / 55,942** |
| **DB JSON 自身 SHA 一致** | **55,942 / 55,942** |
| 行情字段不一致 | **0** |
| DB 缺失记录 | **0** |
| DB 多余记录 | **0** |

**这四层是不同层次的核验，不得合并成一个笼统的「完整性通过」。**

---

## 4. 数据安全核验

| 项 | 要求 | 实际 | 结果 |
| --- | --- | --- | --- |
| `tr_index_daily_raw` 行数 | 55,942 | **55,942** | ✅ |
| 原始行情字段 | 不变 | **不变** | ✅ |
| `row_fingerprint` 字段数 | 14 | **14** | ✅ |
| 证据文件 SHA256 | 34 份不变 | **34 / 34 通过** | ✅ |
| `tr_evidence_files` | 34 | **34** | ✅ |
| `tr_ingest_runs.evidence_count` | 34 | **34** | ✅ |
| `index_daily` 行数 | 50,603 | **50,603** | ✅ |
| `index_daily` 内容指纹 | `dbbd07c1…e61f6` | **`dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6`** | ✅ |
| 12 条疑似合成行 | 保留 | **12** | ✅ |
| 8 条疑似休市占位 | 保留 | **8** | ✅ |
| `H20184` 零值异常 | 保留 | **`close=0.0`** | ✅ |
| 连续性分布 | 0/1/8/3 | **0/1/8/3** | ✅ |
| `real_history_start` | 全 unknown | **全 `unknown`** | ✅ |
| `integrity_check` | ok | **ok** | ✅ |
| `foreign_key_check` | 0 | **0** | ✅ |

---

## 5. 准入与门禁

| 状态 | 值 |
| --- | ---: |
| `raw_data_layer_ingest_candidate` | **12** |
| `validated_series_candidate` | **0** |
| `proxy_qualified_series_candidate` | **0** |
| `formal_series_admitted` | **0** |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

**原始归档完整不等于序列已验证。**

