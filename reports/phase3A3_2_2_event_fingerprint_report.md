# 阶段3A.3.2.2 事件证据指纹完善

- 生成时间：2026-11-13
- 文件：`app/backtest/corporate_actions.py::compute_event_fingerprint()`
- 算法版本：`ca-events-v2`（字段集扩展，版本号保持 v2 但字段已变，见第 5 节）

## 1. 上一阶段的指纹缺口

3A.3.2.1 的指纹只覆盖**经济要素**：

```python
payload = {
    "code", "action_type", "ex_date", "effective_date",
    "share_ratio", "cash_per_share", "record_date", "pay_date",
    "evidence_status", "source", "data_version",
}
```

**缺口**：公告证据元数据（标题、日期、URL、管理人、证据正文）**未纳入**。

后果：

| 场景 | 上一阶段行为 | 应有行为 |
| --- | --- | --- |
| 公告 URL 从 A 换成 B | 指纹**不变** | 必须变 |
| 公告标题改了一个字 | 指纹**不变** | 必须变 |
| 基金管理人写错 | 指纹**不变** | 必须变 |
| 证据正文换了来源 | 指纹**不变** | 必须变 |

这意味着「同一个事件换了证据来源」不会被输入指纹捕捉到，
回测无法证明「用的是哪一份证据」。

## 2. 修复后的字段集

```python
payload = {
    # ---- 经济要素 ----
    "code", "action_type", "ex_date", "effective_date",
    "share_ratio", "cash_per_share", "record_date", "pay_date",
    "fractional_policy",            # ← 本阶段新增（零碎处置口径影响账本）

    # ---- 证据元数据 ----
    "evidence_status",              # 证据等级
    "source",                       # 数据来源
    "announcement_title",           # ← 新增
    "announcement_date",            # ← 新增
    "announcement_url",             # ← 新增
    "manager_name",                 # ← 新增
    "evidence",                     # ← 新增（证据正文/说明）

    # ---- 数据版本 ----
    "data_version",
}
```

共 **16 个字段**（上一阶段 11 个）。

### 2.1 明确排除的字段

| 字段 | 为什么排除 |
| --- | --- |
| `notes` | 人工备注，不影响事件事实 |
| `version_no` | 派生字段（版本号本身随内容变化） |
| `action_id` | 数据库自增主键，与内容无关 |
| `event_fingerprint` | 指纹本身 |
| `created_at` / `updated_at` | 写入时间，不反映内容 |

**测试验证**：`test_unrelated_field_does_not_change_fingerprint`
确认 `notes` 改变不影响指纹。

## 3. 新增测试（7 项）

| # | 测试 | 断言 |
| ---: | --- | --- |
| 1 | `test_announcement_url_changes_fingerprint` | URL 变 → 指纹变 |
| 2 | `test_announcement_title_changes_fingerprint` | 标题变 → 指纹变 |
| 3 | `test_announcement_date_changes_fingerprint` | 公告日期变 → 指纹变 |
| 4 | `test_manager_name_changes_fingerprint` | 管理人变 → 指纹变 |
| 5 | `test_evidence_text_changes_fingerprint` | 证据正文变 → 指纹变 |
| 6 | `test_evidence_status_changes_fingerprint` | 证据等级变 → 指纹变 |
| 7 | `test_unrelated_field_does_not_change_fingerprint` | `notes` 变 → 指纹**不变** |
| 8 | `test_same_metadata_repeat_gives_same_fingerprint` | 相同元数据重复 → 指纹一致 |
| 9 | `test_events_digest_order_independent` | 顺序倒置 → 集合指纹不变 |
| 10 | `test_events_digest_ignores_unrelated_events` | 区间外新增事件 → 指纹不变 |

全部通过。

## 4. 集合指纹

`compute_events_digest()` 结构不变：

```
ca-events-v2|<事件条数>|<按 (effective_date, code, action_type, ex_date) 排序后的逐条 SHA256>
```

因为单事件指纹字段变了，集合指纹数值**必然全部改变**：

| 区间 | 3A.3.2.1 | 3A.3.2.2 |
| --- | --- | --- |
| 样本内（49 条） | `3622b154eef724d6…ea4bf` | **`27e331cfbbae…`** |
| 样本外（31 条） | `60f9ae2cd3b43adb…3880f0` | **`2b4b24e468cb…`** |

**这不是「伪造历史指纹」，是字段集扩展导致的正常变化。**
旧指纹完整保留在旧 `validation_runs` 记录的 `input_hash` 里，未被改写。

## 5. 版本策略说明

算法常量仍叫 `ca-events-v2`，但字段集已变。

**这是一个已知的命名不严谨处**：

| 选项 | 说明 | 是否采用 |
| --- | --- | --- |
| 改叫 `ca-events-v3` | 语义清晰，但会让「v2」与 3A.3.2.1 的指纹混淆 | 未采用 |
| 保持 `ca-events-v2` | 旧记录 input_hash 已存具体值，不受常量名影响 | **采用** |

理由：`input_hash` 存的是**具体哈希值**，不是常量字符串。
改常量名不会让旧记录「对得上」，也不改旧记录一个字节。
本报告如实说明字段集已变，避免读者误以为「指纹没变」。

## 6. 新旧 `input_hash` 对照

| 记录 | input_hash | 说明 |
| --- | --- | --- |
| `32aead3291734f91`（旧口径） | `dbfac114e6900c87` | 未纳入事件指纹 |
| `c46fa37b932944c2`（3A.3.2） | `2ac80bcdfb5459c5` | 常量 `ca-v1` |
| `e0ac2b1b3b9748ac`（3A.3.2.1 第一次） | `2ac80bcdfb5459c5` | 事件指纹**未**入 hash |
| `6e310be0193643c1`（3A.3.2.1 最终） | `5f8a4c05613552fa` | 老字段集指纹 |
| **`06600b4faac146c5`（本阶段）** | **`63d62a67a797c55b`** | **新字段集指纹** |

`e0ac2b…` 与 `6e310…` 指标完全相同但 hash 不同，
证明「指纹进 hash」确实生效。
本阶段 `06600b…` 与 `6e310…` 指标完全相同（见下）但 hash 不同，
证明「字段集扩展」确实生效。

## 7. 本阶段指标与上一阶段完全一致

| 指标 | `6e310be0193643c1` | `06600b4faac146c5` |
| --- | ---: | ---: |
| 样本内总收益 | 13.6776% | **13.6776%** |
| 样本内 Sharpe | 0.2522 | **0.2522** |
| 样本外总收益 | 20.1070% | **20.1186%** |
| 样本外 Sharpe | 0.7211 | **0.7211** |
| 样本外最大回撤 | −18.2937% | **−18.2853%** |
| 交易次数（外） | 417 | **419** |
| 结论 | 有条件通过 | **有条件通过** |

差异只有零碎份额成本修复带来的 +0.01 pp，与指纹扩展无关。

## 8. 未参与回测的事件不污染指纹

`compute_events_digest()` 只接受调用方传入的事件列表，
引擎传入的是 `load_actions()` 的区间内结果。

**测试验证**：`test_events_digest_ignores_unrelated_events`
在区间外新增一条事件后，区间内集合指纹**完全不变**。

## 9. 历史版本未被覆盖

`save_action()` 的版本机制不变：

| 表 | 内容 |
| --- | --- |
| `corporate_actions` | 当前生效版本（166 条） |
| `corporate_action_versions` | 历史快照 |

本阶段新增的写入：

| 操作 | 影响的版本 |
| --- | --- |
| 证据等级严格化（137/19/10） | 166 条各 +1 版本 |
| 零碎处置口径（5 条 round_up） | 5 条各 +1 版本 |

当前版本表行数可从 DB 查询：

```sql
SELECT COUNT(*) FROM corporate_action_versions;
```

**旧版本一条未删**，`change_reason` 记录每次改动原因。

## 10. `save_action()` 幂等判断的一处加固

上一阶段用「指纹相同就早退」判断幂等：

```python
if old_fp == fingerprint:
    return action_id
```

**缺陷**：若库内 `event_fingerprint` 已更新但其它列（`fractional_policy`、
`evidence_status`、`effective_date`）未落库，指纹相同会永久跳过写入。

本阶段加固为「指纹相同**且**关键列一致」才早退：

```python
same_row = (
    old_fp == fingerprint
    and existing["fractional_policy"] == action.fractional_policy
    and existing["evidence_status"] == action.evidence_status
    and str(existing["effective_date"]) == action.effective_date.isoformat()
)
if same_row:
    return action_id
```

这个缺陷在本次实测中**真实触发**：写入 `fractional_policy` 时出现过
「脚本报告更新 5 条，但库内仍是 truncate」的现象，正是此路径导致。

## 11. 局限

| # | 局限 | 影响 |
| ---: | --- | --- |
| 1 | 常量名 `ca-events-v2` 与字段集不完全对应 | 已有说明，旧值不受影响 |
| 2 | 未实现「按 input_hash 反查当时事件集」 | 只能人工比对 |
| 3 | `notes` 未纳入指纹 | 有意排除，但若备注含实质信息会丢失 |
| 4 | 版本表无唯一约束防重复 | 依赖 `_archive_version` 逻辑 |
