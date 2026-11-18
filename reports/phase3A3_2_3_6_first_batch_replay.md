# 阶段3A.3.2.3.6 第一批历史记录受控重放

- 基线 HEAD：`65115e869b79e237a6df8e80246f51df4756c7c7`
- 执行日期：2026-11-18
- **执行状态：中途暂停。** 计划 5 条，完成 2 条，剩余 3 条因代码层面缺陷暂停。

---

## 0. 结论摘要

| 项 | 数量 |
| --- | ---: |
| 计划重放 | 5 |
| 实际执行 | 2 |
| 成功 | 2 |
| 失败 | 0 |
| 因缺陷暂停 | **3** |

前 2 条（`8412fc1cefb4437e`、`b3f1e2c89ebc4b95`）**都跑成功了**，
但执行过程中发现**两个代码层面缺陷**，按任务书「遇到代码或基础设施层面的异常，
立即暂停后续重放」的要求，第 3 条起停止执行。

两个缺陷都不是源记录本身的数据问题，而是当前正式代码的路径缺陷：

| 缺陷 | 影响 | 严重度 |
| --- | --- | --- |
| A：`replay_backtest()` 不落公司行为明细 | backtest 重放记录明细表为空 | 中 |
| B：`_build_regime_payload()` 缺存在性凭证 | validation 的 regime 分组统计全为 unavailable | **高** |

---

## 1. 执行前检查

### 1.1 五条源记录状态

| source_id | 类型 | 分类 | 可重放 | 已有成功重放 | 缺失参数 |
| --- | --- | --- | --- | --- | --- |
| `8412fc1cefb4437e` | backtest | `legacy` | ✅ | 无 | 无 |
| `b3f1e2c89ebc4b95` | validation G9 | `legacy` | ✅ | 无 | 无 |
| `c5589f7dcd1a4a5d` | validation G7 | `legacy` | ✅ | 无 | 无 |
| `838a58fa5f3b4025` | validation G8 | `legacy` | ✅ | 无 | 无 |
| `7d884a1a03d94915` | validation G1 | `legacy` | ✅ | 无 | 无 |

五条全部 `replayable=True`、`params_proof=proven`、均无既有成功重放，
不需要跳过任何一条，也不需要 force。

### 1.2 数据库前置状态

| 表 | 执行前 |
| --- | ---: |
| `backtest_runs` | 12 |
| `validation_runs` | 54 |
| `replay_attempts` | 11 |
| `validation_backtest_runs` | 361 |
| `validation_stress` | 364 |
| `validation_windows` | 415 |
| `validation_grid` | 376 |
| `corporate_actions` | 166 |
| `corporate_action_versions` | 704 |
| `etf_daily_prices` | 116,609 |
| `etf_indicator_daily` | 350,292 |

- `PRAGMA integrity_check`：**ok**
- 行情指纹：`d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`，116,609 行
- 备份：`data/backups/fund_agent_pre_3a3_2_3_6_20261118.db`
  274,653,184 字节，SHA256 `c61cb3bf87b34cc31303df59fceec3eebdd53a89aec6b369524c1df75389e14e`

---

## 2. 逐条执行结果

### 2.1 第 1 条：`8412fc1cefb4437e`（backtest buy_and_hold）

| 项目 | 内容 |
| --- | --- |
| source_id | `8412fc1cefb4437e` |
| replay_attempt_id | `2ecb1651d5a3473a` |
| replay_record_id | `6d4045e45b5f4e0d` |
| config_hash | 无（backtest 不用 config_hash） |
| source_input_hash | `5bd01d68a81b0a1b` |
| replay_input_hash | `b31e5344e810895b` |
| accounting_version | `ca-v2-receivable` ✅ |
| accounting_basis | `formal_receivable` ✅ |
| formal_valuation | `True` ✅ |
| audit_trace | 不适用（`run_scope=standalone`，用户回测不进 validation 审计链） |
| audit_completeness | 不适用（同上） |
| status | **success** |
| reason | — |

**参数来源**：全部来自源记录 `config_json`，`params_source` 逐项为 `recorded`：

```
weights={}, start_date=2024-01-02, end_date=2026-11-09,
initial_cash=1000000.0, execution_price=open,
costs={commission_rate:0.00025, min_commission:5.0, slippage_bps:5.0,
       slippage_fixed:0.0, stamp_duty_rate:0.0, transfer_fee_rate:0.0},
max_defer_days=3, risk_free_rate=0.0, annualization=252,
rebalance_tolerance=0.02, cash_shortfall_policy=reduce,
allow_partial_fill=false, instrument_overrides={}, lot_size_override=null
```

无一字段走默认值或猜测。

**绩效对照**

| 指标 | 源记录 | 新记录 | 差异 |
| --- | ---: | ---: | ---: |
| `total_return` | 0.197338 | 0.278426 | +0.081088 |
| `cagr` | 0.068192 | 0.094140 | +0.025948 |
| `max_drawdown` | -0.201356 | -0.190868 | +0.010488 |
| `sharpe` | None | None | 源记录本身无此值 |

**差异完全由两阶段分红会计解释**：新记录按 `ca-v2-receivable` 在除息日确认应收，
源记录按旧口径不确认。三次分红合计 81,088.00 元：

| 除息日 | 每份 | 持仓 | 应收 |
| --- | ---: | ---: | ---: |
| 2024-01-18 | 0.069 | 289,600 | 19,982.40 |
| 2025-06-18 | 0.088 | 289,600 | 25,484.80 |
| 2026-01-19 | 0.123 | 289,600 | 35,620.80 |

收益差 `0.081088 × 1,000,000 = 81,088.00` 元，**与分红合计精确相等**。
这是口径差异，不是计算错误。

**明细对照**

| 项 | 源 | 新 |
| --- | ---: | ---: |
| 成交笔数 | 1 | 1 |
| 总成本 | 748.5959 | 748.5959 |
| 公司行为应用数 | 0 | **0** ⚠️ |
| 分红应收笔数 | 0 | **0** ⚠️ |

明细为 0 是**缺陷 A** 的表现，详见 §3.1。

### 2.2 第 2 条：`b3f1e2c89ebc4b95`（validation G9）

| 项目 | 内容 |
| --- | --- |
| source_id | `b3f1e2c89ebc4b95` |
| replay_attempt_id | `b1240a8c3d2847a0` |
| replay_record_id | `4d5da66a81da4d52` |
| config_hash | `39bac25b0ec4ce91`（与源记录相同 ✅） |
| source_input_hash | `451bdcc990343464` |
| replay_input_hash | `a8669b514793eab7`（不同，见下） |
| accounting_version | `ca-v2-receivable` ✅ |
| accounting_basis | `formal_receivable`（见 `validation_backtest_runs`，51 条全部如此）✅ |
| formal_valuation | `1`（= True）✅ |
| audit_trace | `incomplete` ⚠️ |
| audit_completeness | `complete=False`，problems 1 条 ⚠️ |
| status | **success** |
| reason | — |

**参数恢复**：`config_hash` 完全命中，`resolved_params` 逐项来自哈希反证：

```
strategy=ma_trend 1.0.0, is=2021-01-04~2024-12-31, oos=2025-01-02~2026-11-09,
ma_window_grid=[5,10,20,30,60,120,250], wf_grid=[5,20,60],
pool_mode=representative, 6 只 ETF,
initial_cash=1000000.0, commission_rate=0.00025, min_commission=5.0,
slippage_bps=5.0, rebalance_tolerance=0.02, max_defer_days=3,
risk_free_rate=0.0, annualization=252, train_months=24, test_months=6,
step_months=6, regime_proxy_code=510300, regime_ma_window=250,
min_validation_days=120, exclude_insufficient=True, min_coverage_ratio=0.95,
indicator_version=v1.0.2-30b821a1af15
```

**绩效对照**

| 指标 | 源记录 | 新记录 | 差异 |
| --- | ---: | ---: | ---: |
| IS `total_return` | 0.041007 | 0.041007 | **0** |
| IS `cagr` | 0.010517 | 0.010517 | **0** |
| IS `max_drawdown` | -0.198785 | -0.198785 | **0** |
| OOS `total_return` | 0.178324 | 0.181437 | +0.003113 |
| OOS `cagr` | 0.097151 | 0.098787 | +0.001636 |
| OOS `max_drawdown` | -0.170868 | -0.168672 | +0.002195 |
| `best_param` | 250 | 250 | 同 |
| `window_count` | 8 | 8 | 同 |

**样本内完全一致（差值 0）**，样本外差 0.31%——来自两阶段分红口径。

**明细对照**

| 项 | 源 | 新 |
| --- | ---: | ---: |
| 内部回测登记 | 0（生成于凭证体系之前） | 51 |
| 公司行为应用事件 | 0 | 144 |
| 分红应收笔数 | 0 | 129 |
| 分红应收金额 | 0.00 | 459,046.11 |
| 已结清笔数 | 0 | 129 |

新记录的明细**完整充足**（这是 3A.3.2.3.4.1 引入凭证体系的直接效果）。

**唯一 problem**：`regime_grouping 登记 0 条，期望 1 条` → 缺陷 B，详见 §3.2。

### 2.3 第 3~5 条：未执行

| source_id | 预期 | 实际 |
| --- | --- | --- |
| `c5589f7dcd1a4a5d`（G7） | 执行 | **未执行**，`replay_attempts` 0 条 |
| `838a58fa5f3b4025`（G8） | 执行 | **未执行**，`replay_attempts` 0 条 |
| `7d884a1a03d94915`（G1） | 执行 | **未执行**，`replay_attempts` 0 条 |

原因：第 2 条暴露出缺陷 B（regime 数据全空），任何 validation 重放都会撞上，
继续执行只会复制同一个缺陷 3 次。

---

## 3. 两个代码缺陷

### 3.1 缺陷 A：`replay_backtest()` 不落公司行为明细

**现象**

新记录 `6d4045e45b5f4e0d` 的 `summary_json.notes` 写着：

```
公司行为：已应用 3 条事件（official_confirmed 3 / secondary_confirmed 0）
```

但明细表：

```
corporate_action_applications WHERE run_id='6d4045e45b5f4e0d'  -> 0 行
dividend_receivables         WHERE run_id='6d4045e45b5f4e0d'  -> 0 行
```

**根因**

`app/replay/runner.py::replay_backtest()` 第 203 行：

```python
engine = BacktestEngine(config, strategy, db_path=db_path)   # db_path=None
```

`replay_backtest()` 默认 `db_path=None`（CLI 也不传），而引擎内两处守卫是：

```python
if self._run_id_for_actions and self.db_path is not None:
    ca.record_application(...)
    ca.save_receivable(...)
```

`db_path is None` → 明细不写。但 `save_result()` 和 `_stamp_replay_record()`
都用 `db_path=None` 走 `settings.database_path` 默认值，**记录落到正式库了**。
同一路径下「记录落库、明细不落库」不一致。

**验证**

- 不传 `db_path`：app=0、recv=0（当前正式库实际表现）
- 传 `db_path=<临时库>`：app=3、recv=3（明细正常）

`app/validation/runner.py::_run_backtest()` 在第 3A.3.2.3.4 阶段已修过同一问题
（`detail_db = db_path if db_path is not None else _settings.database_path`），
但 `replay_backtest()` 这条路径**没同步修**。

**影响面**

只影响 `replay_backtest()` 的 backtest 重放。validation 重放走 `_run_backtest()`，
不受影响（第 2 条 144 条应用事件正常落库可证）。

**是否伪造成功**：否。`accounting_basis` / `formal_valuation` / `input_hash`
全部真实，只是逐笔明细缺失。但按 `audit_completeness` 口径，这属于明细不可追溯。

### 3.2 缺陷 B：`_build_regime_payload()` 缺存在性凭证（**高危**）

**现象**

新记录 `4d5da66a81da4d52` 的 `validation_regime_stats` 四行全部 `unavailable`：

| regime | 新记录 | 对照 `aad7935a2bac4cc4` |
| --- | --- | --- |
| bull | `unavailable`, samples=None | `ok`, 321 |
| bear | `unavailable`, samples=None | `ok`, 24 |
| range | `unavailable`, samples=None | `ok`, 97 |
| unclassified | `unavailable`, samples=None | `insufficient_sample`, 0 |

**根因**

`app/validation/runner.py` 第 694-699 行：

```python
engine = BacktestEngine(oos_cfg, oos_strategy, db_path=db_path)
oos_result = engine.run(codes, indicator_version=config.indicator_version)
_require_formal(oos_result, "市场环境分组回测")
audit.register_backtest(              # ← 直接登记，没有先落凭证
    oos_result, role=audit.ROLE_REGIME,
    scenario_key=config.regime_proxy_code, db_path=db_path,
)
```

而 `app/validation/audit.py::register_backtest()` 在 3A.3.2.3.4.1 阶段加了闸门：

```python
evidence = conn.execute(
    "SELECT run_scope FROM backtest_runs WHERE run_id=?", (run_id,)).fetchone()
if evidence is None:
    raise AuditError(
        f"backtest_run_id={run_id} 在 backtest_runs 中不存在，"
        f"拒绝登记（关联表不得凭空指向未发生的回测）")
```

`register_backtest()` 之前必须先 `register_run_evidence()`——
`_run_backtest()` 已经这么做了（第 3A.3.2.3.4.1 阶段同步修改），
但 `_build_regime_payload()` 是**独立构造引擎**，没走 `_run_backtest()`，
因此漏掉了凭证登记。

登记失败被外层 `except Exception` 捕获，返回
`{"labels_available": False, "error": "..."}`，regime 数据全空，
但 validation 本身仍记为 `success`。

**复现验证**

| 场景 | 结果 |
| --- | --- |
| 无审计上下文调用 `_build_regime_payload` | `缺少 validation_id，拒绝登记内部回测` |
| 有上下文但 validation_id 不存在 | `validation_id=xxx 不存在，拒绝登记内部回测` |
| 有上下文且 validation 存在 | `backtest_run_id=xxx 在 backtest_runs 中不存在，拒绝登记（关联表不得凭空指向未发生的回测）` |

**时间线证据**

- 3A.3.2.3.4.1 提交 `5a4af82`：2026-11-17 09:15:30
- 最后一次成功登记 `regime_grouping`：2026-11-16 **16:10:40**（早于该提交）

即：**凭证闸门上线后，所有新的 validation 重放都会丢失 regime 数据**。
这是 3A.3.2.3.4.1 引入的回归，不是本阶段造成的。

**影响面**

- 所有在 3A.3.2.3.4.1 之后执行的 validation 都会丢 regime
- `audit_completeness()` 会判 `incomplete`（唯一 problem 就是这一条）
- 若不加修复，接下来 3 条 validation 重放会 100% 复制同一缺陷

**是否伪造成功**：**接近**。记录状态 `success`、绩效指标真实，
但 regime 分组统计缺失且未在 `status` 上体现，只在 `audit_completeness`
里以 problem 形式暴露。

---

## 4. 数据库前后对照

### 4.1 表行数

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 12 | 64 | **+52** |
| `validation_runs` | 54 | 55 | **+1** |
| `replay_attempts` | 11 | 13 | **+2** |
| `validation_backtest_runs` | 361 | 412 | **+51** |
| `validation_regime_stats` | 28 | 32 | **+4** |
| `validation_stress` | 364 | 371 | **+7** |
| `validation_windows` | 415 | 423 | **+8** |
| `validation_grid` | 376 | 384 | **+8** |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_versions` | 704 | 704 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |
| `etf_indicator_daily` | 350,292 | 350,292 | **0** |

`backtest_runs` 的 +52 里有 51 条是 G9 validation 的内部回测凭证
（`run_scope=validation_internal`），1 条是 backtest 重放记录
（`run_scope=standalone`）。

### 4.2 完整性

| 项 | 执行前 | 执行后 |
| --- | --- | --- |
| `PRAGMA integrity_check` | ok | **ok** |
| 行情指纹 | `d54727c0…ac49` | **未变** |
| 行情行数 | 116,609 | 116,609 |
| 公司行为事件 | 166 | 166 |
| 公司行为版本 | 704 | 704 |

**行情与公司行为数据零改动**，符合任务书要求。

### 4.3 源记录未被改动

| 源记录 | `input_hash` 执行前 | 执行后 |
| --- | --- | --- |
| `8412fc1cefb4437e` | `5bd01d68a81b0a1b` | `5bd01d68a81b0a1b` |
| `b3f1e2c89ebc4b95` | `451bdcc990343464` | `451bdcc990343464` |
| `c5589f7dcd1a4a5d` | 未触碰 | 未触碰 |
| `838a58fa5f3b4025` | 未触碰 | 未触碰 |
| `7d884a1a03d94915` | 未触碰 | 未触碰 |

### 4.4 新记录追溯性

| 新记录 | source_id | 追溯方式 |
| --- | --- | --- |
| `6d4045e45b5f4e0d` | `8412fc1cefb4437e` | `replay_attempts.attempt_id=2ecb1651d5a3473a` |
| `4d5da66a81da4d52` | `b3f1e2c89ebc4b95` | `replay_attempts.attempt_id=b1240a8c3d2847a0` |

两条 `replay_attempts` 均 `status=success`，`source_input_hash` /
`replay_input_hash` / `replay_accounting_version` 齐全。

---

## 5. G1 专项：同 config_hash 不同 input_hash

任务书要求特别记录 G1 的源记录与新记录 `input_hash`。

由于 G1（`7d884a1a03d94915`）**未执行**，此处给出执行前已知的对照事实：

| 项 | `7d884a1a03d94915`（G1） | `b3f1e2c89ebc4b95`（G9，已执行） |
| --- | --- | --- |
| `config_hash` | `b6b1babace517bdc` | `39bac25b0ec4ce91` |
| 源 `input_hash` | `3e064b6673929193` | `451bdcc990343464` |
| 执行后新 `input_hash` | 未执行 | `a8669b514793eab7` |

**已验证的事实**：G9 的 `config_hash` 与源记录**完全相同**，
但 `input_hash` 从 `451bdcc990343464` 变成 `a8669b514793eab7`。
这印证了任务书的判断——**相同 `config_hash` 不代表数据指纹必然相同**。

原因：`config_hash` 只覆盖验证配置（28 个参数），
`input_hash` 还覆盖实际参与的数据（行情快照、指标版本、公司行为事件集）。
3A.3.2.3.4 之后新增了公司行为事件参与，数据侧指纹必然变化。

G1 执行时预期同样会出现 `input_hash` 变化，届时需照此记录。

---

## 6. 全量测试

```
688 passed, 1 warning in 269.53s (0:04:29)
```

| 项 | 数量 |
| --- | ---: |
| 通过 | **688** |
| 失败 | 0 |
| 跳过 | 0 |
| xfail | 0 |

与上一阶段终值一致——本阶段未修改任何代码，因此测试数量不变。
这也从侧面印证：两个缺陷**已存在的测试没有覆盖到**。

---

## 7. 未执行的 3 条：建议处置

| 记录 | 建议 |
| --- | --- |
| `c5589f7dcd1a4a5d`（G7） | 待缺陷 B 修复后执行 |
| `838a58fa5f3b4025`（G8） | 待缺陷 B 修复后执行 |
| `7d884a1a03d94915`（G1） | 待缺陷 B 修复后执行 |

三条**均未产生任何 attempt**，数据库里没有它们的痕迹，重跑成本为零。

### 7.1 是否建议现在就修

缺陷 B 是 3A.3.2.3.4.1 引入的回归，属于「代码层面异常」，
按任务书要求应「立即暂停后续重放，先报告原因」。

修复范围（如果批准）：

| 文件 | 改动 |
| --- | --- |
| `app/validation/runner.py` | `_build_regime_payload()` 在 `register_backtest()` 之前补 `register_run_evidence()` |
| `app/replay/runner.py` | `replay_backtest()` 把 `db_path` 解析成真实库路径再传给引擎 |

两处都是最小改动（各 2~3 行），不动策略、撮合、会计、指标算法。

**但缺陷 A 已产生的 `6d4045e45b5f4e0d` 和缺陷 B 已产生的 `4d5da66a81da4d52`
怎么处理，需要明确决定：**

| 选项 | 后果 |
| --- | --- |
| 保留现状 | 两条记录明细/regime 缺失，`audit_completeness` 判 incomplete |
| 删除后重跑 | 会丢失已产生的 attempt 记录，且 `replay_attempts` 已有 success 行 |
| 保留并标注 | 在记录里写明缺失原因，重放时用新 ID |

本轮**未做任何处理**，两条记录原样保留，等验收决定。

---

## 8. 边界声明

| 禁止项 | 执行情况 |
| --- | --- |
| 修改源历史记录 | 未修改（`input_hash` 前后相同） |
| 猜测或补造历史参数 | 未猜（参数全部来自 `config_json` / `config_hash` 反证） |
| 修改策略 / 撮合 / 会计 / 指标算法 | 未修改 |
| 修改行情 / 公司行为数据 | 未修改（指纹未变） |
| 重放两条已完成的 P0 记录 | 未重放（`32aead3291734f91` / `c46fa37b932944c2` 未触碰） |
| 执行 G2/G3/G4/G5/G6 或其他未列出记录 | 未执行 |
| 使用 force | **未使用**（两条 `force=False`） |
| 把代表记录的成功标记为同配置其他记录已重放 | 未做（G2/G3 等同 `b1de1d7323a8a35d`/`177a329b6fd72cec` 的记录完全未动） |
| 继续执行第二批 | 未执行 |
| 进入 3A.3.3 / 3B | 未进入 |

---

## 9. 待验收决定事项

1. **缺陷 A / B 是否现在修。** 两处都是最小改动，但不属于本阶段授权范围。
2. **已产生的两条记录如何处置。** 保留 / 删除重跑 / 保留并标注。
3. **`audit_completeness` 判 `incomplete` 是否可接受。**
   G9 新记录的唯一 problem 是缺陷 B 造成的 regime 缺失；
   修复后重跑可消除，但需要再消耗一次 4.5 分钟的运行。
4. **剩余 3 条是否等修复后再跑。** 建议如此，否则会复制同一缺陷 3 次。
