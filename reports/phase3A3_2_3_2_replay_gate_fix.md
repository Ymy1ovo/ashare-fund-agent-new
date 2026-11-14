# 阶段3A.3.2.3.2 重放失败闸门修复报告

- 生成时间：2026-11-14
- 基线 HEAD：`2541fdc1bb4bfbeaaa700efd90461c927b41cfcc`（3A.3.2.3.1）
- 性质：3A.3.2.3.3 的前置条件修复

---

## 1. 起因

3A.3.2.3.3 要求在执行 P0 重放前先核实六项前置条件。实测发现四项不满足。
本文记录缺陷与修复，**不含任何历史记录的重放结果**。

---

## 2. 缺陷一：validation 闸门三值短路

### 位置

`app/replay/runner.py` `replay_validation()` 原实现：

```python
row = conn.execute("SELECT input_hash, accounting_version FROM validation_runs "
                   "WHERE validation_id=?", (result.validation_id,)).fetchone()
replay_hash = str(row[0]) if row else None
replay_acct = str(row[1]) if row and row[1] else None

if replay_acct and replay_acct != CURRENT_ACCOUNTING:   # ← 短路
    ... return FAILED
# 落到下面的 STATUS_SUCCESS
```

### 后果

`replay_acct` 为 `None` 时，`if` 短路，直接落到成功分支。实测四种情况：

| 新记录实况 | 修复前 | 修复后 |
| --- | --- | --- |
| 记录不存在（`row is None`） | **success** | failed |
| `accounting_version = None` | **success** | failed |
| `accounting_version = ''` | **success** | failed |
| `accounting_version = legacy_...` | failed | failed |
| `accounting_version = ca-v9-unknown` | failed | failed |

前三种正是「不得认定成功」的情形。而且 `replay_validation()` 完全不检查
`result` 对象本身的会计口径，只检查落库结果——落库缺失时没有任何兜底。

### 修复

```python
if row is None:
    ... FAILED（reason="重放后查不到新 validation 记录：<id>"）

replay_acct = row[1]
if not isinstance(replay_acct, str) or replay_acct != CURRENT_ACCOUNTING:
    ... FAILED（reason="重放记录会计版本异常：<repr>"）
```

删掉 `replay_acct and` 的前置短路，把「None / 空串 / 非 str」并入拒绝分支。
错误信息用 `{replay_acct!r}`，空串与 None 在日志里可区分。

---

## 3. 缺陷二：backtest 闸门真值判断

### 位置

`app/replay/runner.py` `replay_backtest()` 原实现：

```python
if result.accounting_basis != ACCOUNTING_FORMAL or not result.formal_valuation:
```

### 后果

`not 1` 为 `False`，`formal_valuation=1` 能穿过闸门并调用 `save_result`。
实测修复前 `formal_valuation=1` → `save_result` 被调用、返回 `success`。

这与 3A.3.2.2.4 修过的 `_require_formal()` 是**两处独立实现**：
当时只修了验证层，重放器这一处没跟着改。

### 修复

```python
basis = getattr(result, "accounting_basis", None)
formal = getattr(result, "formal_valuation", None)
if (basis != ACCOUNTING_FORMAL
        or not isinstance(formal, bool) or formal is not True):
    raise ReplayError(...)
```

与 `_require_formal()` 保持同一判定语义：必须是 `bool` 且 `is True`。

---

## 4. 可测缝隙：抽出 `_fetch_validation_record()`

原实现的回查语句内联在 `replay_validation()` 里，导致「查不到记录」这条
失败路径**无法在不替换整个数据库连接的前提下测试**。第一版测试用替换
`get_connection` 的方式，结果把建表等初始化一起挡掉了，测试自身失效。

修复：抽出

```python
def _fetch_validation_record(validation_id, *, db_path=None):
    with get_connection(db_path) as conn:
        return conn.execute(
            "SELECT input_hash, accounting_version FROM validation_runs "
            "WHERE validation_id=?", (validation_id,)).fetchone()
```

测试只 monkeypatch 这一个返回点，其余读写仍走真实库。
这属于为可测性做的最小重构，不改变生产行为。

---

## 5. 新增测试（26 项）

新增 `tests/test_replay_gate_3a3_2_3_2.py`，**每条都核实数据库最终状态**，
不只断言函数抛异常。

| # | 测试 | 覆盖任务书条目 | 断言库内状态 |
| ---: | --- | --- | --- |
| 1 | `test_source_validation_missing_raises` | §8-1 | `replay_attempts` 为空 |
| 2 | `test_source_validation_params_missing` | §8-2 | `failed` 行在，`validation_runs` 无新增 |
| 3 | `test_unknown_strategy_version_cannot_be_proven` | §8-3 | `failed`，reason 含「参数不可证明」 |
| 4 | `test_corporate_action_load_failure_aborts_replay` | §8-4 | `failed`，`backtest_runs` 无新增 |
| 5 | `test_missing_new_validation_record_fails` | §8-5 | `failed`，`validation_runs` 无新增 |
| 6 | `test_new_record_accounting_version_none_fails` | §8-6 | `failed`，`find_success` 为 None |
| 7 | `test_new_record_accounting_version_empty_fails` | §8-7 | `failed` |
| 8 | `test_new_record_legacy_or_unknown_version_fails` × 4 | §8-8 | 四种旧/未知/大小写变体全 `failed` |
| 9 | `test_backtest_non_boolean_formal_valuation_fails` × 8 | §8-9 | `failed`，`save_result` 未被调用，库内无新行 |
| 10 | `test_backtest_non_formal_basis_rejected` | §8-9 | `failed`，`save_result` 未被调用 |
| 11 | `test_save_failure_leaves_no_success_attempt` | §8-10 | `failed`，`backtest_runs` 行数不变 |
| 12 | `test_finish_attempt_failure_does_not_fake_success` | §8-11 | 无 `success` 行，`find_success` 为 None |
| 13 | `test_repeat_replay_does_not_duplicate_success` | §8-12/13 | `success` 行恒为 1，第二次起 `skipped` |
| 14 | `test_no_duplicate_corporate_action_booking_on_repeat` | §8-13 | 应用行与净值行数不变 |
| 15 | `test_interrupted_replay_not_reported_as_success` | §8-14 | `running` 行不被当成成功 |
| 16 | `test_history_untouched_after_failed_replay` | §8-14 | 源记录整行逐字段相等 |

参数化后共 26 个用例。

### 5.1 失败后不留下错误状态

| 检查 | 结果 |
| --- | --- |
| 是否存在失败的 success 记录 | 无：每次 `failed` 都断言 `find_success() is None` |
| 是否产生孤立新记录 | 无：每次断言目标表行数不变 |
| 是否重复分红入账 | 无：重复执行后 `corporate_action_applications` 与 `backtest_daily_nav` 行数不变 |

---

## 6. 回归结果

| 项 | 数量 |
| --- | ---: |
| 3A.3.2.3.1 基线 | 538 |
| 本轮新增 | **26** |
| **总计** | **564** |
| 通过 | **564** |
| 失败 / 跳过 / xfail | 0 / 0 / 0 |

旧 538 项未删除、未跳过、未弱化。

---

## 7. 修复后的前置条件复检

| # | 要求 | 结果 |
| --- | --- | --- |
| 1 | validation 重放严格要求 `ca-v2-receivable` | 通过 |
| 2 | None / 空串 / legacy / 未知均不得认定成功 | 通过（四种全 `failed`） |
| 3 | 新 validation 记录不存在时必须失败 | 通过 |
| 4 | backtest 严格要求 `formal_valuation is True` | 通过（`1` / `"yes"` / `1.0` 全拒） |
| 5 | 失败 attempt 保存 failed + 明确原因 | 通过 |
| 6 | 专项测试已加入，旧测试未删未弱化 | 通过（+26，旧 538 全在） |

六项全部满足，可进入 3A.3.2.3.3 的 P0 重放。

---

## 8. 未做与边界

- 未执行任何历史记录重放
- 未修改任何历史行
- 未改动公司行为会计规则、撮合逻辑、策略算法
- 未改动 `_require_formal()`（验证层闸门）——那是 3A.3.2.2.4 已验收的实现
- 测试结果是本会话本地执行结果，不是外部独立测试
