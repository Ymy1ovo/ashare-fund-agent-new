# 阶段3A.3.2.3.6.1 修复重放审计缺陷并重新执行前两条记录

- 基线 HEAD：`16c0606ef912e6b3ea5110ac1f9bd6199cb3599f`
- 执行日期：2026-11-18
- 范围：只修缺陷 A / B，只重新执行 2 条记录。未执行剩余 3 条，未进入 3A.3.3/3B。

---

## 1. 缺陷修复

### 1.1 缺陷 A：独立回测明细落库

**根因**：`replay_backtest()` 把 `db_path=None` 传给 `BacktestEngine`，
引擎内 `if self.db_path is not None` 守卫使公司行为明细不写；
但 `save_result()` / `_stamp_replay_record()` / attempt 登记走
`get_connection(None)` 的默认库，形成「记录落库、明细为空」。

**修复**（`app/replay/runner.py`）：

新增 `effective_db_path(db_path)`，在 `replay_backtest()` 与
`replay_validation()` 入口各解析一次，之后引擎、保存、标记、
attempt 登记全部复用同一个值。

```
db_path 非空 → 用它
db_path 为空 → settings.database_path
```

返回值保持 `Path` 类型（`get_connection` 需要 `.parent`）。
`replay_validation()` 一并处理，避免同类遗漏。

### 1.2 缺陷 B：市场环境分组回测凭证

**根因**：`_build_regime_payload()` 直接调 `audit.register_backtest()`，
没先 `register_run_evidence()`。3A.3.2.3.4.1 给 `register_backtest()`
加了凭证闸门，导致抛 `AuditError`，被外层 `except Exception` 吞掉，
regime 四项统计全变 `unavailable` 而 validation 仍记 `success`。

**修复**（`app/validation/runner.py`）：

1. 登记顺序改为：
   ```
   BacktestEngine 执行 → _require_formal() →
   register_run_evidence() → register_backtest() → 后续统计
   ```
2. `db_path` 为空时解析成 `settings.database_path`，与 `_run_backtest()` 一致。
3. 外层 `except` 增加：`AuditError` 一律向外抛，不再降级成
   `{"labels_available": False}`。只有非审计类异常
   （如预热数据缺失）才走降级返回。

**未做**：没有跳过审计、没有放宽 `register_backtest()` 校验、
没有伪造 run_id 或凭证。预热、分类、收益序列、NaN 缺失日处理逻辑均未改。

---

## 2. 追加式失效机制

### 2.1 新增关系表

```sql
CREATE TABLE replay_supersessions (
    supersession_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    superseded_attempt_id TEXT NOT NULL,
    superseded_record_id TEXT,
    replacement_attempt_id TEXT,
    replacement_record_id TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE UNIQUE INDEX idx_supersede_attempt ON replay_supersessions(superseded_attempt_id);
```

**关键设计**：

| 要求 | 实现 |
| --- | --- |
| 不删除旧记录 | 旧 attempt 行、旧结果行一律不清 |
| 不篡改旧 attempt | 没有任何 `UPDATE replay_attempts` 语句 |
| 保留原始执行状态 | 旧 attempt 的 `status` 仍是 `success` |
| 可追溯 | 关系记录含旧/新两侧 ID、原因、时间 |
| 不可覆盖 | `superseded_attempt_id` 唯一索引 |
| 新旧不同时算有效 | `find_success()` / `success_map()` 排除被取代的 attempt |

### 2.2 查询层联动

`find_success()` 与 `success_map()` 都加了
`NOT EXISTS (SELECT 1 FROM replay_supersessions WHERE superseded_attempt_id = ...)`，
因此被取代的旧结果不再算成功重放，重新执行不需要 `force`。

### 2.3 两条旧结果的失效标记

| 项 | Backtest | Validation |
| --- | --- | --- |
| source_id | `8412fc1cefb4437e` | `b3f1e2c89ebc4b95` |
| 旧 attempt | `2ecb1651d5a3473a` | `b1240a8c3d2847a0` |
| 旧结果 | `6d4045e45b5f4e0d` | `4d5da66a81da4d52` |
| 旧 attempt 状态 | `success`（**保留**） | `success`（**保留**） |
| 失效原因 | `missing_corporate_action_details` | `regime_audit_incomplete` |
| supersession_id | `3007249bf5b1411d` | `03fe5ff1a63e48de` |
| 新 attempt | `44e6f14f4185417d` | `8a05c4fa1e4d456b` |
| 新结果 | `a56ffe74f3ca48fb` | `c5505f0145e34bbd` |
| 闭环时间 | 2026-11-18T11:51:20 | 2026-11-18T11:58:xx |

两条旧结果**仍在库中可查**，报告能解释其为何不再作为有效证据。

---

## 3. 重新执行结果

### 3.1 Backtest `8412fc1cefb4437e`

| 项目 | 内容 |
| --- | --- |
| source_id | `8412fc1cefb4437e` |
| replay_attempt_id | `44e6f14f4185417d` |
| replay_record_id | `a56ffe74f3ca48fb` |
| source_input_hash | `5bd01d68a81b0a1b` |
| replay_input_hash | `b31e5344e810895b` |
| accounting_version | `ca-v2-receivable` |
| accounting_basis | `formal_receivable` |
| formal_valuation | `True` |
| corporate_action_digest | `9142ce65f4ade9203f45f6d71968f6ed8b6c0521cf00d6905be753db65853d98` |
| status | **success** |

**公司行为应用明细（3 条，完整）**

| action_id | code | action_type | effective_date | 份额前 | 份额后 | cash_delta |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 126 | 510300 | cash_distribution | 2024-01-19 | 289,600 | 289,600 | 19,982.40 |
| 140 | 510300 | cash_distribution | 2025-06-19 | 289,600 | 289,600 | 25,484.80 |
| 150 | 510300 | cash_distribution | 2026-01-20 | 289,600 | 289,600 | 35,620.80 |

**分红应收明细（3 条，完整）**

| action_id | record_date | ex_date | pay_date | shares_at_ex | cash_per_share | amount | status |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| 126 | 2024-01-17 | 2024-01-18 | 2024-01-23 | 289,600 | 0.069 | 19,982.40 | settled |
| 140 | 2025-06-17 | 2025-06-18 | 2025-06-27 | 289,600 | 0.088 | 25,484.80 | settled |
| 150 | 2026-01-16 | 2026-01-19 | 2026-01-27 | 289,600 | 0.123 | 35,620.80 | settled |

合计应收 81,088.00 元，与 `total_return` 增量
`0.2784258040548 - 0.19733780405479995 = 0.081088` **精确对应**。
三条全部 `settled`，`settled_at` 有值。

### 3.2 Validation `b3f1e2c89ebc4b95`（G9）

| 项目 | 内容 |
| --- | --- |
| source_id | `b3f1e2c89ebc4b95` |
| replay_attempt_id | `8a05c4fa1e4d456b` |
| replay_record_id | `c5505f0145e34bbd` |
| config_hash | `39bac25b0ec4ce91`（与源相同） |
| source_input_hash | `451bdcc990343464` |
| replay_input_hash | `a8669b514793eab7` |
| accounting_version | `ca-v2-receivable` |
| accounting_basis | `formal_receivable`（52 条内部回测全部） |
| formal_valuation | `1`（= True） |
| status | **success** |
| conclusion | 有条件通过 |

**regime 统计（4 项全部真实落库）**

| regime | status | samples | cumulative_return |
| --- | --- | ---: | ---: |
| bull | **ok** | 323 | +0.422566 |
| bear | **ok** | 26 | -0.022231 |
| range | **ok** | 97 | -0.150620 |
| unclassified | insufficient_sample | 0 | — |

`regime_grouping` 登记：`29e81b7cf8d7486c`，`status=success`，
`accounting_basis=formal_receivable`，`formal_valuation=1`。

**审计**

| 项 | 结果 |
| --- | --- |
| `audit_trace()` | **complete** |
| `audit_completeness()` | **True**，problems **[]** |

### 3.3 明细汇总对照

| 项 | 源记录 | 旧轮（失效） | 新轮 |
| --- | ---: | ---: | ---: |
| 内部回测登记 | 0 | 51 | **52** |
| 公司行为应用事件 | 0 | 144 | **151** |
| 分红应收笔数 | 0 | 129 | **135** |
| 分红应收金额 | 0.00 | 459,046.11 | **475,647.38** |
| 已结清笔数 | 0 | 129 | **135** |

新轮比旧轮多 1 条内部回测、7 个应用事件、6 笔应收——正是缺陷 B 修复后
补上的 `regime_grouping` 及其公司行为明细。

`run_role` 分布对比：

| role | 旧轮 | 新轮 |
| --- | ---: | ---: |
| `regime_grouping` | **0** | **1** |
| 其余 8 类 | 51 | 51 |

---

## 4. 绩效对照

### 4.1 Backtest

| 指标 | 源 | 旧轮 | 新轮 |
| --- | ---: | ---: | ---: |
| `total_return` | 0.197338 | 0.278426 | **0.278426** |
| `cagr` | 0.068192 | 0.094140 | **0.094140** |
| `max_drawdown` | -0.201356 | -0.190868 | **-0.190868** |
| 成交笔数 | 1 | 1 | **1** |
| 总成本 | 748.5959 | 748.5959 | **748.5959** |

新轮与旧轮**完全一致**——缺陷 A 只影响明细落库，不影响绩效计算。

### 4.2 Validation G9

| 指标 | 源 | 旧轮 | 新轮 |
| --- | ---: | ---: | ---: |
| IS `total_return` | 0.041007 | 0.041007 | **0.041007** |
| IS `cagr` | 0.010517 | 0.010517 | **0.010517** |
| IS `max_drawdown` | -0.198785 | -0.198785 | **-0.198785** |
| OOS `total_return` | 0.178324 | 0.181437 | **0.181437** |
| OOS `cagr` | 0.097151 | 0.098787 | **0.098787** |
| OOS `max_drawdown` | -0.170868 | -0.168672 | **-0.168672** |
| `best_param` | 250 | 250 | **250** |
| `window_count` | 8 | 8 | **8** |
| conclusion | 有条件通过 | 不通过 | **有条件通过** |

新轮与旧轮**绩效完全一致**。conclusion 从「不通过」回到「有条件通过」，
原因是 regime 分组统计恢复后，`decide_conclusion()` 的输入条件完整了。

### 4.3 G9 的 config_hash 与 input_hash

| 项 | 源 | 新轮 |
| --- | --- | --- |
| `config_hash` | `39bac25b0ec4ce91` | `39bac25b0ec4ce91`（**相同**） |
| `input_hash` | `451bdcc990343464` | `a8669b514793eab7`（**不同**） |

**同一 `config_hash` 不代表同一数据证据。** `config_hash` 只覆盖
28 个验证参数；`input_hash` 还覆盖实际参与的数据（行情快照、指标版本、
公司行为事件集）。3A.3.2.3.4 之后公司行为事件参与计算，数据侧指纹必然变化。

---

## 5. 新增回归测试（14 项）

文件：`tests/test_replay_fix_3a3_2_3_6_1.py`

### 5.1 缺陷 A（6 项）

| 测试 | 覆盖 |
| --- | --- |
| `test_effective_db_path_defaults_to_settings` | `db_path=None` → 正式库路径 |
| `test_effective_db_path_keeps_explicit` | 显式传临时库 → 用它 |
| `test_replay_backtest_writes_corporate_action_details` | 应用与应收明细真实落库，金额一致、状态 settled |
| `test_replay_backtest_details_not_cross_database` | 明细、记录、attempt 全在同一库，另一库 0 行 |

### 5.2 缺陷 B（5 项）

| 测试 | 覆盖 |
| --- | --- |
| `test_regime_registers_evidence_before_link` | 监控调用顺序，断言 `["evidence", "link"]`，且关联落库、凭证落库 |
| `test_regime_missing_validation_id_fails` | 无 `validation_id` → 抛 `AuditError` |
| `test_regime_evidence_failure_propagates` | 凭证登记失败 → 抛 `AuditError`，不降级 |
| `test_regime_link_failure_propagates` | 关联登记失败 → 抛 `AuditError` |
| `test_regime_stats_persisted_and_audit_passes` | regime 4 行落库、不全为 unavailable、`audit_completeness` 不再报 regime 缺失 |

### 5.3 追加式失效（5 项）

| 测试 | 覆盖 |
| --- | --- |
| `test_supersession_marks_old_attempt_without_touching_it` | 旧 attempt 全字段前后完全相同，`status` 仍 `success` |
| `test_superseded_attempt_not_counted_as_success` | `find_success()` 返回 None，`success_map()` 不含该源 |
| `test_superseded_replay_can_run_again_without_force` | 不用 force 也能重跑，新 ID 不同，关系闭环 |
| `test_supersession_idempotent` | 重复标记返回同一 ID，不产生重复行 |
| `test_both_reasons_recorded_for_validation` | 两个原因常量正确 |

### 5.4 测试改造说明

旧的 `_seed_market` 只有 80 天行情，regime 的 MA 预热需求
（`REGIME_MA_WINDOW=250`）无法满足，`build_regime_series` 直接抛
`RegimeError`。新 fixture `_regime_fixture()` 用 600 个交易日、
OOS 从第 100 日起，保证预热充分、样本量超 `MIN_REGIME_SAMPLES=20`。
指标行的 `calculation_version` 也改为从 `ValidationConfig().indicator_version`
动态取，避免与真实配置不一致导致「没有该指标版本的数据」。

---

## 6. 数据库前后对照

### 6.1 核心表行数

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 64 | 117 | +53 |
| `validation_runs` | 55 | 56 | +1 |
| `replay_attempts` | 13 | 15 | +2 |
| `replay_supersessions` | 0（新建） | 2 | +2 |
| `validation_backtest_runs` | 412 | 464 | +52 |
| `validation_regime_stats` | 32 | 36 | +4 |
| `validation_stress` | 371 | 378 | +7 |
| `validation_windows` | 423 | 431 | +8 |
| `validation_grid` | 384 | 392 | +8 |
| `corporate_action_applications` | 6,910 | 7,194 | +284 |
| `dividend_receivables` | 3,274 | 3,529 | +255 |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_versions` | 704 | 704 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |
| `etf_indicator_daily` | 350,292 | 350,292 | **0** |

`backtest_runs` 的 +53 = 51 条 G9 内部回测凭证 + 1 条 `regime_grouping` 凭证
+ 1 条 backtest 重放记录。

### 6.2 数据安全

| 项 | 执行前 | 执行后 |
| --- | --- | --- |
| `PRAGMA integrity_check` | ok | **ok** |
| 行情指纹 | `d54727c0…ac49` | **未变** |
| 行情行数 | 116,609 | 116,609 |
| 公司行为事件 | 166 | 166 |
| 公司行为版本 | 704 | 704 |
| 指标行数 | 350,292 | 350,292 |

### 6.3 源记录未改动

| source_id | `input_hash` 前 | 后 | `accounting_version` |
| --- | --- | --- | --- |
| `8412fc1cefb4437e` | `5bd01d68a81b0a1b` | **未变** | `legacy_corporate_action_accounting` |
| `b3f1e2c89ebc4b95` | `451bdcc990343464` | **未变** | `legacy_corporate_action_accounting` |

### 6.4 未执行其他 source_id

2026-11-18T11:50 之后新增的 attempt 只有两条：

```
44e6f14f4185417d  8412fc1cefb4437e  success
8a05c4fa1e4d456b  b3f1e2c89ebc4b95  success
```

G7 / G8 / G1 / G2 / G3 / G4 / G5 / G6 以及两条 P0 记录均未触碰。

### 6.5 旧记录保留核验

| 旧结果 | 是否仍在库 | 旧 attempt 状态 | 是否被统计为有效重放 |
| --- | --- | --- | --- |
| `6d4045e45b5f4e0d` | **是** | `success`（原样） | 否（已被替代） |
| `4d5da66a81da4d52` | **是** | `success`（原样） | 否（已被替代） |

---

## 7. 测试与检查

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 专项测试 | `pytest tests/test_replay_fix_3a3_2_3_6_1.py` | **14 passed**，16.48 秒 |
| 重放相关旧测 | `pytest tests/test_replay_3a3_2_3_1.py tests/test_replay_gate_3a3_2_3_2.py` | **42 passed** |
| 审计相关旧测 | `pytest tests/test_validation_audit_3a3_2_3_4.py` | **106 passed** |
| 全量 pytest | `pytest -q` | **702 passed / 0 failed / 0 skipped / 0 xfail**，269.53 秒 |
| API smoke | `scripts/smoke_validation_api.py` | `SMOKE_FAILED: 无` |
| AppTest `3_回测.py` | Streamlit AppTest | exception 0 / error 0 / df 5 / metric 5 |
| AppTest `4_策略验证.py` | Streamlit AppTest | exception 0 / error 0 / df 8 / metric 7 |
| `PRAGMA integrity_check` | — | **ok** |

基线 688 → **702**（+14），全部为本阶段新增。

---

## 8. 边界声明

| 禁止项 | 执行情况 |
| --- | --- |
| 修改历史源记录 | 未修改（`input_hash` 未变） |
| 修改行情或公司行为事件数据 | 未修改（行数与指纹均未变） |
| 修改策略 / 撮合 / 会计 / 绩效算法 | 未修改 |
| 修改原始历史 attempt 伪造执行 | 未修改（旧 attempt 全字段原样） |
| 删除旧回测或验证记录 | 未删除（两条旧结果仍可查） |
| 重放 G7 / G8 / G1 | 未执行 |
| 重放 G2 / G3 / G4 / G5 / 其他 | 未执行 |
| 重复执行两条 P0 记录 | 未执行 |
| 使用 force | **未使用**（两条 `force=False`） |
| 跳过审计 / 放宽校验 / 伪造 run_id | 未做 |
| 提交数据库到公开 GitHub | 未提交（快照只在本地） |

---

## 9. 完成条件核对

| # | 条件 | 状态 | 证据 |
| ---: | --- | --- | --- |
| 1 | 缺陷 A 修复并有真实回归测试 | ✅ | §1.1 + 4 项测试（含跨库检查） |
| 2 | 缺陷 B 修复并有真实回归测试 | ✅ | §1.2 + 5 项测试（含顺序监控） |
| 3 | 两条旧结果保留且明确标记已被替代 | ✅ | §2.3，旧 attempt 状态仍 `success` |
| 4 | 两条新结果均新 attempt + 新 result_id | ✅ | `44e6f14f…`/`a56ffe74…`、`8a05c4fa…`/`c5505f01…` |
| 5 | Backtest 公司行为明细完整 | ✅ | 3 应用 + 3 应收，金额/份额/日期/action_id 逐笔核验 |
| 6 | Validation 市场环境分组统计完整 | ✅ | bull 323 / bear 26 / range 97 全部 `ok` |
| 7 | 两条新结果正式会计口径正确 | ✅ | 均 `ca-v2-receivable` / `formal_receivable` / `True` |
| 8 | `audit_trace` 与 `audit_completeness` 通过 | ✅ | `complete` / `True`，problems `[]` |
| 9 | 源记录未改变 | ✅ | 两个 `input_hash` 前后相同 |
| 10 | 行情和公司行为数据未改变 | ✅ | 指纹未变，行数未变 |
| 11 | 全量测试通过 | ✅ | 702 passed |
| 12 | 报告 / README / CHANGELOG 一致 | ✅ | 全部 702 |

---

## 10. 交付物

| 项 | 值 |
| --- | --- |
| 执行前备份 | `data/backups/fund_agent_pre_3a3_2_3_6_1_20261118.db`，275,066,880 字节，SHA256 `c53858bfc24c9e00442b8e309fa5fba45433b30dd2e7474dab539161b18cdac3` |
| 全量测试 | 702 passed / 0 failed / 0 skipped，269.53 秒 |
| 新增测试 | +14 |
| `integrity_check` | ok |
| 行情指纹 | `d54727c0…ac49` 未变 |
| 执行后快照 | `data/backups/fund_agent_post_3a3_2_3_6_1_20261118.db`，275,513,344 字节，SHA256 `e27a2b1f101bd86847764cb0b306961b7cc58ae0af4d23355fff3c0ffd8b9266` |
