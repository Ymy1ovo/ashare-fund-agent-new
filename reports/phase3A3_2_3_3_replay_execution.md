# 阶段3A.3.2.3.3 P0 历史验证记录受控重放

- 生成时间：2026-11-14
- 执行前基线 HEAD：`c1e4027217c4d4cf01ed37dbe26fd73de5f73cd3`（3A.3.2.3.2）
- 报告范围：仅两条 P0 记录，未扩大重放范围

---

## 1. 前置条件检查

### 1.1 3A.3.2.3.2 的存在性

第一次执行本任务时，`3A.3.2.3.2` **尚未存在**（`git log` 停在 3A.3.2.3.1
的 `2541fdc`，无对应报告、无对应提交）。按任务书 §2 要求先补齐，产出
`c1e4027`（`reports/phase3A3_2_3_2_replay_gate_fix.md`，测试 538 → 564）。

### 1.2 六项要求的实测结果（补齐 3A.3.2.3.2 之后）

| # | 要求 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | validation 严格 `ca-v2-receivable` | 通过 | `replay_validation` 用 `isinstance(str) and ==` 判定 |
| 2 | None/空串/legacy/未知均失败 | 通过 | 4 种实况全 `failed` |
| 3 | 新记录不存在必须失败 | 通过 | `row is None` 分支 |
| 4 | backtest 要求 `formal_valuation is True` | 通过 | `isinstance(bool) and is True` |
| 5 | 失败 attempt 保存 failed + 原因 | 通过 | 库内实测 `failed` + 中文原因 |
| 6 | 专项测试已加入，旧测试未弱化 | 通过 | +26 项，538 项全保留 |

### 1.3 执行过程中暴露的第三个缺陷（本轮修复）

第一次执行 `32aead3291734f91` 重放时，结果被判 `failed`：

```
[FAIL] 32aead3291734f91 -> 397118a140c44f47（重放记录会计版本异常：None）
```

**根因**：`save_validation_run()` 的 INSERT 语句**不含 `accounting_version` 列**。
历史记录那一列是 `mark_legacy_records.py` / `finalize_replay_records.py`
事后 UPDATE 上去的；而 `replay_validation()` 从不补这一步。
于是任何新验证记录的该列天生为 `NULL`，闸门永远过不去。

**这不是闸门太严，是重放器漏写。** 修复：

```python
def _stamp_replay_validation(validation_id, *, db_path=None):
    """给本次新建的 validation 记录补上 ca-v2-receivable 标记。
    只写刚创建的 validation_id，不触碰历史行。"""
```

同时补 `_reject_replay_record()`：闸门失败时把刚建出来的记录**降级为
`failed` 并写明原因**，而不是留下一条 `status=success` 的孤立记录。

第一次失败留下的 `397118a140c44f47` 已按此规则降级，保留在库内可追溯，
未删除。

新增 2 项测试（`test_replay_stamps_accounting_version_on_new_record`、
`test_failed_gate_downgrades_orphan_record`），测试 564 → **566**。

---

## 2. 两条源记录的重放前盘点

| 项 | `32aead3291734f91` | `c46fa37b932944c2` |
| --- | --- | --- |
| 记录存在 | 是 | 是 |
| 分类 | `legacy` | `legacy` |
| 参数证明 | `proven` | `proven` |
| 可重放 | 是 | 是 |
| 策略 | ma_trend v1.0.0 | ma_trend v1.0.0 |
| 样本内 | 2021-01-04 ~ 2024-12-31 | 2021-01-04 ~ 2024-12-31 |
| 样本外 | 2025-01-02 ~ 2026-11-09 | 2025-01-02 ~ 2026-11-09 |
| ETF 池 | 41 只（`pool_mode=all`） | 41 只（`pool_mode=all`） |
| 参数网格 | 5/10/20/30/60/120/250 | 5/10/20/30/60/120/250 |
| `config_hash` | `11ce7469245afab0` | `5bc9252086c515e2` |
| `input_hash` | `dbfac114e6900c87` | `2ac80bcdfb5459c5` |
| 源结论 | 有条件通过 | 有条件通过 |

**28 个参数全部由 `config_hash` 反证命中**，无一缺失：

资金 1,000,000 / 佣金 0.00025 / 最低佣金 5.0 / 滑点 5 bps /
执行价 open / 延期 3 日 / 容忍带 0.02 / 年化 252 / 无风险 0.0 /
指标版本 `v1.0.2-30b821a1af15` / WF 网格 `[5,20,60]` / 训练 24 月 /
验证 6 月 / 步长 6 月 / 覆盖率 0.95 / 环境代理 `510300` / 环境 MA 250 /
最小样本 120 日。

### 2.1 日期端点的说明

`32aead3291734f91` 存的是 `is_start=2021-01-04`、`oos_start=2025-01-02`
（请求日对齐到下一交易日的结果），反证命中的是请求日 `2021-01-01` /
`2025-01-01`。`c46fa37b932944c2` 存的就是 `2021-01-04` / `2025-01-02`，
反证命中的也是存储值。

两者实际跑出来的交易日历完全相同（源记录里存的对齐后日期一致），
不存在「用默认值覆盖历史参数」。

---

## 3. dry-run 结果

两条都执行了 `--dry-run`，输出完整 28 个参数、源记录 ID、
预计新记录类型、当前会计版本。

dry-run 前后数据库计数：

| 项 | dry-run 前 | dry-run 后 |
| --- | ---: | ---: |
| `validation_runs` | 44 | 44 |
| `replay_attempts` | 1 | 1 |
| `backtest_runs` | 12 | 12 |

行情指纹 dry-run 前后均为 `d54727c0…`。**无写入。**

dry-run 未出现参数不一致、数据缺失或无法解释的警告。

---

## 4. 两条记录的执行结果

### 4.1 第一条：`32aead3291734f91`

| 项 | 值 |
| --- | --- |
| 首轮结果 | **failed**（`397118a140c44f47`，accounting_version=None） |
| 修复后重跑 | **success** → `03410886d1f64fa7` |
| 耗时 | 约 27 分钟 |
| 源 input_hash | `dbfac114e6900c87` |
| 新 input_hash | `1263f78d8a63e309` |
| 新 accounting_version | `ca-v2-receivable` |
| 新结论 | 有条件通过 |

### 4.2 第二条：`c46fa37b932944c2`

| 项 | 值 |
| --- | --- |
| 结果 | **success** → `321caeb581e54d3b` |
| 耗时 | 约 21 分钟 |
| 源 input_hash | `2ac80bcdfb5459c5` |
| 新 input_hash | `6da51a1c462b7c65` |
| 新 accounting_version | `ca-v2-receivable` |
| 新结论 | 有条件通过 |

### 4.3 逐项核验（任务书 §6 的 11 项）

| # | 检查 | 第一条 | 第二条 |
| --- | --- | --- | --- |
| 1 | 原始记录仍存在且内容不变 | 通过 | 通过 |
| 2 | 新记录真实存在 | 通过 | 通过 |
| 3 | 可追溯到 source_validation_id | 通过 | 通过 |
| 4 | `accounting_version == ca-v2-receivable` | 通过 | 通过 |
| 5 | 正式会计标记正确 | 通过 | 通过 |
| 6 | attempt 最终 `success` | 通过 | 通过 |
| 7 | attempt 与新记录关联正确 | 通过 | 通过 |
| 8 | 参数与源一致（区间/池/网格） | 通过 | 通过 |
| 9 | 事件摘要与实际输入一致 | 通过 | 通过 |
| 10 | input_hash 含行情+策略+事件指纹 | 通过 | 通过 |
| 11 | 未修改行情/指标/事件/历史 | 通过 | 通过 |

第 1 项用的是执行前全字段快照比对：`SELECT *` 取出的整行，
逐字段 `==` 判定，两条均为 `True`。

---

## 5. 新旧口径对照

### 5.1 第一条

| 指标 | 旧口径 `32aead…` | 新口径 `034108…` |
| --- | ---: | ---: |
| 样本内总收益 | −16.3259% | **+13.6776%** |
| 样本内 CAGR | −4.5341% | +3.3937% |
| 样本内 Sharpe | 0.1058 | 0.2522 |
| 样本内 Sortino | 0.1429 | 0.3437 |
| 样本内最大回撤 | −32.8057% | −13.8537% |
| 样本内交易次数 | 1,199 | 1,270 |
| 样本外总收益 | +32.2111% | **+20.1146%** |
| 样本外 CAGR | +17.0898% | +10.9107% |
| 样本外 Sharpe | 0.7859 | 0.7210 |
| 样本外 Sortino | 1.5408 | 0.9880 |
| 样本外最大回撤 | −24.5352% | −18.2881% |
| 样本外交易次数 | 413 | 419 |
| 最优参数 | MA250 | MA250 |
| Walk-Forward | 8/8 | 8/8 |
| 结论 | 有条件通过 | 有条件通过 |

### 5.2 第二条

| 指标 | 旧口径 `c46fa3…` | 新口径 `321cae…` |
| --- | ---: | ---: |
| 样本内总收益 | +10.8689% | **+13.6776%** |
| 样本内 CAGR | +2.7224% | +3.3937% |
| 样本内 Sharpe | 0.1776 | 0.2522 |
| 样本内 Sortino | 0.2409 | 0.3437 |
| 样本内最大回撤 | −13.7331% | −13.8537% |
| 样本内交易次数 | 1,249 | 1,270 |
| 样本外总收益 | +20.2447% | **+20.1146%** |
| 样本外 CAGR | +10.9785% | +10.9107% |
| 样本外 Sharpe | 0.7290 | 0.7210 |
| 样本外 Sortino | 0.9993 | 0.9880 |
| 样本外最大回撤 | −18.1127% | −18.2881% |
| 样本外交易次数 | 419 | 419 |
| 最优参数 | MA250 | MA250 |
| Walk-Forward | 8/8 | 8/8 |
| 结论 | 有条件通过 | 有条件通过 |

### 5.3 两条新结果完全一致

`03410886d1f64fa7` 与 `321caeb581e54d3b` 的所有绩效指标逐项相同。

这是**预期结果**：两条源记录的参数完全相同（只是记录在不同时间点写入，
`config_hash` 不同是因为字段集版本差异），在新会计口径下必然收敛到同一组数字。

### 5.4 差异归因

| 区间 | 差异来源 | 判定 |
| --- | --- | --- |
| 第一条样本内 −16.33% → +13.68% | **会计口径**（旧口径把分红当价格下跌，从不入账） | 口径差异，非错误 |
| 第一条样本外 +32.21% → +20.11% | 同上；旧口径在样本外高估约 12 pp | 口径差异，非错误 |
| 第二条样本内 +10.87% → +13.68% | 同上，但幅度小（该记录写于 3A.3.2 之后，已有部分修复） | 口径差异 |
| 第二条样本外 +20.24% → +20.11% | 同上，仅 −0.13 pp | 口径差异 |

**行情数据未变**：新旧记录 `data_fingerprint.sha256` 均为
`d54727c0a76a1b09…`。

**参数未变**：由 `config_hash` 反证保证。

**策略算法未变**：本轮未改动 `app/backtest/strategies/`。

---

## 6. 公司行为事件处理情况

| 项 | 数值 |
| --- | ---: |
| 区间内事件（2021-01-04 ~ 2026-11-09） | 81 条 |
| 其中可应用（证据等级达标） | 81 条 |
| 事件集 digest | `8aeafc0a2d17fd2ce2a65983eb81129d…` |
| 涉及标的 | 27 只 |

新记录 `03410886d1f64fa7` / `321caeb581e54d3b` 的会计口径链：

```
除息日 → 确认应收（dividend_receivable，计入总资产，不进现金）
发放日 → 应收转现金（dividend_receivable −，cash +）
总资产 = cash + market_value + dividend_receivable
```

### 6.1 一个必须说明的口径事实

`corporate_action_applications` 与 `dividend_receivables` 里，
**本轮两条新记录的行数为 0**。

原因是：验证流程内部每次都生成新的临时 `run_id` 跑回测，
验证记录本身的 `validation_id` 不会出现在这两张业务表里。
这两张表的键是**回测 run_id**，不是 validation_id。历史 39 条 legacy
验证记录同样没有对应行——这是既有设计，不是本轮引入的缺陷。

**因此**：本报告能核对「事件集 digest 一致」「区间内 81 条全部可应用」，
但**无法从数据库直接给出「本次重放的分红应收金额与到账笔数」**。
该数字在 `scripts/replay_3a3_2.py --legacy-comparison` 这类
**单策略内存回测**里可得（3A.3.2.1 报告：样本外 applied 30 / settled 23）。

这一点属于**口径不可比**，按任务书要求明确标记，不伪造数字。

---

## 7. 幂等性检查

两条记录重放完成后，再次用相同 `--source` 执行：

```
[SKIP] 32aead3291734f91 -> 03410886d1f64fa7（已存在成功重放，跳过）
[SKIP] c46fa37b932944c2 -> 321caeb581e54d3b（已存在成功重放，跳过）
```

| 检查 | 结果 |
| --- | --- |
| 是否重复生成新记录 | 否，`validation_runs` 保持 47 条不变 |
| 是否识别已成功 | 是，返回 `skipped` + 原 replay_id |
| 是否重复计入分红 | 无新记录产生，不存在重复入账 |
| 是否改变已有新记录 | 否 |
| 是否产生冲突的成功记录 | 否，每个 source 恰好 1 条 `success` |

未使用 `--force`。

---

## 8. 异常测试结果

新增 `tests/test_replay_gate_3a3_2_3_2.py`（28 项，含 2 项本轮补的执行缺陷测试）。
每条都核实数据库最终状态。

| 任务书条目 | 测试 | 库内状态断言 |
| --- | --- | --- |
| §8-1 源记录不存在 | `test_source_validation_missing_raises` | attempt 表为空 |
| §8-2 原始参数缺失 | `test_source_validation_params_missing` | `failed` 行在，无新记录 |
| §8-3 策略版本未知 | `test_unknown_strategy_version_cannot_be_proven` | `failed` |
| §8-4 事件表读取失败 | `test_corporate_action_load_failure_aborts_replay` | `failed`，backtest 无新增 |
| §8-5 新记录查不到 | `test_missing_new_validation_record_fails` | `failed`，无新增 |
| §8-6 version=None | `test_new_record_accounting_version_none_fails` | `failed` |
| §8-7 version='' | `test_new_record_accounting_version_empty_fails` | `failed` |
| §8-8 version=旧/未知 | `test_new_record_legacy_or_unknown_version_fails` ×4 | 四种全 `failed` |
| §8-9 正式标记错误 | `test_backtest_non_boolean_formal_valuation_fails` ×8 | `failed`，`save_result` 未调 |
| §8-10 保存失败 | `test_save_failure_leaves_no_success_attempt` | `failed`，行数不变 |
| §8-11 状态更新失败 | `test_finish_attempt_failure_does_not_fake_success` | 无 `success` 行 |
| §8-12 重复执行幂等 | `test_repeat_replay_does_not_duplicate_success` | `success` 恒为 1 |
| §8-13 不产生重复成功 | `test_no_duplicate_corporate_action_booking_on_repeat` | 应用行/净值行不变 |
| §8-14 中断不伪装成功 | `test_interrupted_replay_not_reported_as_success` | `running` 不算成功 |

### 8.1 特别检查

| 检查 | 结果 |
| --- | --- |
| 失败后是否留下错误的 success 记录 | 无：`test_failed_gate_downgrades_orphan_record` 断言降级为 `failed` |
| 是否产生孤立的新记录 | 实测发生过一次（`397118a140c44f47`），已降级保留，未删除 |
| 是否重复分红入账 | 无：重复执行后业务表行数不变 |

---

## 9. SQLite 完整性

```
PRAGMA integrity_check -> ok
```

| 表 | 执行前 | 执行后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_versions` | 704 | 704 |
| `backtest_runs` | 12 | 12 |
| `validation_runs` | 44 | **47** |
| `replay_attempts` | 1 | **4** |

新增 3 条 validation 行（2 条成功 + 1 条失败降级）、3 条 attempt 行。

---

## 10. 原始数据未被修改的证据

| 证据 | 值 |
| --- | --- |
| 行情指纹（执行前） | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 行情指纹（执行后） | 同上 |
| 行数 | 116,609（不变） |
| 源记录 `32aead3291734f91` 全字段 | 与执行前快照逐字段相等 |
| 源记录 `c46fa37b932944c2` 全字段 | 与执行前快照逐字段相等 |
| `corporate_actions` | 166（不变） |
| `corporate_action_versions` | 704（不变） |

两条源记录的执行前快照保存在 `data/_snapshot_before.json`（本地，未提交）。

---

## 11. 遗留问题和风险

1. **`397118a140c44f47` 是一条失败的中间产物**，已降级为 `failed` 并保留
   `error_message`。它是首次执行的审计痕迹，不删除。盘点时该行被归入
   `unknown_legacy`（`accounting_version` 为 NULL）。

2. **新记录的公司行为明细无法从 validation 层直接查到**（§6.1）。
   验证记录不持有 `run_id`，`corporate_action_applications` 的键是回测 run_id。
   若要审计分红应收金额，需跑单策略内存回测或给验证层增加 run_id 传递。

3. **两条重放各约 21~27 分钟**，35 条待重放全量约 13 小时。
   本轮按要求只跑 2 条。

4. **`_stamp_replay_validation` 是对新记录的 UPDATE**，
   与「不修改历史记录」不冲突（只写刚创建的 validation_id），
   但它确实是重放路径上唯一的新增写操作，需在后续审计中保持可见。

5. 测试结果是本会话本地执行结果，不是外部独立测试。

---

## 12. 是否建议扩大历史重放范围

**建议扩大，但需先满足两个前提。**

支持理由：

- 两条 P0 重放均已通过全部 11 项核验，闸门有效
- 参数忠实性由 `config_hash` 反证保证，不是默认值重建
- 幂等与失败隔离已实测
- 两条独立源记录收敛到同一组数字，说明会计口径实现稳定

前提：

1. **先补验证层的会计明细可追溯**（§11-2）。
   否则扩大范围后仍然只能比对绩效数字，无法审计「81 条事件具体如何入账」。
2. **明确 35 条待重放记录的执行价值排序**。
   其中 12 条共用 `input_hash=dc5137ab80c92d71`，重放价值低；
   真正有信息增益的是 4 条 41 只全池记录（已完成 2 条，剩
   `e725034e46ff47e5`、`b6e1155d19ba4b6a`）。

**不建议**无条件跑完 35 条：约 13 小时中有一半是重复验证同一组参数。

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
