# 阶段3B-6.2.3.1.1.1 修正报告：原始归档完整性与审计计数修复

> **只修指纹、计数与完整性字段。不重建数据层，不重新下载，不改任何行情数值。**

**基线 HEAD**：`9cf46ab084e7ecc6e51e60572c770e698b83ad7c`

---

## 1. 问题 1：证据计数 36 vs 实际 34

### 1.1 根因

原导入脚本用累加 `upsert` 调用次数统计证据：

```python
evidence_count += 1   # 每次 upsert 调用都加 1
```

但 `399997` 有 **2 个候选**（`H20539`、`399997CNY02`），它们共用同一份对照文件
`csindex_ctrl_399997_from20040102.json`。`upsert_evidence()` 按 `relative_path`
去重（实际只留 1 行），但**计数器加了 2 次**。

**34 唯一文件 + 2 次重复计数 = 36。**

### 1.2 修复

改为按**数据库实际唯一文件数**统计：

```python
evidence_count = conn.execute(
    "select count(*) from tr_evidence_files").fetchone()[0]
```

### 1.3 结果

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| `tr_evidence_files` 行数 | 34 | **34** |
| `tr_ingest_runs.evidence_count` | **36** | **34** |
| manifest 文件数 | 34 | **34** |
| 审计 JSON `unique_files` | 34 | **34** |
| 导入报告 | 34 | **34** |

**四项完全一致。**

### 1.4 唯一证据构成

| 类型 | 数量 |
| --- | ---: |
| `basic_info`（官方基本信息） | 12 |
| `history`（原始历史行情） | 12 |
| `control`（原价格指数对照） | 10 |
| **合计** | **34** |

---

## 2. 问题 2：row_fingerprint 漏字段

### 2.1 修正前

```python
keys = ("tr_code", "trade_date", "open", "high", "low", "close",
        "volume", "amount", "change", "change_pct",
        "returned_code", "returned_name")     # 12 个字段
```

**缺 `cons_number` 与 `peg`**——这两个字段已存入 `tr_index_daily_raw`。

### 2.2 修正后

```python
FINGERPRINT_FIELDS = (
    "tr_code", "trade_date", "open", "high", "low", "close",
    "volume", "amount", "change", "change_pct",
    "cons_number", "peg",              # ← 新增
    "returned_code", "returned_name",
)                                       # 14 个字段
```

序列化规则固定为 `字段名=repr(值)` 逐行拼接，顺序固定。

### 2.3 全量重算

| 项 | 值 |
| --- | ---: |
| 重算行数 | **55,942** |
| 行情数值变化 | **无** |

---

## 3. 问题 3：逐行原始记录完整性

### 3.1 新增两列

| 列 | 用途 |
| --- | --- |
| `raw_record_json` | 原始记录的**规范化** JSON（固定字段顺序） |
| `raw_record_sha256` | 该规范化 JSON 的 SHA256 |

**重要区分**：

| 字段 | 含义 |
| --- | --- |
| `evidence_sha256` | **原始证据文件**的 SHA256（文件级） |
| `raw_record_sha256` | **单条记录规范化 JSON** 的 SHA256（行级） |

**两者用途不同，不得互相替代**（有测试断言二者不相等）。

### 3.2 规范化规则

```python
RAW_RECORD_FIELDS = (
    "tradeDate", "indexCode", "indexNameCnAll", "indexNameCn",
    "indexNameEnAll", "indexNameEn",
    "open", "high", "low", "close", "change", "changePct",
    "tradingVol", "tradingValue", "consNumber", "peg",
)
json.dumps(ordered, ensure_ascii=False, sort_keys=False,
           separators=(",", ":"))
```

**字段顺序固定、分隔符固定，同一记录永远产生同一 JSON。**

### 3.3 逐候选核对结果（全量，非抽样）

| 候选 | 原始行 | DB 行 | 匹配 | 不符 | 缺失 | 多余 | 完整 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `399997CNY02` | 4,349 | 4,349 | **4,349** | 0 | 0 | 0 | ✅ |
| `H00012` | 3,376 | 3,376 | **3,376** | 0 | 0 | 0 | ✅ |
| `H00016` | 5,563 | 5,563 | **5,563** | 0 | 0 | 0 | ✅ |
| `H00300` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | ✅ |
| `H00905` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | ✅ |
| `H00906` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | ✅ |
| `H00922` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | ✅ |
| `H00942` | 5,321 | 5,321 | **5,321** | 0 | 0 | 0 | ✅ |
| `H20184` | 5,320 | 5,320 | **5,320** | 0 | 0 | 0 | ✅ |
| `H20539` | 4,350 | 4,350 | **4,350** | 0 | 0 | 0 | ✅ |
| `H20930` | 3,003 | 3,003 | **3,003** | 0 | 0 | 0 | ✅ |
| `N00012` | 3,376 | 3,376 | **3,376** | 0 | 0 | 0 | ✅ |
| **合计** | **55,942** | **55,942** | **55,942** | **0** | **0** | **0** | **✅** |

**逐条比对字段**：`open` / `high` / `low` / `close` / `tradingVol` /
`tradingValue` / `change` / `changePct` / `consNumber` / `peg` /
`indexCode` / `indexNameCnAll`，以及 `raw_record_sha256`。

---

## 4. 数据安全核验

### 4.1 行情数值未变

| 项 | 结果 |
| --- | --- |
| 记录数（前 → 后） | 55,942 → **55,942** |
| `close` / `cons_number` / `peg` 全量快照比对 | **完全一致** |
| 异常行（12 合成 + 8 休市 + 1 零值） | **全部保留，标记不变** |

### 4.2 `index_daily` 未变

| 项 | 值 |
| --- | --- |
| 行数 | **50,603** |
| 内容指纹 | **`dbbd07c1339e99f27b0aeadb43eb56848776dbbad97f3fb7b9748bbd2f1e61f6`** |
| 与任务给定值 | **一致** |

### 4.3 证据文件未变

| 项 | 结果 |
| --- | --- |
| 证据文件数 | **34** |
| SHA256 复核 | **34 / 34 通过** |

### 4.4 状态未变

| 项 | 值 |
| --- | --- |
| 连续性分布 | 官方 0 / 代理 1 / 疑似 8 / 未知 3 |
| `real_history_start` | **全部 `unknown`** |
| 行质量状态含 `verified` | **否** |

### 4.5 数据库

| 项 | 值 |
| --- | --- |
| 备份 | `data/backups/fund_agent_before_3b6_2_3_1_1_1.db` |
| 实施前 SHA256 | `1c6327d9b7fb1b504fac55684fa62dc0984da13d51256747dfbb5fe6b54d2e62` |
| 实施后 SHA256 | `4fbab661ce645f8f5d740168a11675ecf6456917c29aad18a9b3aca416ca684d` |
| 变化原因 | 新增 2 列 + 重算 55,942 行指纹（预期） |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

---

## 5. 准入状态未升级

| 状态 | 值 |
| --- | ---: |
| `raw_data_layer_ingest_candidate` | **12** |
| `validated_series_candidate` | **0** |
| `proxy_qualified_series_candidate` | **0** |
| `formal_series_admitted` | **0** |

---

## 6. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

