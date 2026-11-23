# 阶段3B-5.3.2 事务连接外键约束与指纹序列化最终修正

- 基线 HEAD：`35f4d3c71cc09c395d11fa23712b65bbad7acd48`
- 执行日期：2026-11-23
- 修改模块：`app/fund/ingest_user_funds/_impl.py`
- 新增测试：`tests/test_3b5_3_2_fk_serialization.py`

> **本轮只处理两个小问题，不重构。**

---

## 0. 结论先行

| 问题 | 修复前 | 修复后 |
| --- | --- | --- |
| P0 外键约束 | 事务连接未启用 `foreign_keys`，孤儿份额可写入 | **`PRAGMA foreign_keys=ON` + 读回断言为 1，失败立即报错** |
| P1 序列化歧义 | `\|` 拼接，值内含分隔符会撞库 | **JSON 数组 + 类型标签，无歧义** |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

---

## 1. P0：启用事务连接的外键约束

### 1.1 问题

`_open_tx()` 用独立 `sqlite3.connect` 建事务连接，但**没有**执行
`PRAGMA foreign_keys=ON`。SQLite 默认关闭外键，
于是「插入不存在的 fund_id 对应份额」不会报错，引用完整性形同虚设。

### 1.2 修复

```python
conn.execute("PRAGMA temp_store = MEMORY")
conn.execute("PRAGMA busy_timeout = 5000")

# ① 先开外键（必须在 BEGIN IMMEDIATE 之前，事务内设置无效）
conn.execute("PRAGMA foreign_keys = ON")
# ② 读回确认，PRAGMA 可能被静默忽略
enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
if int(enabled) != 1:
    conn.close()
    raise RuntimeError(
        "接入事务连接未能启用外键约束（PRAGMA foreign_keys 返回 "
        f"{enabled!r}）；拒绝继续接入")

# ③ 再开事务
conn.execute("BEGIN IMMEDIATE")
```

**只改本连接的 PRAGMA**，不触碰 `app/database/db.py` 的全局连接，
其他模块行为完全不变。

### 1.3 验证

| 测试 | 断言 |
| --- | --- |
| `test_tx_connection_enables_foreign_keys` | 事务连接 `PRAGMA foreign_keys == 1` |
| `test_tx_connection_fk_on_before_begin` | 已 `in_transaction=True` 且外键仍为 1 → 说明是 BEGIN 前设的 |
| `test_global_connection_unaffected` | 全局 `get_connection()` 仍为默认 0，未被改动 |
| `test_insert_orphan_share_raises_integrity_error` | 插入 `fund_id=999999` 的份额 → **`sqlite3.IntegrityError`** |
| `test_orphan_insert_rolls_back_whole_transaction` | 外键失败后整只基金回滚，三张表行数归零 |
| `test_normal_ingest_still_works_with_fk_on` | 开外键后正常接入仍成功，`foreign_key_check` 为空 |

---

## 2. P1：消除内容指纹序列化歧义

### 2.1 问题

旧实现用 `"|".join(_stable_value(v) for v in row)` 拼一行。
若字段值本身含 `|`，两行不同数据会拼成同一字节串：

```
("a|b", "c")  →  str:a|b|str:c
("a", "b|c")  →  str:a|str:b|c   ← 边界不同但易撞
```

### 2.2 修复：JSON 数组 + 类型标签

```python
def _stable_value(v):
    if v is None:          return ("null", None)
    if isinstance(v, bool): return ("bool", int(v))
    if isinstance(v, int):  return ("int", v)
    if isinstance(v, float):
        if math.isnan(v):  return ("float", "nan")
        if math.isinf(v):  return ("float", "inf" or "-inf")
        return ("float", repr(v))
    if isinstance(v, bytes): return ("bytes", v.hex())
    return ("str", str(v))

def _encode_row(values) -> bytes:
    return json.dumps([list(_stable_value(v)) for v in values],
                      ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
```

由 **JSON 负责转义**引号、反斜杠、换行、竖线与方括号，
不再依赖任何分隔符，边界天然无歧义。

| 值 | 序列化片段 |
| --- | --- |
| `None` | `["null",null]` |
| `True` | `["bool",1]` |
| `1` | `["int",1]` |
| `1.0` | `["float","1.0"]` |
| `"1"` | `["str","1"]` |
| `b"1"` | `["bytes","31"]` |

nan / inf 走字符串承载，保证 JSON 合法（标准 JSON 不允许 NaN/Infinity 字面量）。

### 2.3 验证

| 测试 | 断言 |
| --- | --- |
| `test_separator_not_ambiguous` | `("a\|b","c")` 与 `("a","b\|c")` **指纹不同** |
| `test_separator_variants_all_distinct` | 5 种竖线变体产生 **5 个不同序列化** |
| `test_bracket_and_quote_not_ambiguous` | 方括号/引号字符不撞库 |
| `test_json_encoding_is_valid_json` | 编码结果可被 `json.loads` 还原 |
| `test_type_tags_preserved` | NULL/int/float/str/bytes 类型可区分 |
| `test_serialization_deterministic` | 同数据重复计算一致 |
| `test_nan_inf_serializable` | nan/inf 不破坏编码 |

**保留**原有能力：

| 测试 | 断言 |
| --- | --- |
| `test_fingerprint_changes_on_same_length_edit` | 同长度修改指纹变化 |
| `test_fingerprint_changes_row_count_unchanged` | 行数不变只改一条指纹变化 |
| `test_fingerprint_unchanged_by_recompute` | 重复计算一致 |

---

## 3. 正式数据库只读验证

**不重新采集、不重新写入、只做只读检查。**

| 检查 | 结果 |
| --- | --- |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0 违规** |
| 清盘本体 | **41**（不变） |
| 生命周期事件 | **49**（不变） |
| 原 12 份额 | **12/12** |
| 原 9 本体 | **9** |
| 本轮 5 份额 | **5/5** |
| ETF 行情指纹 | `d54727c0…`（不变） |

### 内容指纹

| 时点 | SHA256（新序列化算法） |
| --- | --- |
| 当前正式库 | `f71c36f9f1a5d73f9f0b1f930b6c2dfaff58cb08f985d0828feb2e4288cd635b` |
| 备份库（3B-5.3.1 时点） | `f71c36f9f1a5d73f9f0b1f930b6c2dfaff58cb08f985d0828feb2e4288cd635b` |

**完全一致** → 本轮改动未触碰任何正式数据。

> 注：序列化算法从 `\|` 拼接改为 JSON 数组后，指纹值本身会变
>（3B-5.3.1 记录的 `0c867be4…` → 本轮 `f71c36f9…`），
> 但**同一算法下正式库与备份库的指纹完全一致**，
> 说明数据内容未变。

| 表 | 行数 |
| --- | ---: |
| `fund_master` | 53 |
| `fund_share_classes` | 80 |
| `fund_nav_daily` | 47718 |
| `fund_dividends` | 44 |
| `fund_manager_history` | 21 |
| `fund_aum_history` | 683 |
| `fund_fee_rules` | 90 |
| `fund_subscription_status` | 12 |
| `fund_lifecycle_events` | 49 |
| `fund_data_quality` | 31 |

---

## 4. 测试结果（实际执行）

| 项 | 结果 |
| --- | --- |
| 新增专项 `test_3b5_3_2_fk_serialization.py` | **17 passed** |
| 3B-5.3.1 专项回归 | **20 passed** |
| 3B-5.3 原专项回归 | **27 passed** |
| 3B-5.1 / 5.2 回归 | **135 passed** |
| **全量** | **1482 passed / 0 failed / 381.59 秒** |

1482 = 3B-5.3.1 的 1465 + 本轮 17。

---

## 5. 静态检查 vs 实际执行

| 项 | 性质 |
| --- | --- |
| `ast.parse` 语法检查 | **静态** |
| PRAGMA 顺序审阅 | **静态** |
| 17 项新增测试 | **实际执行** |
| 20 + 27 + 135 项回归 | **实际执行** |
| 1482 项全量 | **实际执行** |
| 正式库指纹比对 / integrity / fk | **实际执行** |

---

## 6. 边界遵守

| 禁止项 | 状态 |
| --- | --- |
| 修改 Schema | ❌ 未做 |
| 改全局连接行为 | ❌ 未做（全局仍为默认 OFF，有测试断言） |
| 重新采集基金 | ❌ 未做 |
| 重新写入正式库 | ❌ 未做（指纹与备份一致） |
| 重构 | ❌ 未做（只改 `_open_tx` 与序列化两处） |
| 开放回测/排名 | ❌ 未做 |

---

## 7. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
