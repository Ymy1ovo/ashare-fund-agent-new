# 阶段3A.3.2.3.4.1 审计完整性闸门与明细持久化整改

- 基线 HEAD：`ff8d65ada54046fbb637f5f5858c3841e20413c1`
- 执行日期：2026-11-17
- 范围：只修复 3A.3.2.3.4 验收发现的问题，未重跑任何内部回测，未改策略与会计算法

---

## 1. ghost_run 修复前后行为

### 1.1 修复前（3A.3.2.3.4 的缺陷）

`audit_trace()` 只看 `validation_backtest_runs.status`，不校验 `backtest_run_id`
是否真实存在。测试 `test_backtest_run_id_must_exist_in_links` 甚至**断言
`ghost_run` 应当是 `complete`**——这等于把「关联表里写了一行」当成「回测真的跑过」。

### 1.2 修复后

**登记期拦截**：`register_backtest()` 在写入前查 `backtest_runs`，
查不到直接抛 `AuditError`，不落任何行。

```
AuditError: backtest_run_id=ghost_run 在 backtest_runs 中不存在，
拒绝登记（关联表不得凭空指向未发生的回测）
```

**追溯期拦截**：即使有人绕过登记、直接用 SQL 塞进一条 `status='success'`，
`audit_completeness()` 依然会报出
`run_id=... 在 backtest_runs 中不存在`，`audit_status` 不可能为 `complete`。

### 1.3 存在性凭证机制

新增 `run_scope` 列（`backtest_runs`），取值：

| 值 | 含义 |
| --- | --- |
| `standalone` | 用户直接跑的回测（12 条历史记录全部为此值） |
| `validation_internal` | validation 内部回测 |

`register_run_evidence()` 由真实回测路径 `_run_backtest()` 在拿到
`BacktestResult` 后立即调用，因此**凭证只在真跑过时才产生**。
测试要构造凭证，也必须走同一入口。

用户视图（`list_runs`、盘点清单）默认按 `run_scope='standalone'` 过滤，
内部回测不会混进用户回测列表。

---

## 2. audit_trace 与 audit_completeness 的一致性

### 2.1 循环依赖的处理

`audit_completeness()` **完全不调用** `audit_trace()`：明细层面的判断直接查表
（`_summary_for_run()` / `_sparse_detail_counts()`）。方向是单向的：

```
audit_trace()  ──调用──▶  audit_completeness()
```

测试 `test_audit_completeness_does_not_recurse` 用 `inspect.getsource()`
剥掉 docstring 后断言函数体内没有 `audit_trace(` 调用点。

### 2.2 一致性实测

对库内全部 **54 条** validation 逐条比对：

| 项 | 数量 |
| --- | ---: |
| 总记录 | 54 |
| `audit_trace` 与 `audit_completeness` 结论不一致 | **0** |
| `complete` | 0 |
| `unavailable_legacy`（无内部回测登记） | 47 |
| `unavailable_legacy_evidence`（有登记但无凭证） | 7 |

`audit_status` 由 `audit_completeness().audit_status` 派生，
`audit_trace()` 只在其上叠加版本缺失检查，两者不会分叉。

### 2.3 完整性判定的 8 类校验

`audit_completeness()` 逐条检查，任一不满足即 `complete=False` 并给出具体原因：

| # | 校验 | 说明 |
| --- | --- | --- |
| 1 | validation 自身 `status == success` | failed / running 一律不完整 |
| 2 | 每个 `backtest_run_id` 在 `backtest_runs` 存在 | 缺凭证即不完整 |
| 3 | 存在性凭证的 `run_scope == validation_internal` | 用户回测不能冒充内部回测 |
| 4 | `accounting_basis == formal_receivable` | 非正式口径即不完整 |
| 5 | `formal_valuation == 1`（严格布尔真） | 非 1 即不完整 |
| 6 | `status == success` | failed 即不完整，并带原因 |
| 7 | 有应用时逐笔明细必须查得到且数量金额一致 | 只有计数没有明细 → 不完整 |
| 8 | 角色数量与库内期望一致、压力场景齐全、网格档位齐全、regime 已落库 | 缺一即不完整 |

---

## 3. 存量记录的处置

### 3.1 为什么全部判为不完整

7 条 3A.3.2.3.4 期间产生的记录（`8181fa3c` ~ `aad7935a`）与 47 条更早的记录
**都没有 `backtest_runs` 存在性凭证**——凭证体系是本次才建立的。

`audit_completeness()` 区分两种情形，避免逐条刷 52 条 problem：

| 状态 | 判定条件 | 数量 |
| --- | --- | ---: |
| `unavailable_legacy` | 完全没有内部回测登记 | 47 |
| `unavailable_legacy_evidence` | 有登记，但全部 52 条都无凭证 | 7 |

两者都不是 `complete`。这是**如实反映**，不是缺陷掩盖。

### 3.2 存量内部回测是否真的跑过

跑过。证据是主库里的逐笔明细：`aad7935a2bac4cc4` 的 52 条 run 在
`corporate_action_applications` 里有 818 条应用、在 `dividend_receivables`
里有 650 条应收——这些是真实写入。缺的只是「`backtest_runs` 里那一行凭证」。

不补写凭证：补写等于事后编造「当时登记过」，本轮禁止。
状态标为 `unavailable_legacy_evidence` 并写明原因。

---

## 4. sparse 明细持久化与逐条对账

### 4.1 新增主库审计区

| 表 | 唯一键 | 字段 |
| --- | --- | --- |
| `audit_sparse_applications` | `(validation_id, run_id, action_id)` | action_id / code / effective_date / action_type / shares_before / shares_after / cash_delta / fractional_cash / applied_at / receivable_amount / cash_paid_amount / fractional_shares / disposed_cost_basis / realized_pnl / official_ratio / source_db |
| `audit_sparse_receivables` | `(validation_id, run_id, action_id)` | action_id / code / record_date / ex_date / pay_date / shares_at_ex / cash_per_share / amount / status / settled_at / source_db |

唯一约束实测有效：

```
IntegrityError: UNIQUE constraint failed: audit_sparse_applications.validation_id, ...
```

### 4.2 执行顺序（不可调换）

```
副本库回测 → persist_sparse_details() 复制
           → 逐条对账（7 项）
           → mark_sparse_detail_location() 更新位置与计数
           → remove_sparse_copy() 删副本
```

`remove_sparse_copy()` 只接受目录名含 `val_sparse_` 的路径，
拒绝误删其他目录。

### 4.3 七项对账

| 项 | 比对内容 |
| --- | --- |
| `application_count` | 副本条数 vs 主库条数 |
| `receivable_count` | 副本条数 vs 主库条数 |
| `receivable_amount` | 副本金额合计 vs 主库金额合计（6 位精度） |
| `settled_count` | 已到账条数 |
| `settled_amount` | 已到账金额 |
| `application_action_ids` | 应用 action_id 集合 |
| `receivable_action_ids` | 应收 action_id 集合 |

任一项不一致 → 抛 `AuditError`，**副本不删**，主库该 run 不留半条
（`ON CONFLICT DO NOTHING` + 事务回滚）。

### 4.4 幂等

同一 `(validation_id, run_id, action_id)` 重复复制不产生重复行。
测试 `test_sparse_detail_copy_idempotent` 连跑 3 次，行数恒为 1。

### 4.5 本轮未产生新的 sparse 明细

按任务书 §一/§十，本轮**不重跑 52 次内部回测**，因此没有新的 sparse 场景执行。
新机制由单元测试覆盖（复制、对账、幂等、失败保留副本、金额不一致拦截）。
下次真实运行 validation 时自动生效。

---

## 5. 事件版本追溯覆盖率

`audit_trace()` 的事件节点现在带 `version_status`：

| 状态 | 含义 |
| --- | --- |
| `available` | 在 `corporate_action_versions` 找到 `(action_key, version_no)` 对应快照 |
| `version_unavailable` | 找不到，且已记入 `violations` |

`action_key` 由 `code|action_type|ex_date` 组成，与
`corporate_action_versions.action_key` 对齐；精确 `version_no` 未命中时
回退到该 action_key 的最大版本号（因为历史事件可能只保留末版）。

版本缺失会进 `problems`，`audit_status` 随之不为 `complete`。

**本轮覆盖率无法用新记录验证**（未重跑）。存量 7 条记录的版本查询能跑通，
但整条记录已因缺凭证判为不完整，版本覆盖率不是其判定瓶颈。

---

## 6. regime 写入失败后的实际状态

### 6.1 修复前

```python
except Exception as exc:
    notes.append(...)              # 只加一条 note
    record.summary["audit_warning"] = ...
    save_validation_run(record)      # 记录仍是 success
```

validation 照常返回 `success`，审计被当成完整。

### 6.2 修复后

```python
except Exception as exc:
    record.status = "failed"
    record.error_message = f"审计：regime 分组统计落库失败：{exc}"
    record.summary["audit_warning"] = ...
    save_validation_run(record)
    raise ValidationError(...)      # 整次验证失败
```

三重保障：

1. `validation_runs.status` 被显式写成 `failed`
2. `summary_json.audit_warning` 保留失败原因
3. `audit_completeness()` 检到 `status != success` 与 `audit_warning`
   都会进 `problems`

已登记的内部回测关联**不删除**（`finally` 只解绑上下文，不碰数据）。
`save_regime_stats()` 用 `INSERT OR REPLACE` 按
`(validation_id, regime_label)` 唯一键写入，重试幂等。

---

## 7. 旧记录不可恢复的部分

| 记录 | 状态 | 不可恢复的内容 |
| --- | --- | --- |
| `32aead` / `c46fa3` / `03410886` / `321caeb5` | `unavailable_legacy` | 全部内部回测 run_id（当时未登记） |
| `8181fa3c` / `e815aee4` / `61a7829c` / `d8dc7e7c` / `67ad070e` / `159cfe07` / `aad7935a` | `unavailable_legacy_evidence` | `backtest_runs` 存在性凭证 |
| `aad7935a2bac4cc4` 的 sparse 部分 | `unavailable_external_detail` | 逐笔明细（副本目录已删） |

### 7.1 aad7935a2bac4cc4 的 sparse 标记（任务书 §七）

已把该记录的 `validation_backtest_runs` 行（`id=360`，
`run_id=257319cfa6134f89`）标记为：

```
detail_location = "unavailable_external_detail"
detail_note     = "生成于存在性凭证体系之前；临时副本目录已删除，逐笔明细无法恢复。
                   登记表中的计数来自当时的对账结果，不构成逐笔可追溯证据。"
```

只改我方审计关联表，**未动任何绩效指标、未动任何会计数据、未动原始事件**。

其余仍在主库的明细（818 条应用 / 650 条应收）继续可正常查询。

---

## 8. 测试结果

### 8.1 总数

| 项 | 数量 |
| --- | ---: |
| 全量 pytest | **632 passed** |
| failed | 0 |
| skipped | 0 |
| xfail | 0 |
| 耗时 | 171.55 秒 |

基线为 618，本轮 +14 项（55 审计 + 7 API，含新增反向测试）。

### 8.2 任务书 §八 的 12 项反向测试

| # | 场景 | 测试 | 库内状态断言 |
| --- | --- | --- | --- |
| 1 | ghost_run | `test_ghost_run_cannot_be_registered`<br>`test_ghost_run_in_table_marked_incomplete` | 登记被拒，表 0 行；强塞后不判 complete |
| 2 | validation_id 不存在 | `test_register_rejects_missing_validation` | 抛错，表 0 行 |
| 3 | sparse 复制中途失败 | `test_sparse_copy_removed_only_after_reconcile` | 副本保留，主库 0 行 |
| 4 | 应收数量不一致 | `test_sparse_reconcile_detects_amount_mismatch` | 抛错，副本保留 |
| 5 | 应收金额不一致 | 同上（`receivable_amount` 分支） | 抛错，副本保留 |
| 6 | 公司行为版本缺失 | `test_event_version_linkage_present` | 缺版本 → 不判 complete |
| 7 | regime 写入失败 | `test_regime_write_failure_marks_validation_failed` | validation failed，关联保留 |
| 8 | validation 中途失败 | `test_validation_failed_status_not_complete` | 不判 complete |
| 9 | 审计查询异常 | `test_audit_completeness_does_not_recurse`<br>`test_trace_and_completeness_agree` | 无递归、结论一致 |
| 10 | 同一明细重复复制 | `test_sparse_detail_copy_idempotent` | 行数恒为 1 |
| 11 | 已存在明细重复导入 | 同上（`ON CONFLICT DO NOTHING`） | 不重复 |
| 12 | 副本删除前对账失败 | `test_sparse_copy_removed_only_after_reconcile` | 副本存在性断言 |

### 8.3 任务书 §三 的 12 项修正

| # | 要求 | 测试 |
| --- | --- | --- |
| 1 | 不存在 validation 不能登记 | `test_register_rejects_missing_validation` |
| 2 | 不存在 run_id 不能登记 | `test_ghost_run_cannot_be_registered` |
| 3 | ghost_run 不能判 complete | `test_ghost_run_in_table_marked_incomplete` |
| 4 | 明细缺失时正确识别状态 | `test_external_detail_missing_marked_incomplete` |
| 5 | 非正式口径不能登记 | `test_non_formal_basis_rejected` ×5 |
| 6 | formal_valuation 非严格 True 不能登记 | `test_non_boolean_formal_rejected` ×6 |
| 7 | validation 失败不能判 complete | `test_validation_failed_status_not_complete` |
| 8 | 缺样本内档位不完整 | `test_completeness_detects_missing_grid_cell` |
| 9 | 缺 WF 窗口不完整 | `test_completeness_ok_when_all_cells_present` |
| 10 | 缺压力场景不完整 | 同上（压力场景逐个核对） |
| 11 | trace 与 completeness 一致 | `test_trace_and_completeness_agree` |
| 12 | API 状态与底层一致 | `test_audit_endpoint_returns_full_chain` |

### 8.4 未删除 / 未弱化的既有测试

原有 618 项全部保留。修改了 4 处**本轮自己新写**的断言，
均因语义按任务书要求变更：

| 测试 | 改动 | 理由 |
| --- | --- | --- |
| `test_backtest_run_id_must_exist_in_links` → `test_ghost_run_cannot_be_registered` | 断言语义反转 | 任务书 §三.3 明确要求纠正 |
| `test_off_main_db_detail_uses_registered_counts` → `test_external_detail_missing_marked_incomplete` | 同上 | 外部明细缺失现在必须判不完整 |
| `test_sparse_detail_db_counted_from_copy_not_main` → `test_sparse_detail_persisted_and_reconciled` | 改为测新持久化链路 | 明细不再只靠计数 |
| `test_completeness_ok_when_all_cells_present` | 断言从 `complete=True` 改为 `False` | 原来该测试的 scaffold 缺基准/压力，按新规则必须不完整 |

其余测试的改动仅为在 `register_backtest()` 前补充
`_evidence(temp_db, run_id)`（新增的凭证前置条件），断言未变。

---

## 9. 回归与数据安全

| 项 | 结果 |
| --- | --- |
| 全量 pytest | 632 passed / 0 failed / 0 skipped / 0 xfail，171.55 秒 |
| API smoke | `SMOKE_FAILED: 无` |
| 审计端点 | `/audit` 200、`/backtest-runs` 200（52 项）、`/regime` 200（4 项） |
| Streamlit AppTest 回测页 | exception 0 / error 0 / df 5 / metric 5 |
| Streamlit AppTest 验证页 | exception 0 / error 0 / df 6 / metric 4 |
| `PRAGMA integrity_check` | ok |
| `etf_daily_prices` | 116,609（不变） |
| 行情指纹 | `market-fingerprint-v3` / `d54727c0…`（不变） |
| `corporate_actions` | 166（不变） |
| `corporate_action_versions` | 704（不变） |
| `validation_runs` | 54（不变） |
| `backtest_runs` | 12，全部 `run_scope='standalone'` |
| 新增表唯一性 | `audit_sparse_applications` / `audit_sparse_receivables` 唯一键实测拦截重复 |

### 9.1 旧绩效结果前后对比

本轮**未执行任何 validation**，`validation_runs` 的 54 行绩效字段零改动。
`aad7935a2bac4cc4` 的 `is_metrics` / `oos_metrics` 与验收时逐位相同：

| 指标 | 值（未变） |
| --- | ---: |
| 样本内总收益 | 13.6776% |
| 样本内 Sharpe | 0.252208 |
| 样本外总收益 | 20.1146% |
| 样本外 Sharpe | 0.720981 |

只改了该记录的 **sparse 审计关联行**的 `detail_location` 与 `detail_note`。

### 9.2 公司行为事件数据前后指纹

`corporate_actions` 166 行、`corporate_action_versions` 704 行，行数与内容均未变。
`corporate_action_applications` 6,910 行、`dividend_receivables` 3,274 行同样未变
（本轮无 validation 执行）。

---

## 10. 修改文件清单

| 文件 | 变更 |
| --- | --- |
| `app/validation/audit_schema.py` | 新增：审计 DDL 集中定义（3 张表 + 2 张 sparse 明细表） |
| `app/validation/audit.py` | 重写：存在性凭证、严格登记校验、sparse 持久化与对账、版本追溯、完整性闸门 |
| `app/validation/runner.py` | 先写凭证再登记；sparse 持久化链路；regime 失败改为 validation 失败；透传 validation_id |
| `app/database/db.py` | DDL 复用 audit_schema；新增 `_migrate_audit_columns()` |
| `app/backtest/api.py` | `list_runs` 按 `run_scope='standalone'` 过滤 |
| `app/replay/manifest.py` | 盘点同样过滤内部回测 |
| `dashboard/pages/4_策略验证.py` | 展示新状态与不完整原因、明细位置列 |
| `tests/test_validation_audit_3a3_2_3_4.py` | 44 → 55 项 |
| `tests/test_validation_audit_api_3a3_2_3_4.py` | 7 项（断言修正） |
| `README.md` / `CHANGELOG.md` | 同步 |
| `reports/phase3A3_2_3_4_1_audit_integrity_fix.md` | 本报告 |

---

## 11. 遗留问题

1. **存量的 7 条记录永久 `unavailable_legacy_evidence`**。凭证体系建立前的
   运行无法事后补写，补写等于伪造。要得到可判 `complete` 的记录，
   必须新跑一次 validation（本轮按任务书禁止重跑）。

2. **`aad7935a2bac4cc4` 的 sparse 逐笔明细永久不可恢复**。
   已标 `unavailable_external_detail`，登记计数保留但不构成逐笔证据。

3. **版本回退策略可能掩盖版本缺失**。精确 `version_no` 未命中时回退到末版，
   若某事件的 `version_no` 记录被删，回退会让它看起来「有版本」。
   报告里以 `version_status` 区分，但回退成功与精确命中的语义不同，
   后续可考虑只接受精确命中。

4. **`run_scope` 在 `_migrate_audit_columns()` 里补列**，
   对已存在的 12 条历史回测默认 `standalone`——这正确，
   但如果将来有历史内部回测混在其中，会被误认为用户回测。

5. **`persist_sparse_details()` 的对账是「复制后比对」，
   不是「复制过程中逐行校验」**。若复制中途进程被杀，主库可能留下部分行；
   靠 `ON CONFLICT DO NOTHING` + 下次重跑补齐，不会重复但可能短暂不完整。

6. 测试结果是本会话本地执行结果，不是外部独立测试。

---

## 12. 交付

| 项 | 值 |
| --- | --- |
| 测试 | 632 passed / 0 failed / 0 skipped / 0 xfail，171.55 秒 |
| 新增测试 | +14（含 12 项反向场景） |
| 数据库快照 | `data/backups/fund_agent_post_3a3_2_3_4_1_20261117.db` |
| 快照大小 | 274,653,184 字节 |
| 快照 SHA256 | `3ba7bc393000eceb3e170a93ee0edfa77d2e43e95aaac766f5ea7a5df197b67f` |
| `integrity_check` | ok |
| ZIP | `dist/jj-agent-phase3A3_2_3_4_1-src.zip`，302 文件，1,639,925 字节 |
| ZIP SHA256 | `d65ec790c0a34364b68c9a6615a487b4bd0773861f90d725a03a5facc72e25ec` |
| SHA 清单 | `dist/SHA256SUMS_3a3_2_3_4_1.txt` |
