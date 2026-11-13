# 阶段3A.3.2.1 输入指纹与事件版本管理

- 生成时间：2026-11-13
- 目标：让「同一策略 + 同一数据 + 同一事件」必然得到同一输入指纹，反之必然不同

## 1. 上一阶段的缺陷

3A.3.2 的 `_input_hash()` 只加了一个**固定字符串** `corporate_action_version='ca-v1'`：

```python
payload = {
    ...
    "corporate_action_version": "ca-v1",   # 常量，永远不变
}
```

后果：

| 场景 | 是否改变 input_hash | 应该 |
| --- | :---: | :---: |
| 改一条事件的拆分比例 | ❌ 不变 | ✅ 应变 |
| 改分红金额 | ❌ 不变 | ✅ 应变 |
| 把某条事件从 confirmed 降级为 unverified | ❌ 不变 | ✅ 应变 |
| 删除一条事件 | ❌ 不变 | ✅ 应变 |

**版本号是口径标记，不是数据内容标记。** 只加版本号无法保证可复现。

## 2. 两级指纹

### 2.1 单事件指纹 `compute_event_fingerprint(action)`

对一条事件的全部关键字段做规范序列化后 SHA256：

```python
payload = {
    "code": "511030",
    "action_type": "split",
    "ex_date": "2021-01-08",
    "effective_date": "2021-01-11",
    "share_ratio": 10.0,
    "cash_per_share": None,
    "record_date": None,
    "pay_date": None,
    "evidence_status": "official_confirmed",
    "source": "https://...",
    "data_version": "ca-v1",
}
text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

覆盖任务书要求的全部 11 个字段。`sort_keys=True` + `separators=(",", ":")`
保证序列化结果唯一。

浮点处理：`round(float(x), 10)`，避免 `0.1+0.2` 这类表示误差造成伪差异。

### 2.2 事件集合指纹 `compute_events_digest(actions)`

```python
ordered = sorted(actions, key=lambda a: (a.effective_date, a.code, a.action_type, a.ex_date))
digest = sha256(b"ca-events-v2|<count>|")
for action in ordered:
    digest.update(compute_event_fingerprint(action).encode())
    digest.update(b"\n")
```

三个要点：

1. **稳定顺序**：多级排序键，同日同代码同类型再按 `ex_date`
2. **包含条数**：`ca-events-v2|N|` 前缀，防止「空集合」与「单事件」撞哈希
3. **逐条哈希再聚合**：不是把所有字段拼成一个大串，避免字段拼接歧义

## 3. 接入 `input_hash`

### 3.1 回测层

```python
actions_digest = ca.compute_events_digest(actions)   # 只含本次参与的事件
input_hash = _input_hash(
    ..., corporate_action_version="ca-v1",
    corporate_action_digest=actions_digest,
)
```

### 3.2 验证层

`app/validation/runner.py::_input_hash()` 同步纳入：

```python
payload = {
    "config": ..., "codes": ..., "data": fingerprint,
    "fingerprint_version": ...,
    "corporate_action_version": "ca-v1",
    "corporate_action_digest": events_digest,
}
```

`_events_digest_for(config, codes)` 预计算区间内**可应用**事件的指纹。

## 4. 七条要求的落实

| # | 要求 | 实现 | 验证 |
| ---: | --- | --- | --- |
| 1 | 对实际参与事件生成确定性 SHA256 | `compute_events_digest` | `test_events_digest_only_covers_given_events` |
| 2 | 哈希覆盖 11 个字段 | `compute_event_fingerprint` | `test_event_fingerprint_deterministic` |
| 3 | 稳定顺序排序 | 四元组排序键 | 同上 |
| 4 | 加入 `input_hash` | 回测层 + 验证层 | `test_input_hash_changes_with_event_content` |
| 5 | 版本号不变但内容变化 → 哈希变化 | 内容哈希独立于版本号 | 同上 |
| 6 | 同一事件同一数据重复运行 → 同指纹 | 纯函数，无随机源 | `test_events_digest_only_covers_given_events` 末尾断言 |
| 7 | 未参与事件不污染指纹 | `load_actions` 已按区间 + codes 过滤 | `test_events_digest_only_covers_given_events` |

## 5. 实测指纹

同一份事件数据、两次独立重放：

| 运行 | 事件集 | 事件指纹 |
| --- | --- | --- |
| 样本外（ca=True，41 只池） | 31 条 | `60f9ae2cd3b43adb7d2f6943d1ab1691c3d4b2da8fd90ea68c6ed2815d3880f0` |
| 样本内（ca=True，41 只池） | 49 条 | `3622b154eef724d664d96df548bfa6473f88ee1a4ffbf422eed34ebb519ea4bf` |
| 任意 run（ca=False） | 0 条 | `2dc9ec3938…8e74f2`（固定值） |

**样本外 MA250 与 B&H 得到完全相同的指纹**：两者加载的事件集相同
（区间 + 41 只池），事件指纹只描述「用了哪些事件」，不描述「怎么用」。

验证层：

| 记录 | 事件指纹 | input_hash |
| --- | --- | --- |
| `32aead3291734f91`（旧口径） | — | `dbfac114e6900c87` |
| `c46fa37b932944c2`（3A.3.2） | 无事件指纹 | `2ac80bcdfb5459c5` |
| `6e310be0193643c1`（本阶段） | 已纳入 | `5f8a4c05613552fa` |

**关键点**：`e0ac2b1b3b9748ac` 与 `6e310be0193643c1` 的 `input_hash`
不同（`2ac80b…` vs `5f8a4c…`），但数值结果完全相同——
这正是「哈希纳入事件指纹」生效的证据。

## 6. 事件版本管理

### 6.1 上一阶段的缺陷

3A.3.2 的 `save_action()` 用 `UPDATE` 覆盖已有事件：

```sql
UPDATE corporate_actions SET share_ratio=?, evidence_status=?, ... WHERE action_id=?
```

这与报告声称的「历史版本保留」矛盾——**旧内容被静默覆盖，无法追溯**。

### 6.2 本阶段的版本化保存

```
corporate_actions          当前生效版本（每个事件一行）
corporate_action_versions  历史版本快照（每次修改一行）
```

`save_action()` 新逻辑：

```python
fingerprint = compute_event_fingerprint(action)
if existing.event_fingerprint == fingerprint:
    return action_id                      # 内容没变 → 幂等，不写库
if existing:
    _archive_version(...)                 # 先把旧版本存进版本表（只存一次）
    new_version = old_version + 1
    UPDATE corporate_actions SET ..., version_no=new_version,
                                 event_fingerprint=fingerprint
    _write_version(key, new_version, ..., reason)
```

### 6.3 版本表结构

```sql
corporate_action_versions (
    version_id, action_key, version_no,
    code, action_type, ex_date, effective_date,
    share_ratio, cash_per_share, record_date, pay_date,
    source, evidence_status, data_version,
    change_reason,        -- 修改原因
    snapshot_json,        -- 完整快照
    created_at,
    UNIQUE(action_key, version_no)
)
```

### 6.4 实测

本阶段把 166 条事件的证据等级从 `confirmed` 改写为三档，
每条都产生了一次新版本：

| 项 | 数量 |
| --- | ---: |
| `corporate_actions` 当前事件 | 166 |
| `corporate_action_versions` 历史版本 | **338** |
| 平均版本数 | 2.04 |
| `version_no` 分布 | 全部为 2 |

version 1 = 3A.3.2 首次写入（`change_reason='首次写入'`）
version 2 = 本阶段证据等级回写（`change_reason='证据等级回写：xxx'`）

**旧版本完整保留在版本表中，可随时还原。**

### 6.5 查询历史版本

```python
from app.backtest.corporate_actions import event_key, event_versions
key = event_key(action)          # "511030|split|2021-01-08"
for v in event_versions(key):
    print(v["version_no"], v["change_reason"], v["evidence_status"], v["created_at"])
```

## 7. 版本与可追溯

| 问题 | 回答 |
| --- | --- |
| 这次回测用的是哪些事件？ | `corporate_action_applications` 按 `run_id` 查询 |
| 当时的输入指纹是什么？ | `backtest_runs.input_hash` / `validation_runs.input_hash` |
| 那些事件的当时内容是什么？ | `input_hash` 反查 + `corporate_action_versions` 快照 |
| 事件被改过几次？改了为什么？ | `corporate_action_versions.change_reason` |

## 8. 未完成项

| # | 项 | 原因 |
| ---: | --- | --- |
| 1 | 没有「按 input_hash 自动还原事件集」的查询接口 | 需 `input_hash` 与 `version_no` 建立映射表，本阶段未做 |
| 2 | 历史 run 的事件指纹无法回填 | 旧记录生成时未记录，只能标记为 legacy |
| 3 | 版本表没有压缩/归档机制 | 当前 338 行，规模可接受 |

## 9. 复现验证

```bash
# 事件指纹确定性
python -c "
import sys; sys.path.insert(0,'.')
from app.backtest.corporate_actions import load_actions, compute_events_digest
a = load_actions(start='2025-01-02', end='2026-11-09')
print(compute_events_digest([x for x in a if x.is_confirmed]))
"

# 版本历史
python -c "
import sys; sys.path.insert(0,'.')
from app.backtest.corporate_actions import event_versions
print(event_versions('510300|cash_distribution|2021-01-18'))
"
```
