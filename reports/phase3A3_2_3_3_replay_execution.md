# 阶段3A.3.2.3.3 P0 历史验证记录受控重放

- 首次执行：2026-11-14
- 复核与补充：2026-11-16
- 执行基线 HEAD：`c1e4027217c4d4cf01ed37dbe26fd73de5f73cd3`（3A.3.2.3.2）
- 本轮交付 HEAD：`07f02dc2e5318bc4cdd5a148ee4fe1a21e0cd22a` + 本次复核补丁
- 范围：仅指定的 2 条 P0 记录，未扩大重放范围

---

## 1. 前置条件检查结果

### 1.1 3A.3.2.3.2 是否已完成并提交

**首次执行时不存在。** `git log` 停在 3A.3.2.3.1 的 `2541fdc`，
无 3A.3.2.3.2 的提交、报告或产物。按任务书 §2 要求先补齐，产出
`c1e4027`：`reports/phase3A3_2_3_2_replay_gate_fix.md`，测试 538 → 564。

### 1.2 六项要求实测

| # | 要求 | 结果 | 实测证据 |
| --- | --- | --- | --- |
| 1 | validation 严格要求 `ca-v2-receivable` | 通过 | `isinstance(replay_acct, str) and == CURRENT` |
| 2 | None/空串/legacy/未知不得成功 | 通过 | 五种实况全落 `failed` |
| 3 | 新记录不存在必须失败 | 通过 | `row is None` 独立分支 |
| 4 | backtest 要求 `formal_valuation is True` | 通过 | `isinstance(bool) and is True` |
| 5 | 失败 attempt 保存 failed + 原因 | 通过 | 库内 `failed` + 中文原因实测 |
| 6 | 专项测试已加入，旧测试未弱化 | 通过 | +26 → +2 → +2，共 30 项 |

### 1.3 三项在施工中暴露的缺陷

| # | 缺陷 | 位置 | 修复 |
| --- | --- | --- | --- |
| 1 | validation 闸门三值短路，None/空串/记录不存在全放行 | `replay_validation` | 显式 `row is None` + 严格白名单 |
| 2 | backtest 闸门真值判断，`formal_valuation=1` 能穿过 | `replay_backtest` | 改 `isinstance(bool) and is True` |
| 3 | `save_validation_run()` 不写 `accounting_version` 列，新记录该列恒为 NULL | 重放路径 | 新增 `_stamp_replay_validation()` |

缺陷 3 是**首次真实重放时暴露的**，不是读代码发现的：

```
[FAIL] 32aead3291734f91 -> 397118a140c44f47（重放记录会计版本异常：None）
```

同时补 `_reject_replay_record()`：闸门失败时把刚建出来的记录降级为
`failed` 并写明原因，不留 `status=success` 的孤立记录。

---

## 2. 两条源记录的重放前盘点

| 检查项 | `32aead3291734f91` | `c46fa37b932944c2` |
| --- | --- | --- |
| 1. 记录真实存在 | 是 | 是 |
| 2. 分类 | `legacy`（待重放） | `legacy`（待重放） |
| 3. 原始参数完整 | 是，无缺失项 | 是，无缺失项 |
| 4. 参数可忠实恢复 | 是，`config_hash` 反证命中 | 是，`config_hash` 反证命中 |
| 5. 输入数据可读 | 行情 116,609 行、事件 81 条均可读 | 同 |
| 6. 无默认值替代 | 28 个参数全部反证命中，非默认值填充 | 同 |
| 7. 未被当前默认值覆盖 | 是 | 是 |

### 2.1 全部 28 个已证明参数

| 参数 | 值 | 参数 | 值 |
| --- | --- | --- | --- |
| strategy_name | `ma_trend` | strategy_version | `1.0.0` |
| initial_cash | 1,000,000.0 | commission_rate | 0.00025 |
| min_commission | 5.0 | slippage_bps | 5.0 |
| execution_price | `open` | max_defer_days | 3 |
| risk_free_rate | 0.0 | annualization | 252 |
| rebalance_tolerance | 0.02 | indicator_version | `v1.0.2-30b821a1af15` |
| ma_window_grid | `[5,10,20,30,60,120,250]` | wf_grid | `[5,20,60]` |
| train_months | 24 | test_months | 6 |
| step_months | 6 | pool_mode | `all`（41 只） |
| regime_proxy_code | `510300` | regime_ma_window | 250 |
| min_validation_days | 120 | exclude_insufficient | True |
| min_coverage_ratio | 0.95 | notes | `[]` |

**证明方法**：把这些值代入 `ValidationConfig.params_hash()`，
结果必须**完全等于**库里的 `config_hash`
（`11ce7469245afab0` / `5bc9252086c515e2`）。命中即全部参数被证明，
不是「大概差不多」。

### 2.2 区间端点的口径说明

| 记录 | 存库 `is_start` | 反证命中的请求日 |
| --- | --- | --- |
| `32aead3291734f91` | 2021-01-04 | 2021-01-01 |
| `c46fa37b932944c2` | 2021-01-04 | 2021-01-04 |

`32aead3291734f91` 存的是「请求日 2021-01-01（元旦）对齐到下一交易日」的
结果，反证时必须用请求日才能命中哈希。两者**实际交易日历完全相同**，
不存在参数覆盖。

### 2.3 基准与环境配置

| 项 | 值 | 可比较性 |
| --- | --- | --- |
| 环境代理 | `510300`，MA250 | 可比 |
| 基准 | `510300`（沪深300代理）、`510500`（中证500代理） | 可比 |
| 压力场景 | 7 个（base / cost+50 / cost+100 / slippage×2 / slippage×3 / sparse / insufficient） | 可比 |

---

## 3. dry-run 结果

两条都执行了 `--dry-run`，输出完整 28 个参数、源记录 ID、
预计新记录类型（`validation_runs` 新 ID）、当前会计版本
（`ca-v2-receivable`）。

### 3.1 零写入证明

| 项 | dry-run 前 | dry-run 后 |
| --- | ---: | ---: |
| `validation_runs` | 47 | 47 |
| `replay_attempts` | 4 | 4 |
| `backtest_runs` | 12 | 12 |
| 行情指纹 | `d54727c0…` | `d54727c0…` |
| 源记录 `finished_at` | 未变 | 未变 |

dry-run 未出现参数不一致、数据缺失或无法解释的警告。

---

## 4. 两条记录的执行结果

### 4.1 第一条：`32aead3291734f91`

| 阶段 | 结果 |
| --- | --- |
| 首次执行（2026-11-14 15:22~15:49，约 27 分钟） | **failed** → `397118a140c44f47`（`accounting_version=None`） |
| 修复缺陷 3 后重跑（15:57~16:24，约 27 分钟） | **success** → `03410886d1f64fa7` |

| 项 | 值 |
| --- | --- |
| 源 input_hash | `dbfac114e6900c87` |
| 新 input_hash | `1263f78d8a63e309` |
| 新 accounting_version | `ca-v2-receivable` |
| 新 legacy_flag | NULL（新记录，未标记为历史） |
| 新结论 | 有条件通过 |
| 子表 | windows 8 / grid 8 / stress 7 |

### 4.2 第二条：`c46fa37b932944c2`

| 项 | 值 |
| --- | --- |
| 执行时间 | 2026-11-14 16:29~16:52，约 21 分钟 |
| 结果 | **success** → `321caeb581e54d3b` |
| 源 input_hash | `2ac80bcdfb5459c5` |
| 新 input_hash | `6da51a1c462b7c65` |
| 新 accounting_version | `ca-v2-receivable` |
| 新结论 | 有条件通过 |
| 子表 | windows 8 / grid 8 / stress 7 |

### 4.3 逐项核验（§6 的 11 项）

| # | 检查 | 第一条 | 第二条 |
| --- | --- | --- | --- |
| 1 | 原始记录仍存在且内容不变 | 通过 | 通过 |
| 2 | 新记录真实存在 | 通过 | 通过 |
| 3 | 可追溯到 `source_validation_id` | 通过 | 通过 |
| 4 | `accounting_version == ca-v2-receivable` | 通过 | 通过 |
| 5 | 正式会计标记正确 | 通过（见 4.4） | 通过 |
| 6 | attempt 最终 `success` | 通过 | 通过 |
| 7 | attempt 与新记录关联正确 | 通过 | 通过 |
| 8 | 参数与源一致 | 区间/池/网格/策略全等 | 同 |
| 9 | 事件摘要与实际输入一致 | 通过（见 §6.2） | 通过 |
| 10 | input_hash 含行情+策略+事件指纹 | 通过（见 §6.3） | 通过 |
| 11 | 未修改行情/指标/事件/历史 | 通过 | 通过 |

第 1 项用执行前 `SELECT *` 全字段快照逐字段比对，两条均为 `True`。

### 4.4 第 5 项的口径澄清（必须标注）

`backtest_runs.summary_json` 里有 `accounting_basis` / `formal_valuation`
两个键；**`validation_runs.summary_json` 里没有**——验证层从不写这两个键，
历史 44 条记录也全都没有。

因此验证记录的「正式会计标记」表现为：

| 载体 | 值 | 说明 |
| --- | --- | --- |
| `validation_runs.accounting_version` | `ca-v2-receivable` | 权威标记 |
| `validation_runs.legacy_flag` | `NULL` | 非历史记录 |
| 重放闸门 | `replay_attempts.status='success'` | 已通过白名单检查 |

验证层的「正式口径」由 `app/validation/runner.py::_require_formal()`
在**回测结果层面**把关（`accounting_basis=formal_receivable` +
`formal_valuation is True`），任一不满足就抛 `ValidationError` 中止整次验证。
本轮两条重放都跑到了 `status=success`，说明它们的每一次内部回测都通过了
该闸门。

**不伪造**：不能声称 `validation_runs.summary_json` 里有这两个键。

---

## 5. 新旧口径对照

### 5.1 第一条 `32aead3291734f91` → `03410886d1f64fa7`

| 指标 | 旧口径 | 新口径 | 差异 |
| --- | ---: | ---: | ---: |
| **样本内** | | | |
| 总收益 | −16.3259% | **+13.6776%** | +29.9995 pp |
| CAGR | −4.5341% | +3.3937% | +7.9278 pp |
| Sharpe | 0.1058 | 0.2522 | +0.1464 |
| Sortino | 0.1429 | 0.3437 | +0.2008 |
| 最大回撤 | −32.8057% | −13.8537% | +18.9520 pp |
| 交易次数 | 1,199 | 1,270 | +71 |
| **样本外** | | | |
| 总收益 | +32.2111% | **+20.1146%** | −12.0965 pp |
| CAGR | +17.0898% | +10.9107% | −6.1791 pp |
| Sharpe | 0.7859 | 0.7210 | −0.0649 |
| Sortino | 1.5408 | 0.9880 | −0.5528 |
| 最大回撤 | −24.5352% | −18.2881% | +6.2471 pp |
| 交易次数 | 413 | 419 | +6 |
| **其他** | | | |
| 最优参数 | MA250 | MA250 | 同 |
| Walk-Forward | 8/8 | 8/8 | 同 |
| 结论 | 有条件通过 | 有条件通过 | 同 |

### 5.2 第二条 `c46fa37b932944c2` → `321caeb581e54d3b`

| 指标 | 旧口径 | 新口径 | 差异 |
| --- | ---: | ---: | ---: |
| **样本内** | | | |
| 总收益 | +10.8689% | **+13.6776%** | +2.8087 pp |
| CAGR | +2.7224% | +3.3937% | +0.6713 pp |
| Sharpe | 0.1776 | 0.2522 | +0.0746 |
| Sortino | 0.2409 | 0.3437 | +0.1028 |
| 最大回撤 | −13.7331% | −13.8537% | −0.1206 pp |
| 交易次数 | 1,249 | 1,270 | +21 |
| **样本外** | | | |
| 总收益 | +20.2447% | **+20.1146%** | −0.1301 pp |
| CAGR | +10.9785% | +10.9107% | −0.0678 pp |
| Sharpe | 0.7290 | 0.7210 | −0.0080 |
| Sortino | 0.9993 | 0.9880 | −0.0113 |
| 最大回撤 | −18.1127% | −18.2881% | −0.1754 pp |
| 交易次数 | 419 | 419 | 0 |
| **其他** | | | |
| 最优参数 | MA250 | MA250 | 同 |
| Walk-Forward | 8/8 | 8/8 | 同 |
| 结论 | 有条件通过 | 有条件通过 | 同 |

### 5.3 各市场环境结果

**不可比较，明确标注。**

`validation_runs.summary_json` 只存 `is_metrics` / `oos_metrics` /
`conclusion` / `conclusion_reasons` / `window_*` / `data_fingerprint`，
**不存 `regime` 分组统计**；数据库也没有对应的 regime 表。
`conclusion_reasons` 里只能读到一句汇总：

| 记录 | 环境相关结论 |
| --- | --- |
| 全部 4 条 | 「市场环境覆盖 3 类且样本充足」 |

三条新记录与两条源记录在这一点上完全相同，**无法给出 bull/bear/range 的
分组收益**。不伪造分组数字。

### 5.4 参数网格对比（可比较，能解释样本内反转）

| 参数 | 旧口径 IS 收益 | 新口径 IS 收益 |
| --- | ---: | ---: |
| MA5 | −40.8425% | −29.8687% |
| MA10 | −26.1708% | −19.2217% |
| MA20 | −16.5770% | −7.4331% |
| MA30 | −18.3964% | −5.8484% |
| MA60 | −19.1497% | −0.6924% |
| MA120 | −17.0107% | −5.1047% |
| MA250 | **−16.3259%** | **+13.6776%** |

全部 7 个档位在新口径下都改善，但 MA250 的改善幅度最大（+30.00 pp），
其余档位改善 7.2~18.5 pp。原因是 MA250 换手最低、持仓最久，
累积的分红应收最多——旧口径把这些分红当成价格下跌吃掉，
把「长期持有」这条路径的收益系统性压低。

**这正是「有条件通过」里「仅 1/7 个参数组合在样本内取得正收益」的由来**：
旧口径下是 0/7，新口径下是 1/7。

### 5.5 差异归因

| 差异 | 来源 | 判定 |
| --- | --- | --- |
| 样本内 −16.33% → +13.68%（第一条） | **会计口径** | 口径差异，非错误 |
| 样本外 +32.21% → +20.11%（第一条） | 会计口径 | 口径差异，非错误 |
| 样本内 +10.87% → +13.68%（第二条） | 会计口径（该记录已有部分修复，故幅度小） | 口径差异 |
| 样本外 +20.24% → +20.11%（第二条） | 会计口径，仅 −0.13 pp | 口径差异 |
| 行情数据 | **未变**，指纹 `d54727c0…` 四条记录相同 | 非差异来源 |
| 策略参数 | **未变**，`config_hash` 反证 | 非差异来源 |
| 策略算法 | **未变**，本轮未改 `app/backtest/strategies/` | 非差异来源 |

### 5.6 两条新结果完全一致

`03410886d1f64fa7` 与 `321caeb581e54d3b` 的所有指标逐位相同。

**预期结果**：两条源记录的实际运行参数完全相同（41 只池、MA250、
同一区间、同一成本），在新会计口径下必然收敛到同一组数字。
它们的 `input_hash` 不同（`1263f78d…` vs `6da51a1c…`）是因为
请求日不同（2021-01-01 vs 2021-01-04），对齐后交易日历相同。

---

## 6. 公司行为事件处理情况

### 6.1 事件数量

| 口径 | 事件数 | 可应用 | digest |
| --- | ---: | ---: | --- |
| 全库区间内（2021-01-04~2026-11-09） | 81 | 81 | `8aeafc0a2d17fd2c…` |
| **41 只回测池内** | **80** | **80** | `668090ae7ed7e81b…` |

差值是 `588200`（在 46 只全库池中，不在 41 只回测池中）。
两条新记录用的都是 **80 条池内事件**。

### 6.2 第 9 项核验：事件摘要与实际输入一致

用「41 只池 + 区间」重新 `load_actions` + `compute_events_digest`，
得到 `668090ae…`；这与重放时传给 `_input_hash` 的 digest 一致
（下节反证验证）。事件集未被改动：`corporate_actions` 166 条、
`corporate_action_versions` 704 条，前后不变。

### 6.3 第 10 项核验：input_hash 反证

用「当前行情指纹 + 池内 80 条事件 digest + resolved_params」
重算 `_input_hash()`：

| 记录 | 库内 input_hash | 重算值 | 一致 |
| --- | --- | --- | --- |
| `03410886d1f64fa7` | `1263f78d8a63e309` | `1263f78d8a63e309` | **是** |
| `321caeb581e54d3b` | `6da51a1c462b7c65` | `6da51a1c462b7c65` | **是** |
| `32aead3291734f91`（旧） | `dbfac114e6900c87` | 不等 | 预期（旧算法无事件指纹） |
| `c46fa37b932944c2`（旧） | `2ac80bcdfb5459c5` | 不等 | 预期（同上） |

**结论**：新记录的 `input_hash` 确实由「行情指纹 + 策略参数 + 事件指纹」
三者共同决定，且可被独立复现。

### 6.4 分红应收与到账：不可比较，明确标注

`corporate_action_applications` 与 `dividend_receivables` 的主键是
**回测 run_id**，不是 `validation_id`。验证流程每次内部生成临时 run_id，
所以：

| 检查 | 结果 |
| --- | --- |
| 本轮 3 条新 validation 在这两张表的行数 | **0** |
| 历史 44 条 legacy validation 的行数 | 同样为 0（既有设计） |

**因此本报告无法从数据库给出「本次重放的现金分红应收金额与到账笔数」。**
该数字只能在单策略内存回测（`scripts/replay_3a3_2.py --legacy-comparison`）
里得到——3A.3.2.1 报告记录的是样本外 applied 30 / settled 23。

这是**口径不可比**，不是数据缺失。按任务书要求明确标注，不伪造。

### 6.5 不变量 C 的执行确认

| 要求 | 实现 |
| --- | --- |
| 必须用 `ca-v2-receivable` | 新记录该列实测为该值 |
| 分红按登记日持仓确认应收 | `engine._capture_dividend_shares()` 在成交后、快照前锁定 |
| 除息日不进可用现金 | `ex_date` 只确认 `dividend_receivable` |
| 发放日才转现金 | `settle_dividend_receivable(pay_date <= on_date)` |
| 拆分/合并/零碎/补偿规则 | 3A.3.2.2 / 2.2.1 已验收逻辑，本轮未改 |
| 事件表读取失败必须终止 | `CorporateActionLoadError` 抛出，回测中止 |

---

## 7. 幂等性检查

两条记录完成后，再次用相同 `--source` 执行（2026-11-16 复核）：

```
[SKIP] 32aead3291734f91 -> 03410886d1f64fa7（已存在成功重放，跳过）
[SKIP] c46fa37b932944c2 -> 321caeb581e54d3b（已存在成功重放，跳过）
```

| 检查 | 结果 |
| --- | --- |
| 不重复生成新的成功记录 | 是，`validation_runs` 保持 47 条 |
| 正确识别已成功 | 是，返回 `skipped` + 原 replay_id |
| 不重复计入现金分红 | 无新记录产生 |
| 不重复生成公司行为影响 | `corporate_action_applications` 行数不变（3,787） |
| 不改变已有新记录 | 是，新记录 `input_hash` / `finished_at` 未变 |
| 不产生冲突的成功记录 | 是，每个 source 恰好 1 条 `success` |

未使用 `--force`。`--force` 的行为：新建 run_id + 新 attempt 行，
旧记录保留不覆盖——本轮不需要，未执行。

---

## 8. 异常测试结果

`tests/test_replay_gate_3a3_2_3_2.py`，**30 项**，每条核实数据库最终状态。

| 任务书条目 | 测试 | 库内状态断言 |
| --- | --- | --- |
| §8-1 源记录不存在 | `test_source_validation_missing_raises` | attempt 表为空 |
| §8-2 原始参数缺失 | `test_source_validation_params_missing` | `failed`，无新记录 |
| §8-3 策略版本未知 | `test_unknown_strategy_version_cannot_be_proven` | `failed` |
| §8-4 事件表读取失败 | `test_corporate_action_load_failure_aborts_replay`（backtest）<br>`test_validation_replay_event_load_failure_fails`（validation） | `failed`，无新记录 |
| §8-5 新记录查不到 | `test_missing_new_validation_record_fails` | `failed`，无新增 |
| §8-6 version=None | `test_new_record_accounting_version_none_fails` | `failed` |
| §8-7 version='' | `test_new_record_accounting_version_empty_fails` | `failed` |
| §8-8 version=旧/未知 | `test_new_record_legacy_or_unknown_version_fails` ×4 | 四种全 `failed` |
| §8-9 正式标记错误 | `test_backtest_non_boolean_formal_valuation_fails` ×8<br>`test_backtest_non_formal_basis_rejected` | `failed`，`save_result` 未调 |
| §8-10 保存失败 | `test_save_failure_leaves_no_success_attempt` | `failed`，行数不变 |
| §8-11 状态更新失败 | `test_finish_attempt_failure_does_not_fake_success` | 无 `success` 行 |
| §8-12 重复执行幂等 | `test_repeat_replay_does_not_duplicate_success` | `success` 恒为 1 |
| §8-13 不产生重复成功 | `test_no_duplicate_corporate_action_booking_on_repeat` | 应用/净值行不变 |
| §8-14 中断不伪装成功 | `test_interrupted_replay_not_reported_as_success` | `running` 不算成功 |
| 补充 | `test_validation_replay_internal_failure_records_reason` | `failed` + 原因可查 |
| 补充 | `test_replay_stamps_accounting_version_on_new_record` | 新记录带 `ca-v2-receivable` |
| 补充 | `test_failed_gate_downgrades_orphan_record` | 孤立记录降级为 `failed` |
| 补充 | `test_history_untouched_after_failed_replay` | 源记录整行不变 |

### 8.1 特别检查

| 检查 | 结果 |
| --- | --- |
| 失败后是否留下错误的 success 记录 | **实测发生过一次**：`397118a140c44f47`。已按 `_reject_replay_record()` 降级为 `failed` 并写入 `error_message`，保留不删 |
| 是否产生孤立的新记录 | 同上，该记录即孤立产物，已降级 |
| 是否存在重复分红入账 | 无：重复执行后业务表行数不变 |

---

## 9. SQLite 完整性检查

```
PRAGMA integrity_check -> ok
```

| 表 | 首次执行前 | 现在 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `etf_pool` | 46 | 46 |
| `trade_calendar` | 8,797 | 8,797 |
| `backtest_runs` | 12 | 12 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_versions` | 704 | 704 |
| `corporate_action_applications` | 3,787 | 3,787 |
| `dividend_receivables` | 785 | 785 |
| `validation_runs` | 44 | **47** |
| `replay_attempts` | 1 | **4** |

新增 3 条 validation 行（2 成功 + 1 失败留痕）、3 条 attempt 行。

---

## 10. 原始数据未被修改的证据

| 证据 | 值 |
| --- | --- |
| 行情指纹（执行前 / 执行后 / 幂等后） | 三次均为 `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 行情行数 | 116,609（不变） |
| 源 `32aead3291734f91` 全字段 | 与执行前快照逐字段相等 |
| 源 `c46fa37b932944c2` 全字段 | 与执行前快照逐字段相等 |
| `corporate_actions` | 166（不变） |
| `corporate_action_versions` | 704（不变） |
| 源记录 `finished_at` | `2026-11-11T17:47:44` / `2026-11-12T20:25:06`（未变） |

---

## 11. 遗留问题和风险

1. **`397118a140c44f47` 是失败的中间产物**，`accounting_version` 为 NULL、
   `status='failed'`。它在盘点里被归入 `unknown_legacy`。保留作为首次执行的
   审计痕迹，不删除。

2. **验证层的分红明细不可追溯**（§6.4）。这是既有设计缺陷，
   影响所有 44 条历史验证记录。要审计「哪条事件、多少应收、何时到账」，
   目前只能跑单策略内存回测。

3. **各市场环境的收益不可比较**（§5.3）。`regime` 分组结果从未落库。

4. **`_stamp_replay_validation()` 是对新记录的 UPDATE**，
   与「不修改历史记录」不冲突（只写刚创建的 validation_id），
   但它是重放路径上唯一的新增写操作，需在后续审计中保持可见。

5. **两条重放各约 21~27 分钟**，剩 35 条全量约 13 小时。

6. 测试结果是本会话本地执行结果，不是外部独立测试。

---

## 12. 是否建议扩大历史重放范围

**建议扩大，但需先解决两件事。**

支持理由：

- 两条 P0 全部通过 11 项核验，闸门在三轮迭代后已收敛
- 参数忠实性由 `config_hash` 反证保证
- 幂等、失败隔离、孤立记录降级均已实测
- 两条独立源记录收敛到同一组数字，说明口径实现稳定

必须先解决：

1. **补验证层的会计明细可追溯**（§11-2）。
   否则扩大范围后仍只能比对绩效数字，无法审计 80 条事件具体如何入账。
   最小方案：让验证流程把内部回测的 `run_id` 透传到
   `corporate_action_applications`，或在 `summary_json` 里存
   `applied_actions` / `settled_dividends` 的汇总。

2. **明确 35 条待重放的价值排序**。
   37 条里 12 条共用 `input_hash=dc5137ab80c92d71`，
   重放它们只能验证同一组参数的稳定性，信息增益低。
   真正有增量的是剩余 2 条 41 只全池记录：
   `e725034e46ff47e5`、`b6e1155d19ba4b6a`（各约 27 分钟）。

**不建议**无条件跑完 35 条：约 13 小时里超过一半在重复验证同一组参数。

---

## 13. 最终状态

| 项 | 值 |
| --- | --- |
| 第一条 source → 新记录 | `32aead3291734f91` → `03410886d1f64fa7` |
| 第二条 source → 新记录 | `c46fa37b932944c2` → `321caeb581e54d3b` |
| 失败中间产物 | `397118a140c44f47`（`failed`，已降级保留） |
| 待重放 validation | 35 条 |
| 已重放 | 2 条 |
| 行情指纹 | 未变 |
| `integrity_check` | ok |
| 两条核验 | 11/11 全部通过 |
