# 阶段3A.3.2.3.4 验证内部回测与公司行为审计追溯体系

- 基线 HEAD：`55a88b22824c43038bc48fb520a65bae29955d4a`
- 执行日期：2026-11-16
- 范围：只补审计追溯，未改策略算法、公司行为会计规则、撮合规则、绩效指标算法

---

## 1. 修改前调用路径清单

`app/validation/runner.py` 内部共有 **9 类** BacktestEngine 执行，全部梳理如下。

| # | 类型 | 代码位置 | 是否用引擎 | 独立 run_id | 应用事件 | 写应用表 | 写应收表 | 有 input_hash | 过 `_require_formal()` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 样本内参数网格 | `_run_validation_unlocked` L377-390 | 是（经 `_run_backtest`） | 是 | 是 | 是 | 是 | 是 | 是 |
| 2 | 样本外正式回测 | L394-402 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| 3 | WF 训练回测 | L424-436 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| 4 | WF 测试回测 | L443-452 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| 5 | 市场环境分组回测 | `_build_regime_payload` L592 | **是（直接 new BacktestEngine）** | 是 | 是 | 是 | 是 | 是 | 是 |
| 6 | 基准回测 | `_build_benchmarks_rows` L849 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| 7 | 成本/滑点压力 | `_build_stress_rows` L863 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| 8 | sparse_data 压力 | `_run_data_stress` L920 | 是（**跑在副本库**） | 是 | 是 | 写**副本库** | 写**副本库** | 是 | 是 |
| 9 | insufficient 压力 | `_run_data_stress` L944 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |

### 1.1 修改前的持久化缺口

| 缺口 | 后果 |
| --- | --- |
| validation_runs 无任何内部 backtest run_id 字段 | validation_id → run_id 完全断链 |
| 明细表按 run_id 存 264 个不同 run | 从 validation_id 查不到任何明细 |
| validation_summary 无 regime 分组 | 市场环境结果丢失，只剩一句汇总 |
| `_run_backtest()` 未解析 `db_path`，传 None 时引擎走 `if self.db_path is not None` 守卫 | **validation 内部回测根本不写公司行为明细** |
| `BacktestResult.run_id` 与 `engine._run_id_for_actions` **不是同一个 UUID** | 即便有明细也关联错 |

最后两条是本次审查新发现的**真实缺陷**，不是设计推测：

```
result.run_id        = 47a7006f17d04d1f
engine._run_id_for_actions = 828c263dc1384bf2   ← 明细表写的是这个
```

---

## 2. 数据库结构变化

### 2.1 新增表 `validation_backtest_runs`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | 自增 |
| `validation_id` | TEXT NOT NULL | 父 validation |
| `backtest_run_id` | TEXT NOT NULL | 内部回测 run_id（真实存在） |
| `run_role` | TEXT NOT NULL | 9 类角色之一 |
| `scenario_key` | TEXT | 参数档位 / 窗口 / 压力场景 |
| `strategy_name` / `strategy_version` | TEXT | 策略标识 |
| `strategy_params_json` | TEXT | 策略参数 |
| `start_date` / `end_date` | TEXT | 回测区间 |
| `indicator_version` / `initial_cash` / `codes_json` | | 运行配置 |
| `accounting_basis` | TEXT | 独立记录会计口径 |
| `formal_valuation` | INTEGER | 0/1 |
| `input_hash` | TEXT | 可追溯输入指纹 |
| `corporate_action_digest` | TEXT | 事件集指纹 |
| `applied_action_count` | INTEGER | 应用事件数 |
| `receivable_count` / `receivable_amount` | INTEGER / REAL | 应收笔数与金额 |
| `settled_count` / `settled_amount` | INTEGER / REAL | 到账笔数与金额 |
| `status` | TEXT NOT NULL | success / failed |
| `reason` | TEXT | 失败原因或明细位置说明 |
| `created_at` | TEXT NOT NULL | 登记时间 |

约束：`UNIQUE(validation_id, backtest_run_id)` —— 同一次内部回测不能重复登记；
同一 validation 可登记多次；同一 run_id 可挂到不同 validation（各自独立）。

### 2.2 新增表 `validation_regime_stats`

按 `validation_id + regime_label` 唯一，字段覆盖任务书 §5 要求的全部项：
总日数、有效观测数、缺失日数、累计收益、CAGR、Sharpe、Sortino、
最大回撤、年化波动、交易次数、是否满足最小样本、原因。

### 2.3 未改动

`validation_runs`、`validation_windows`、`validation_grid`、`validation_stress`、
`corporate_action_applications`、`dividend_receivables` 的**结构一行未动**。
只新增两张表 + `_migrate()` 里的两列补丁。

---

## 3. 每种内部回测的关联覆盖

新 validation `aad7935a2bac4cc4` 的实际登记：

| 角色 | 数量 | 场景键示例 | 覆盖 |
| --- | ---: | --- | --- |
| `in_sample_grid` | 7 | ma5 / ma10 / ma20 / ma30 / ma60 / ma120 / ma250 | 全部 7 档 |
| `out_of_sample` | 1 | ma250 | 唯一一次 |
| `walkforward_train` | 24 | w0-ma5 … w7-ma60 | 8 窗 × 3 候选 |
| `walkforward_test` | 8 | w0-ma20 … w7-ma60 | 8 窗 |
| `regime_grouping` | 1 | 510300 | 唯一一次 |
| `benchmark` | 4 | buy_and_hold / hs300 / ma_trend / zz500 | 全部 |
| `stress_cost_slippage` | 5 | base / cost_plus_50 / cost_plus_100 / slippage_x2 / slippage_x3 | 全部 5 个 |
| `stress_sparse_data` | 1 | sparse_data | 副本库执行 |
| `stress_insufficient` | 1 | insufficient | 40 日短区间 |
| **合计** | **52** | | |

`audit_completeness()` 校验：**complete = True，problems = []**。

---

## 4. 新 validation_id

**`aad7935a2bac4cc4`**

- 源记录：`c46fa37b932944c2`（未改动）
- 会计版本：`ca-v2-receivable`
- 结论：有条件通过
- 行情指纹执行前后一致

---

## 5. 内部回测 run_id 总数

**52 条**，全部真实存在，全部可在 `validation_backtest_runs` 查到。

---

## 6. 各回测角色数量

见 §3 表格。合计 52。

---

## 7. 公司行为事件审计明细

按角色汇总（数据来自 `corporate_action_applications` / `dividend_receivables` 真实行）：

| 角色 | runs | 应用事件 | 应收笔数 | 应收金额 | 到账笔数 | 到账金额 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| benchmark | 4 | 66 | 51 | 128,951.97 | 51 | 128,951.97 |
| in_sample_grid | 7 | 202 | 155 | 149,078.90 | 155 | 149,078.90 |
| out_of_sample | 1 | 30 | 23 | 12,821.78 | 23 | 12,821.78 |
| regime_grouping | 1 | 0 | 0 | 0.00 | 0 | 0.00 |
| stress_cost_slippage | 5 | 150 | 115 | 64,045.60 | 115 | 64,045.60 |
| stress_insufficient | 1 | 3 | 3 | 2,238.40 | 3 | 2,238.40 |
| stress_sparse_data | 1 | 31 | 23 | 12,728.18 | 23 | 12,728.18 |
| walkforward_test | 8 | 25 | 22 | 10,127.69 | 22 | 10,127.69 |
| walkforward_train | 24 | 311 | 258 | 205,671.43 | 258 | 205,671.43 |
| **合计** | **52** | **818** | **650** | **585,663.95** | **650** | **585,663.95** |

涉及事件 78 条（去重），按类型：

| 类型 | 条数 |
| --- | ---: |
| `cash_distribution` | 56 |
| `split` | 18 |
| `reverse_split` | 4 |

### 7.1 样本外明细（可直接对照 3A.3.2.1 报告）

| 项 | 值 |
| --- | --- |
| run_id | `3140a4e414b24f52` |
| 区间内池内可应用事件 | 31 |
| 已应用 | 30 |
| 现金分红应收 | 23 笔 / 12,821.78 元 |
| 已到账 | 23 笔 / 12,821.78 元 |
| 拆分 | 5 条中应用 4 条 |
| 反向拆分 | 3 条全部应用 |

`applied=30 / receivable=23` 与 3A.3.2.1 报告完全一致。

---

## 8. 分红应收与到账实际金额

### 8.1 全量汇总

| 项 | 笔数 | 金额 |
| --- | ---: | ---: |
| 应收合计 | 650 | 585,663.95 |
| 已到账 | 650 | 585,663.95 |
| **未到账** | **0** | **0.00** |

全部 650 笔在回测区间内均已到 `pay_date`，无跨区间挂账。

### 8.2 跨库明细（必须标注）

`stress_sparse_data` 的 23 笔 / 12,728.18 元写在**稀疏副本库**
`val_sparse_*/sparse_market.db`，不在主库。

审计结果按登记表里的实际计数呈现，并带 `detail_location = "external_copy_db"`
与 `detail_note` 说明位置。**不显示为 0，也不假装在主库。**

---

## 9. 未应用事件及原因

样本外区间（2025-01-02 ~ 2026-11-09）池内可应用 31 条，应用 30 条，**1 条未应用**：

| action_id | 代码 | 类型 | 除息日 | 生效日 | 原因 |
| ---: | --- | --- | --- | --- | --- |
| 153 | 515880 | split (1:3.0) | 2026-02-02 | 2026-02-03 | **当期未持仓** |

证据：`positions_daily` 中该 run 的 515880 持仓行数为 0。
引擎只对持仓标的应用份额调整，未持仓则跳过——这是既有会计规则，
本次未改。

**不标为 blocked**：`blocked_actions` 用于「口径不明确而拒绝执行」，
与「未持仓」是不同语义。本报告如实记录为「不适用」。

---

## 10. 市场环境分组统计

已落库 `validation_regime_stats` 4 行：

| 环境 | 状态 | 总日数 | 有效 | 缺失 | 累计收益 | Sharpe | Sortino | CAGR | 最大回撤 | 年化波动 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bull | ok | 324 | 321 | 3 | +53.24% | 2.1879 | 3.3656 | +39.81% | −7.46% | 15.90% |
| bear | ok | 26 | 24 | 2 | −4.81% | −5.6095 | −5.9579 | −40.43% | −4.99% | 9.15% |
| range | ok | 97 | 97 | 0 | −17.16% | −2.2385 | −2.5833 | −38.69% | −18.39% | 20.86% |
| unclassified | **insufficient_sample** | 0 | 0 | 0 | — | — | — | — | — | — |

### 10.1 关键说明

- `unclassified` 有效样本 0 < 20（`MIN_REGIME_SAMPLES`），标记
  `insufficient_sample` 并写原因「有效日收益 0 < 20」，**不填 0、不并入 range**。
- 分组总日数 324+26+97 = 447，等于 OOS 交易日总数，无非交易日压缩。
- **缺 2 个的 bear、缺 3 个的 bull**：缺失日单独记在 `missing_days`，
  没有 dropna 后再统计。
- 预热数据只参与 MA250 初始化，不计入 OOS 绩效，labels 也不含预热日。
- Sharpe / Sortino / CAGR / 回撤口径与 `compute_performance()` 完全一致，
  只把样本限定在本环境内；**未发明新算法**。

---

## 11. 两次重放绩效对照

| 指标 | `321caeb581e54d3b` | `aad7935a2bac4cc4` | 差异 |
| --- | ---: | ---: | ---: |
| **样本内** | | | |
| 总收益 | 13.6776% | 13.6776% | **0** |
| CAGR | 3.3937% | 3.3937% | **0** |
| Sharpe | 0.252208 | 0.252208 | **0** |
| Sortino | 0.343685 | 0.343685 | **0** |
| 最大回撤 | −13.8537% | −13.8537% | **0** |
| 交易次数 | 1,270 | 1,270 | **0** |
| **样本外** | | | |
| 总收益 | 20.1146% | 20.1146% | **0** |
| CAGR | 10.9107% | 10.9107% | **0** |
| Sharpe | 0.720981 | 0.720981 | **0** |
| Sortino | 0.987995 | 0.987995 | **0** |
| 最大回撤 | −18.2881% | −18.2881% | **0** |
| 交易次数 | 419 | 419 | **0** |
| 最优参数 | MA250 | MA250 | 同 |
| 结论 | 有条件通过 | 有条件通过 | 同 |

**逐位相同。** 原因：同一数据、同一参数、同一代码口径；
本次改动只在回测结果产生之后增加登记与统计，不触碰计算路径。

---

## 12. 旧记录兼容情况

| 记录 | audit_status | 说明 |
| --- | --- | --- |
| `32aead3291734f91` | `unavailable_legacy` | 无内部回测登记 |
| `c46fa37b932944c2` | `unavailable_legacy` | 同上 |
| `03410886d1f64fa7` | `unavailable_legacy` | 同上 |
| `321caeb581e54d3b` | `unavailable_legacy` | 同上 |

缺少的原始数据：内部各次 BacktestEngine 的 run_id、会计口径快照、
公司行为应用明细。这些在生成时**未被记录**，且明细表里也查不到对应
run_id（当时 `_run_backtest` 传 `db_path=None`，引擎根本不写明细）。

**不猜测补齐、不修改原始绩效指标、不伪造审计记录。**

### 12.1 本次施工过程中的中间记录

| validation_id | 状态 | 说明 |
| --- | --- | --- |
| `8181fa3cbf394466` | 完成但明细 0 | 第一次试跑，`db_path` 未解析，明细未写 |
| `e815aee4f01b4146` | 同上 | 第二次试跑 |
| `61a7829c9f7d4fac` | 完成，明细 31 | 第三次，sparse 未登记 |
| `d8dc7e7c109342c1` | **不完整** | MA5 因 `database is locked` 失败，缺 1 条登记 |
| `67ad070efc0d4b7b` | 完成 | 第五次 |
| `159cfe0708fb49c6` | 完成 | 第六次 |
| `aad7935a2bac4cc4` | **完成（交付）** | 第七次，`audit_completeness=True` |

这些记录**全部保留**，不删除。它们的 `audit_completeness` 分别为
False/True，如实反映各自的完整度；`d8dc7e7c109342c1` 明确标为不完整。

---

## 13. 异常测试结果

`tests/test_validation_audit_3a3_2_3_4.py`（43 项）+
`tests/test_validation_audit_api_3a3_2_3_4.py`（7 项）= **50 项**，
每条都核实数据库最终状态。

| 任务书条目 | 测试 | 库内状态断言 |
| --- | --- | --- |
| 1. validation_id 不存在 | `test_audit_trace_validation_not_found` | 返回 `validation_not_found`，links 为空 |
| 2. backtest_run_id 不存在 | `test_backtest_run_id_must_exist_in_links` | 链接存在但明细计数 0，不伪造 |
| 3. 同一 run_id 重复登记 | `test_unique_constraint_on_validation_and_run` | 抛 `AuditError`，表内仍 1 行 |
| 4. 同一 validation 多次回测 | `test_same_validation_many_runs` | 3 行，角色顺序正确 |
| 5. 正式会计标记缺失 | `test_missing_formal_flag_rejected` | 抛错，表内 0 行 |
| 6. formal_valuation 非 bool | `test_non_boolean_formal_rejected` ×6 | 六种值全拒，表内 0 行 |
| 7. basis 非 formal_receivable | `test_non_formal_basis_rejected` ×5 | 五种全拒，表内 0 行 |
| 8. 公司行为事件加载失败 | `test_event_load_failure_leaves_validation_failed` | validation `failed`，已登记痕迹保留 |
| 9. 应用明细缺失 | `test_missing_application_and_receivable_marked_not_fabricated` | 计数 0，非伪造 |
| 10. 应收明细缺失 | 同上 | 金额 0.0 |
| 11. 分红重复入账 | `test_duplicate_receivable_not_double_counted` | 唯一约束挡住，仍 1 行 |
| 12. 分红重复结算 | `test_duplicate_settlement_does_not_change_amount` | settled 恒为 1 |
| 13. regime 数据不足 | `test_regime_insufficient_sample_persisted` | `insufficient_sample` + 原因，指标 null |
| 14. regime 收益序列缺口 | `test_regime_missing_day_kept_apart` | total/valid/missing 三值分离 |
| 15. validation 中途失败 | `test_partial_validation_marked_incomplete` | coverage `complete=False` |
| 16. 关联表写入失败 | `test_register_without_validation_id_raises`<br>`test_register_without_run_id_raises` | 抛 `AuditError`，表内 0 行 |
| 17. 成功但关联不完整 | `test_completeness_detects_missing_grid_cell`<br>`test_completeness_reports_failed_run_reason` | 指出缺哪个档位 / 失败原因 |
| 18. 旧记录无审计明细 | `test_legacy_record_audit_unavailable` | `unavailable_legacy` + 原因 |
| 19. 同一 validation 重复查询 | `test_repeated_query_returns_same_result` | 两次结果相等 |
| 20. 重复执行审计汇总 | `test_repeated_regime_write_idempotent` | 4 行不重复插入 |
| 补充 | `test_scenario_key_falls_back_to_context` | 漏传场景键不丢信息 |
| 补充 | `test_audit_db_path_redirects_registration` | sparse 登记落主库 |
| 补充 | `test_sparse_detail_db_counted_from_copy_not_main` | 副本库明细被正确统计 |
| 补充 | `test_off_main_db_detail_uses_registered_counts` | 跨库按登记计数呈现并标注 |
| 补充 | `test_main_db_detail_reported_as_main` | 主库明细标 `main_db` |
| 补充 | `test_regime_stats_exposes_risk_metrics` | 四指标齐全 |
| 补充 | `test_regime_insufficient_sample_has_no_metrics` | 不足时不产出指标 |
| 补充 | `test_regime_metrics_persisted_after_save` | 落库后四指标可读 |
| 补充 | `test_failed_run_marks_audit_incomplete` | 一条 failed → `incomplete` |
| 补充 | `test_regime_absent_label_marked_unavailable_not_fabricated` | 缺标签标 `unavailable` |
| API | 7 项 | 404 分支、legacy 标记、完整链路、三个查询端点 |

### 13.1 反向审查：系统会不会误判「完整审计成功」

逐条验证过以下失败路径，**结论：不会**。

| 失败路径 | 防护 |
| --- | --- |
| validation 跑到一半崩 | `finally` 解绑上下文，已登记痕迹保留；`audit_status=incomplete` |
| 某次内部回测口径不对 | `register_backtest` 抛 `AuditError`，整个 validation 失败 |
| 某次内部回测抛异常 | 该次不登记（引擎没产出 result）；`audit_completeness` 报「缺角色」 |
| 网格某档崩了 | 该档不登记；`audit_completeness` 指出「MAx 未登记」 |
| 关联表写入失败 | 抛 `AuditError` 上抛，validation 失败，不留假 success |
| sparse 明细在副本库 | 标 `external_copy_db` + `detail_note`，不显示 0 |
| 缺角色 / 缺档位 | `audit_completeness.complete = False` + 具体 problems |

**实测案例**：`d8dc7e7c109342c1` 的 MA5 因 `database is locked` 失败，
系统正确报出 `in_sample_grid 登记 6 条，期望 7 条` + `样本内 MA5 未登记`，
没有把它当成完整审计成功。

---

## 14. SQLite 完整性

```
PRAGMA integrity_check -> ok
```

| 表 | 修改前 | 现在 | 变化 |
| --- | ---: | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |
| `etf_pool` | 46 | 46 | 0 |
| `trade_calendar` | 8,797 | 8,797 | 0 |
| `backtest_runs` | 12 | 12 | 0 |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `corporate_action_applications` | 3,787 | 6,910 | +3,123 |
| `dividend_receivables` | 785 | 3,274 | +2,489 |
| `validation_runs` | 47 | 54 | +7 |
| `replay_attempts` | 4 | 11 | +7 |
| `validation_backtest_runs` | 0（新表） | 361 | +361 |
| `validation_regime_stats` | 0（新表） | 28 | +28 |

明细表增长全部来自本次 7 次试跑/交付重放的内部回测——这正是本次
要打通的链路。事件表、版本表、行情表**一行未动**。

---

## 15. 数据库快照报告

| 文件 | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_3_4_20261116.db` | 272,994,304 | `1342d823cf8ee830458433ca2aeac1b6027daec2d7f1bc7287d450af0b53c580` |
| `data/backups/fund_agent_post_3a3_2_3_4_20261116.db` | 274,620,416 | `5ad980a9fc43b8167fd717bb6a93f7166c7e2f7cfaf04b3f948e9e50e5f86ddc` |

数据库不入 Git、不入 ZIP，仅本地保留。

---

## 16. 遗留问题

1. **旧记录永久不可追溯**。`32aead` / `c46fa3` / `03410886` / `321caeb5`
   四条只能标 `unavailable_legacy`。当时引擎不写明细，无从恢复。

2. **中间试跑记录保留**。`8181fa3c` ~ `159cfe07` 共 6 条，其中
   `d8dc7e7c109342c1` 不完整。它们会出现在验证页面列表里，
   审计 tab 会如实显示各自状态。是否清理需另行决定，本阶段不删。

3. **`regime_grouping` 的明细恒为 0**。该次回测是纯内存分组计算，
   不产生交易——不是缺陷，是本来的行为。

4. **`stress_sparse_data` 明细永久在主库之外**。副本目录
   `val_sparse_*` 在用完后被清理，若要长期审计需保留副本或把明细回写主库。
   当前做法：登记表存实际计数 + 标注位置，主库能查到「有多少」，
   查不到「具体哪几笔」。

5. **`audit_completeness` 的期望值只覆盖能从库内推出的角色**。
   基准数依赖 `benchmark_config`，若该字段为空则不核对数量，只核对是否出现。

6. **性能影响未单独测量**。每次内部回测多一次 INSERT + 一次明细 COUNT，
   相对单次回测数十秒级耗时可忽略，但未做基准对照。

7. 测试结果是本会话本地执行结果，不是外部独立测试。

---

## 17. 交付清单

| 项 | 值 |
| --- | --- |
| 新 validation_id | `aad7935a2bac4cc4` |
| 内部回测 run 数 | 52 |
| 应用事件 | 818 |
| 应收 / 到账 | 650 笔 / 585,663.95 元 |
| 未到账 | 0 笔 / 0.00 元 |
| 审计完整性 | complete，problems = [] |
| 测试 | 618 passed / 0 failed / 0 skipped / 0 xfail，161.82 秒 |
| 行情指纹 | `d54727c0…` 未变 |
| `integrity_check` | ok |
| ZIP | `dist/jj-agent-phase3A3_2_3_4-src.zip`，300 文件，1,621,433 字节 |
| ZIP SHA256 | `cfc0671eb306364399cc64906d74200ce744df5d655ca0f9f251a67bfe7bb045` |
| SHA 清单 | `dist/SHA256SUMS_3a3_2_3_4.txt` |
