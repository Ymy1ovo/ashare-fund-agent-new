# 阶段3A.3.2.3.1 源记录与重放记录对应关系设计

- 生成时间：2026-11-14
- 基线 HEAD：`f99c6ea379b297ff1bf141823e88f4413451ee5b`

## 1. 设计目标

1. 源记录**永不修改**（不 UPDATE、不 DELETE、不回填字段）
2. 每次重放生成**新** `run_id` / `validation_id`
3. 源→重放的对应关系可查询、可审计、可断点恢复
4. 参数忠实性可验证，无法验证时拒绝执行
5. 非正式口径的结果不得登记为成功

## 2. 新增表 `replay_attempts`

只新增一张表，不改任何历史表。

```sql
CREATE TABLE IF NOT EXISTS replay_attempts (
    attempt_id                TEXT PRIMARY KEY,
    record_kind               TEXT NOT NULL,      -- backtest / validation
    source_record_id          TEXT NOT NULL,
    replay_record_id          TEXT,
    source_input_hash         TEXT,
    replay_input_hash         TEXT,
    source_accounting_version TEXT,
    replay_accounting_version TEXT,
    source_config_hash        TEXT,               -- 仅 validation
    replay_params_json        TEXT,               -- 实际使用的参数快照
    status                    TEXT NOT NULL,      -- running / success / failed / skipped
    reason                    TEXT,
    started_at                TEXT NOT NULL,
    finished_at               TEXT,
    replay_timestamp          TEXT
);
CREATE INDEX idx_replay_source ON replay_attempts(record_kind, source_record_id);
CREATE INDEX idx_replay_status ON replay_attempts(status);
```

### 2.1 字段与任务要求的对应

| 任务书要求 | 字段 |
| --- | --- |
| `source_record_id` | `source_record_id` |
| `replay_record_id` | `replay_record_id` |
| `source_input_hash` | `source_input_hash` |
| `replay_input_hash` | `replay_input_hash` |
| `source_accounting_version` | `source_accounting_version` |
| `replay_accounting_version` | `replay_accounting_version` |
| `replay_timestamp` | `replay_timestamp` |
| `replay_status` | `status` |

额外增加：`attempt_id`（一次尝试的唯一标识，支持强制重跑时保留多次尝试）、
`replay_params_json`（当次实际使用的参数，便于事后核对）、
`reason`（失败原因）、`source_config_hash`（验证记录用）。

### 2.2 为什么用独立表而不是给历史表加列

给 `backtest_runs` / `validation_runs` 加 `source_record_id` 列意味着
**UPDATE 历史行**，违反「不修改历史记录」。独立表只追加，天然满足约束。

## 3. 状态机

```
         start_attempt()
              │
              ▼
         [running]
              │
      ┌───────┼────────┬─────────┐
      ▼       ▼        ▼         ▼
  [success] [failed] [skipped]  (崩溃→保持 running)
```

- `skipped`：已有成功重放且未指定 `--force`，**不写新 attempt 行**
- `failed`：参数不可证明 / 回测抛错 / 结果非正式口径
- `running`：只在实际执行期间存在；进程崩溃后该行保留，
  下次运行不会把它当成成功（`find_success` 只认 `success`）

## 4. 幂等与断点恢复

| 场景 | 行为 |
| --- | --- |
| 重复执行同一源记录 | `find_success()` 命中 → 返回 `skipped`，不创建新回测记录 |
| 指定 `--force` | 跳过幂等检查，创建新记录；旧 attempt 行保留 |
| 单条失败 | 记 `failed` + `reason`，不影响同批其他记录 |
| 中断后恢复 | 已 `success` 的下次自动跳过；未执行的下次照常执行 |
| 历史记录 | 从不 UPDATE / DELETE，幂等靠「跳过」而非「改历史」 |

## 5. 参数忠实性

### 5.1 backtest：直接从 `config_json` 读

`config_json` 结构完整（13~14 个键），包含成本、执行价、延期、
容忍带、资金等全部字段。唯一缺的是**策略参数**：

| 策略 | 必需参数 | 落库情况 |
| --- | --- | --- |
| `ma_trend` | `ma_window` | `strategy_params` 恒为 `{}`，**缺失** |
| `buy_and_hold` | 无（等权） | 不需要 |

缺失时 `build_backtest_config()` 抛 `ReplayError`，不填默认值。

### 5.2 validation：`config_hash` 反证

`validation_runs` 只有区间、池、网格四类列，其余参数全在 `config_hash` 里。
反证流程：

```
for 字段集 in (current 28 字段, historical 26 字段):
  for pool_mode in (all, representative):
    for 日期候选 in (存储值, 该月 1 日) 的笛卡尔积:
      payload = 默认值 + 存储列 + 候选
      if sha256(payload)[:16] == config_hash:
          return 参数（已证明）
return None（不可证明）
```

命中即证明**全部**参数（含默认值那批）。未命中就是不可证明，
不允许「用当前默认值重建」——那是猜测。

## 6. 非正式口径防护

重放执行时强制：

```python
config = BacktestConfig(..., apply_corporate_actions=True)
...
if result.accounting_basis != "formal_receivable" or not result.formal_valuation:
    raise ReplayError("重放结果不是正式口径")
```

验证重放还要检查落库后的 `accounting_version == 'ca-v2-receivable'`。

`scripts/replay_3a3_2.py --legacy-comparison` 保留的旧对照片段虽然会跑
`apply_corporate_actions=False`，但那是**内存回测、不落库**，
不会产生任何正式记录。

## 7. 新记录的口径标记

`save_result()` 只写 `summary_json`，不写 `backtest_runs.accounting_version` 列。
若不补标记，新记录会被盘点判成 `unknown_legacy`（本轮实测踩到过）。

修复：重放成功后调 `_stamp_replay_record()`，

```python
UPDATE backtest_runs SET accounting_version='ca-v2-receivable', evidence_version=?
WHERE run_id=?    -- 只写刚创建的 run_id
```

## 8. 盘点归类与重放的闭环

```
audit_replay_history.py
  ├─ backtest_manifest()   → 读 backtest_runs + config_json
  └─ validation_manifest() → 读 validation_runs + config_hash 反证
        ↓
    分类（current_formal / replayed / legacy / unknown_legacy / non_replayable）
        ↓
    legacy 清单 → replay_3a3_2.py --pending / replay_validation_3a3_2.py --pending
        ↓
    写 replay_attempts → 下次盘点自动变 replayed
```

## 9. 安全护栏

| 要求 | 实现 |
| --- | --- |
| 重放前备份 | 本轮已生成 `data/backups/fund_agent_post_3a3_2_3_1_20261114.db` |
| 行情指纹 | 重放前后各算一次，不一致则退出码 1 |
| `integrity_check` | 每轮回归都跑 |
| 不改历史 | 全部 SQL 只有 INSERT / 针对新 run_id 的 UPDATE |
| 正式口径 | `apply_corporate_actions=True` 硬编码，结果非正式即失败 |
| 禁止关闭公司行为 | 源记录即便曾关闭，重放也强制打开 |

## 10. 已知限制

1. `backtest_runs.accounting_version` 是权威标记，但重放记录需要额外 UPDATE
   才能带上；这是对**新记录**的写，不涉及历史行
2. `replay_attempts` 里 `running` 状态在进程崩溃后会残留，
   需要在报告中人工识别；不影响幂等（只认 `success`）
3. `config_hash` 反证依赖当时使用的字段集，若未来 `ValidationConfig`
   再增字段，历史记录的反证需要同步新增变体
