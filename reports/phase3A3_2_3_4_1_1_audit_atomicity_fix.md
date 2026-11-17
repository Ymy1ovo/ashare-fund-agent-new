# 阶段3A.3.2.3.4.1.1 审计完整性与 Sparse 明细持久化整改

- 基线 HEAD：`5a4af823d230870d469c45ad30f3deb20d893b70`
- 执行日期：2026-11-17
- 范围：修 6 个已知缺陷，未重跑 52 次内部回测，未改策略/会计/绩效算法

---

## 1. 本轮发现的问题

| # | 问题 | 位置 | 性质 |
| ---: | --- | --- | --- |
| 1 | `copy_info` 被尾随逗号变成 tuple | `runner.py` sparse 成功路径 | 会导致 TypeError，成功路径直接崩 |
| 2 | 主库插入与对账不在同一事务 | `audit.py::persist_sparse_details` | 对账失败无法回滚，留半条 |
| 3 | 对账只比计数与合计金额 | `audit.py` | 单条单字段错误查不出 |
| 4 | WF 只查 `walkforward_test` | `audit.py::audit_completeness` | 缺训练窗口仍判 complete |
| 5 | 压力测试只看场景是否登记 | 同上 | 登记了但执行失败也通过 |
| 6 | `_version_of()` 精确未命中回退最新版 | 同上 | 掩盖历史版本缺失 |

问题 1 是**本轮亲眼确认的真实缺陷**：`copy_info = {...},` 末尾那个逗号
让它成为只含一个元素的 tuple，下一行 `copy_info["copy_path"]` 必然抛
`TypeError: tuple indices must be integers or slices, not str`。

是否能触发取决于是否真的跑到 sparse 成功路径。上轮未重跑 52 次内部回测，
所以线上没暴露；只要跑一次带 sparse 场景的 validation 就会崩。

---

## 2. 每个问题对应的代码修改

### 2.1 P0-1：tuple 缺陷

```python
# 修改前
copy_info = {**copy_info, "removed": True,
             "audit_detail": "audit_sparse_applications"},

# 修改后
copy_info = {
    **copy_info,
    "removed": True,
    "audit_detail": "audit_sparse_applications",
}
```

同时检查了成功路径的完整时序，并补了副本清理的失败处理：

```
副本创建 → 回测 → 明细持久化 → 逐字段对账 → 更新位置 → 删副本 → 返回
                                                  ↑
                                    清理失败 → mark_sparse_detail_location
                                              记录失败原因 → 抛 AuditError
```

清理失败不再静默：关联行被写上「明细已复制但对账后删副本失败 + 残留路径」，
然后整条场景标 `failed`。

失败路径新增 `mark_backtest_failed()`：回测跑完了但审计持久化/对账失败时，
把已登记的关联行降级为 `failed` 并写原因——关联行保留（它确实发生过），
但状态不能是 success。

### 2.2 P0-2：事务原子性

`persist_sparse_details()` 重写为**单个 `with get_connection()` 块内**
完成「插入 + 对账」，对账不通过就在块内 `raise`，
由连接管理器统一 `rollback`。

```python
with get_connection(db_path) as conn:
    # 插入应用明细
    # 插入应收明细
    # 读出主库实际行
    # 逐字段对账 → problems
    if problems:
        raise AuditError(...)   # ← 块内 raise → rollback
    return {...}
```

历史行不删：`ON CONFLICT DO NOTHING`，已存在的行原样保留。
重复写入幂等：连跑 3 次行数恒为 1（测试 `test_sparse_persist_idempotent_three_times`）。

失败原因精确到字段：`应用 action_id=5 字段 cash_delta 不一致：副本=1.5 主库=0.0`。

### 2.3 P0-3：逐字段对账

应用明细 15 个字段全部参与：

```
action_id / code / effective_date / action_type / shares_before /
shares_after / cash_delta / fractional_cash / applied_at /
receivable_amount / cash_paid_amount / fractional_shares /
disposed_cost_basis / realized_pnl / official_ratio
```

应收明细 10 个字段全部参与：

```
action_id / code / record_date / ex_date / pay_date / shares_at_ex /
cash_per_share / amount / status / settled_at
```

**精度规则（明确写死）**：

| 类型 | 规则 |
| --- | --- |
| 数值字段（`cash_delta` / `amount` / `official_ratio` 等 10 个） | 绝对误差 `<= 1e-6` |
| 整数与文本字段 | 严格相等 |
| 复制前后 | 双方都先 `round(float(x), 6)` 再比，与库内写入精度一致 |

`1e-6` 与 `save_receivable()` 里 `round(amount, 6)` 的精度对齐，
不是为了放宽而选的大容差。

### 2.4 P0-4：Walk-Forward 完整性

新增逐窗口核对（`audit_completeness()`）：

1. 训练窗口：每个已执行窗口 × `wf_grid` 每个候选，都必须有
   `walkforward_train` 记录（场景键 `w{idx}-ma{candidate}`）。
2. 训练记录数量必须等于 `已执行窗口数 × 候选数`。
3. 测试窗口：每个已执行窗口必须有 `walkforward_test` 记录
   （场景键 `w{idx}-ma{selected_param}`）。
4. 训练/测试记录状态必须为 `success`。
5. `validation_windows.status` 与执行结果一致。
6. `insufficient_data` 窗口单列一条 problem——它没有执行，审计不完整。
7. 窗口表为空（没有 WF）也判不完整。

`wf_grid` 从 `validation_runs.walkforward_config` 读；读不到时退回
「该窗口至少有一条训练记录」的弱校验，并在 problem 里说明依据。

### 2.5 P0-5：压力测试执行状态

场景不再「登记了就算过」，改为三重核对：

| 检查 | 失败含义 |
| --- | --- |
| 场景能关联到内部回测记录 | 场景没真的跑 |
| 回测记录 `status == success` | 执行失败 |
| 场景自身 `status` 在允许集合内 | 状态异常 |

`insufficient_data` 的区分：

| 状态 | 含义 | 判定 |
| --- | --- | --- |
| 场景 `insufficient` + 回测 `success` | 执行成功，样本不足 | 不报执行失败 |
| 场景 `insufficient` + 回测 `failed` | 执行本身失败 | 报「回测执行状态为 failed」 |
| `insufficient` 挂在非样本量场景（如 `cost_plus_50`） | 误用 | 报「只有样本量类场景允许该状态」 |

---

## 3. P0-6：事件版本严格匹配

`_version_of()` 删除了回退分支：

```python
# 修改前：精确未命中 → 取该 action_key 的最大版本号
fallback = conn.execute("... ORDER BY version_no DESC LIMIT 1")

# 修改后：只按 (action_key, version_no) 精确查，查不到返回 None
row = conn.execute(
    "SELECT ... FROM corporate_action_versions "
    "WHERE action_key=? AND version_no=?", (key, version_no))
return dict(row) if row is not None else None
```

`version_no` 为 `None` 直接返回 `None`（不拿空值去匹配）。

版本缺失后：

- 事件条目 `version_status = "version_unavailable"`
- `action_id` 进 `versions_unavailable`
- `audit_trace()` 把它写进 `problems`
- `audit_status` 不为 `complete`

Sparse 审计明细新增两列保留版本证据：
`audit_sparse_applications` / `audit_sparse_receivables` 各加
`version_no INTEGER` 与 `event_fingerprint TEXT`，
由 `persist_sparse_details()` 从副本的 `corporate_actions` 一并复制。

---

## 4. 新增测试与覆盖场景

测试文件：`tests/test_validation_audit_3a3_2_3_4.py`，57 → **95** 项（+38）。

### 4.1 tuple 缺陷

| 测试 | 覆盖 |
| --- | --- |
| `test_sparse_success_path_returns_dict` | 返回的 `data_copy` 必须是 dict 且有 `copy_path` |

### 4.2 原子事务与逐字段对账

| 测试 | 覆盖 |
| --- | --- |
| `test_application_field_tamper_detected` ×14 | 应用明细 14 个字段逐个篡改 → 全部对账失败 |
| `test_receivable_field_tamper_detected` ×9 | 应收明细 9 个字段逐个篡改 → 全部对账失败 |
| `test_reconcile_failure_rolls_back_whole_transaction` | 对账失败后主库不留新行 |
| `test_sparse_persist_idempotent_three_times` | 连跑 3 次行数恒为 1 |
| `test_sparse_detail_keeps_version_and_fingerprint` | 版本号与指纹被保留 |
| `test_sparse_persist_requires_event_row` | 副本无事件行 → 对账失败不留行 |

每个字段篡改测试都验证：抛出的错误信息里含该字段名，
且回滚后主库行数不变、值仍是篡改前的值。

### 4.3 Walk-Forward

| 测试 | 覆盖 |
| --- | --- |
| `test_wf_missing_train_window_incomplete` | 缺训练窗口 → 不完整 |
| `test_wf_missing_test_window_incomplete` | 缺测试窗口 → 不完整 |
| `test_wf_failed_train_window_incomplete` | 训练失败 → 不完整 + 原因 |
| `test_wf_insufficient_window_incomplete` | 窗口数据不足 → 不完整 |

### 4.4 压力测试

| 测试 | 覆盖 |
| --- | --- |
| `test_stress_success_but_execution_failed_incomplete` | 登记 success 但执行 failed → 不完整 |
| `test_stress_scenario_without_run_incomplete` | 场景无关联回测 → 不完整 |
| `test_stress_insufficient_not_treated_as_failure` | insufficient 不误判为执行失败 |
| `test_stress_insufficient_on_wrong_scenario_incomplete` | 非样本量场景用 insufficient → 报错 |

### 4.5 版本严格匹配

| 测试 | 覆盖 |
| --- | --- |
| `test_version_exact_match_no_fallback` | **最新版本存在但历史版本不存在 → 标 version_unavailable，不回退** |
| `test_version_number_none_marked_unavailable` | 版本号为空 → 不可用 |

`test_version_exact_match_no_fallback` 的做法：删掉该事件的精确版本行，
只插一条 `version_no=99` 的假版本，然后断言
`version_status == "version_unavailable"` 且 `version is None`。
旧实现会回退到 99 并报 `available`，这个测试会失败。

---

## 5. 全量测试结果

```
670 passed, 1 warning in 234.00s (0:03:53)
```

| 项 | 数量 |
| --- | ---: |
| 总数 | **670** |
| 通过 | **670** |
| 失败 | **0** |
| 跳过 | **0** |
| xfail | **0** |
| 耗时 | 234.00 秒 |

唯一 warning 是 `StarletteDeprecationWarning`（httpx 弃用），与业务无关。

基线 632 → 670，**+38**，全部对应本轮修复点。

### 5.1 未删除 / 未弱化

上一轮 632 项全部保留。修改了 2 处既有测试的**前置构造**（不是断言）：

| 测试 | 改动 | 原因 |
| --- | --- | --- |
| `test_sparse_reconcile_detects_amount_mismatch` | 副本里补插 `corporate_actions` 事件行 | 新规则要求版本可追溯，无事件行会先失败 |
| `test_sparse_detail_copy_idempotent` | 同上 | 同上 |

断言本身未变。

---

## 6. API smoke 与 Streamlit AppTest

| 项 | 结果 |
| --- | --- |
| `scripts/smoke_validation_api.py` | `SMOKE_FAILED: 无` |
| `GET /api/validations/not_exist` | 404（期望） |
| AppTest `3_回测.py` | exception 0 / error 0 / df 5 / metric 5 |
| AppTest `4_策略验证.py` | exception 0 / error 0 / df 6 / metric 4 |

---

## 7. SQLite 完整性

```
PRAGMA integrity_check -> ok
```

| 表 | 本轮前 | 本轮后 | 变化 |
| --- | ---: | ---: | --- |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `validation_runs` | 54 | 54 | 0 |
| `backtest_runs` | 12 | 12 | 0 |
| `validation_backtest_runs` | 361 | 361 | 0 |
| `validation_regime_stats` | 28 | 28 | 0 |
| `audit_sparse_applications` | 0 | 0 | 0 |
| `audit_sparse_receivables` | 0 | 0 | 0 |

**只有结构变化，没有数据变化**：
`audit_sparse_applications` / `audit_sparse_receivables` 各加两列
（`version_no`、`event_fingerprint`），由 `_migrate_audit_columns()` 幂等补齐。

新增表唯一性：

| 表 | 唯一键 | 实测 |
| --- | --- | --- |
| `audit_sparse_applications` | `(validation_id, run_id, action_id)` | `IntegrityError` 拦截重复 |
| `audit_sparse_receivables` | `(validation_id, run_id, action_id)` | 同上 |

---

## 8. 历史记录前后对照

### 8.1 54 条 validation 的审计状态

| 状态 | 数量 |
| --- | ---: |
| `unavailable_legacy` | 47 |
| `unavailable_legacy_evidence` | 7 |
| `complete` | **0** |

`audit_trace` 与 `audit_completeness` 对 54 条**逐条比对，不一致 0 条**。

### 8.2 aad7935a2bac4cc4

| 项 | 值 |
| --- | --- |
| 状态 | `unavailable_legacy_evidence` |
| sparse 关联行 | `detail_location = "unavailable_external_detail"` |
| sparse 逐笔明细 | 不伪造，保持为空 |
| 绩效指标 | **零改动** |
| 是否被升级为 complete | **否** |

### 8.3 绩效与会计数据

本轮**未执行任何 validation、未重跑任何内部回测**，
`validation_runs` 的绩效字段、`corporate_action_applications`、
`dividend_receivables`、`corporate_actions`、`corporate_action_versions`
行数与内容全部未变。

行情指纹 `market-fingerprint-v3` / 116,609 行 /
`d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`，未变。

---

## 9. 尚未解决的问题及其影响

1. **本轮没有用真实 sparse 场景端到端验证整条链路。**
   任务书禁止重跑 52 次内部回测，所以 tuple 修复、事务原子性、
   `audit_sparse_applications` 的实际写入，都只在单元测试层面验证过
   （测试里造了真实的副本库、真实的事件行、真实的明细行）。
   下次真实跑带 sparse 的 validation 才能确认端到端。
   **影响**：`persist_sparse_details()` 在真实数据量下的表现（如 30+ 条应用）
   未实测，理论上无差异，但未证明。

2. **存量 7 条记录永久 `unavailable_legacy_evidence`。**
   凭证体系建立前的运行无法补写，补写等于伪造。
   要得到 `complete` 记录必须新跑一次 validation（本轮禁止）。

3. **`aad7935a2bac4cc4` 的 sparse 逐笔明细永久不可恢复。**
   副本目录已删，已标 `unavailable_external_detail`。

4. **`persist_sparse_details()` 的原子性依赖 SQLite 的隐式事务。**
   `get_connection()` 用 `conn.commit()` 提交、异常时 `rollback()`，
   所有 `execute` 在同一连接同一事务内。这不等于「显式 BEGIN IMMEDIATE」，
   在有并发写入时可能出现锁等待——已有 `busy_timeout=5000` 兜底，
   但高并发下仍可能失败（失败会整体回滚，不会留半条）。

5. **`wf_grid` 从 `walkforward_config` 读取，历史记录该字段为空 `{}`。**
   对存量记录走「每窗口至少一条训练记录」的弱校验；
   弱校验比强校验宽，但存量记录本来就已经因缺凭证判为不完整，
   不构成放行风险。

6. 测试结果是本会话本地执行结果，**不是 ChatGPT 独立验证**。

---

## 10. 本轮最终结论

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| Sparse 成功路径不再有 tuple 类型错误 | ✅ | §2.1 代码 + `test_sparse_success_path_returns_dict` |
| Sparse 完整成功路径集成测试通过 | ⚠️ 部分 | 单元级通过；真实端到端未跑（§9.1） |
| 插入与逐字段对账处于同一原子事务 | ✅ | §2.2 + `test_reconcile_failure_rolls_back_whole_transaction` |
| 任一关键字段对账失败均能整体回滚 | ✅ | 23 个字段篡改测试 |
| 历史审计记录不被删除或覆盖 | ✅ | §8 行数与状态未变 |
| WF 训练和测试窗口均有完整性检查 | ✅ | §2.4 + 4 项测试 |
| 压力测试检查真实关联回测及执行状态 | ✅ | §2.5 + 4 项测试 |
| `insufficient_data` 与执行失败有明确区分 | ✅ | §2.5 三态判定 |
| 公司行为版本精确匹配，不再回退 | ✅ | §3 + `test_version_exact_match_no_fallback` |
| Sparse 审计保留版本号和指纹 | ✅ | 两个新列 + `test_sparse_detail_keeps_version_and_fingerprint` |
| 旧记录继续标 `unavailable_external_detail` | ✅ | §8.2 |
| 全量测试通过，数量如实报告 | ✅ | 670 passed / 0 failed / 0 skipped |
| API smoke / AppTest / integrity_check | ✅ | §6 §7 |
| 报告/README/CHANGELOG/ZIP/manifest/SHA256 | ✅ | §12 |
| Gitee 提交、GitHub 同步 | ✅ | §12 |

**代码修改完成不等于阶段验收通过。** 本报告只证明"本轮 6 个 P0 缺陷已修
并有测试覆盖"，端到端 sparse 链路仍需一次真实运行确认。

---

## 11. 修改文件清单

| 文件 | 变更 |
| --- | --- |
| `app/validation/audit.py` | `persist_sparse_details()` 改为单事务 + 逐字段对账；`_version_of()` 去回退；新增 `mark_backtest_failed()`、`_reconcile_rows()`、`_normalize()`、`_values_equal()`；`audit_completeness()` 补 WF 与压力检查 |
| `app/validation/audit_schema.py` | 两张 sparse 明细表各加 `version_no`、`event_fingerprint` |
| `app/database/db.py` | `_migrate_audit_columns()` 补 sparse 表两列 |
| `app/validation/runner.py` | 修 tuple 缺陷；副本清理失败处理；失败时 `mark_backtest_failed()` 降级 |
| `tests/test_validation_audit_3a3_2_3_4.py` | 57 → 95 项 |
| `README.md` / `CHANGELOG.md` | 同步 |
| `reports/phase3A3_2_3_4_1_1_audit_atomicity_fix.md` | 本报告 |

---

## 12. 交付

| 项 | 值 |
| --- | --- |
| 测试 | 670 passed / 0 failed / 0 skipped / 0 xfail，234.00 秒 |
| 新增测试 | +38 |
| `integrity_check` | ok |
| 行情指纹 | `d54727c0…` 未变 |
| 数据库快照 | `data/backups/fund_agent_post_3a3_2_3_4_1_1_20261117.db` |
| 快照大小 | 274,653,184 字节 |
| 快照 SHA256 | `c61cb3bf87b34cc31303df59fceec3eebdd53a89aec6b369524c1df75389e14e` |
| ZIP | `dist/jj-agent-phase3A3_2_3_4_1_1-src.zip` |
| ZIP 文件数 | 303 |
| ZIP 大小 | 1,656,867 字节 |
| ZIP SHA256 | `9ee07adc8e6ebcac729569e801bc8498106ec27e08a75a89a2f5ba7101dac442` |
| SHA 清单 | `dist/SHA256SUMS_3a3_2_3_4_1_1.txt` |
| ZIP 内容检查 | 无 `.db` / `.venv` / `__pycache__` / `.log` / `tmp*` |
