# 阶段3A.3.2.2.2 公司行为安全边界最终修复

- 生成时间：2026-11-13
- 基线提交：`8f86859edc5cf5abf09734266a34d3823c91b9d6`
- 性质：**安全边界修复**，不改变任何行情数据，不调整策略参数

## 1. 问题1：公司行为加载失败必须 fail closed

### 1.1 根因

`app/backtest/engine.py::_load_corporate_actions()`：

```python
try:
    actions = load_actions(...)
except Exception as exc:                      # ← 吞掉一切异常
    self.notes.append(f"公司行为：事件表不可用（{type(exc).__name__}），按旧口径回测")
    return []                                # ← 静默返回空列表
```

事故路径：事件表缺失 / 迁移未完成 / SQL 失败 / 反序列化失败
→ 异常被吞 → 引擎拿到空事件集 → 按旧口径跑完
→ 产出一条 `status=success`、`formal_valuation=True` 的回测记录
→ **净值漏记全部公司行为，但外观完全正常**。

这是本轮最严重的问题：账本错了，结果却看起来合法。

### 1.2 修复

新增专用异常 `CorporateActionLoadError(BacktestError)`：

```python
try:
    actions = load_actions(...)
except Exception as exc:
    raise CorporateActionLoadError(
        f"公司行为事件加载失败（{type(exc).__name__}: {exc}）。"
        "apply_corporate_actions=True 时不允许静默降级为旧会计口径；"
        "请检查事件表是否存在、迁移是否完成，或显式设置 "
        "apply_corporate_actions=False 后重跑（该结果不得用于正式评价）。"
    ) from exc
```

上抛后引擎 `run()` 异常退出，**不产出任何回测结果**，
数据库里不会留下 `status=success` 的记录。

新增 `_validate_loaded_actions()`，逐条校验事件结构：

| 校验项 | 不通过时 |
| --- | --- |
| `code` 非空字符串 | 抛 `CorporateActionLoadError` |
| `action_type` 非空 | 抛 |
| `ex_date` / `effective_date` 是 `date` 类型 | 抛 |
| 拆分/合并 `share_ratio > 0` | 抛 |
| 分红 `cash_per_share > 0` | 抛 |

**不合法事件不静默过滤**——那是另一种形式的降级。

### 1.3 显式关闭时的标记

`apply_corporate_actions=False` 是唯一允许的关闭方式，且必须留下标记：

| 字段 | 正式口径 | 关闭时 |
| --- | --- | --- |
| `BacktestResult.accounting_basis` | `formal_receivable` | **`disabled_non_official`** |
| `BacktestResult.formal_valuation` | `True` | **`False`** |
| `notes` | — | 「本次结果使用非正式会计口径，不得作为正式策略评价依据」 |
| `as_meta()` | 输出两字段 | 输出两字段 |

### 1.4 覆盖测试（5 项）

| 测试 | 覆盖 |
| --- | --- |
| `test_missing_action_table_raises` | 事件表被 DROP → 抛错 |
| `test_broken_action_row_raises` | 表结构缺列 → 抛错 |
| `test_invalid_action_structure_raises` | 脏数据（比例 NULL）→ 抛错 |
| `test_disable_flag_marks_non_formal` | 关闭时标记非正式 |
| `test_formal_run_keeps_formal_basis` | 正常时标记正式 |

## 2. 问题2：现金分红必须要求真实登记日

### 2.1 根因

分红资格由**权益登记日**决定，但代码有两处用除息日兜底：

```python
# engine.py 索引构建
lock_day = action.record_date or action.ex_date

# engine.py 阻断判断
record = action.record_date or action.ex_date
```

`record_date` 缺失时把除息日当登记日，等于**伪造权益登记证据**。

### 2.2 修复

**构造阶段强制**（`CorporateAction.__post_init__`）：

| 字段 | 要求 | 违反时 |
| --- | --- | --- |
| `record_date` | 必须存在 | 抛「缺少权益登记日，不得用除息日替代」 |
| `pay_date` | 必须存在 | 抛「缺少现金发放日」 |
| `cash_per_share` | > 0 | 抛（原有） |
| `record_date <= ex_date` | 必须 | 抛「晚于除息日」 |
| `pay_date >= ex_date` | 必须 | 抛「早于除息日」 |

**删除全部回退**：

```python
# 修复后
record_index.setdefault(action.record_date, []).append(action)
record = action.record_date
```

全库复查：`grep -n 'record_date or'` → **0 处**。

### 2.3 阻断原因细分

`_record_holding_block_reason()` 返回 `(原因描述, reason_code)`：

| reason_code | 触发条件 |
| --- | --- |
| `missing_record_date` | `record_date is None`（构造阶段已拦，防御性保留） |
| `missing_record_date_holding` | 登记日在区间内但未生成日终快照 / 早于回测起点 |
| `invalid_record_date` | 登记日不在回测交易日历中 |
| `missing_pay_date` | 发放日缺失（构造阶段已拦，防御性保留） |

### 2.4 覆盖测试（5 项）

| 测试 | 覆盖 |
| --- | --- |
| `test_cash_distribution_requires_pay_date` | 缺 pay_date → 抛 |
| `test_cash_distribution_requires_cash_per_share` | 缺金额 → 抛 |
| `test_record_date_after_ex_date_rejected` | 登记日晚于除息日 → 抛 |
| `test_pay_date_before_ex_date_rejected` | 发放日早于除息日 → 抛 |
| `test_blocked_reason_missing_record_date_holding` | 登记日非交易日 → `invalid_record_date` |

原有 `test_dividend_requires_record_date_in_range` 与
`test_secondary_dividend_with_unverified_record_date_not_applied`
**升级为更严格断言**：从「引擎阻断」改为「构造阶段即拒绝」。

## 3. 问题3：同日登记日与除息日的成交时序

### 3.1 根因

主循环原顺序：

```
0) _apply_corporate_actions()   ← 开盘前，此时当日成交尚未发生
1) 开盘撮合
2) _capture_dividend_shares()   ← 收盘后（这一处在，但开盘前那段会抢先）
```

对于 `record_date == ex_date` 的分红：
`_apply_corporate_actions` 在**开盘前**执行，
此时 `_dividend_locked_shares` 里没有当日持仓
（登记日捕获在收盘后才跑），于是：
- 若前一日有持仓 → `record_index` 命中前一日吗？不会，key 是 `record_date`
- 实际走的是「未锁定 → 阻断」分支

结果：当日买入的份额拿不到分红，当日行情走势正确的场景反而被误判。

### 3.2 修复

拆成**两段处理**：

```
开盘前：
  _apply_corporate_actions()    ← 份额调整 + 登记日已过去的现金分红
  若 record_date == ex_date → 放入 _deferred_dividends，跳过

开盘撮合（当日成交完成）

收盘后：
  _capture_dividend_shares()    ← 普通登记日锁定
  _confirm_same_day_dividends() ← 同日分红：先锁定收盘持仓，再确认应收
  然后才做收盘估值
```

关键代码：

```python
if action.record_date == action.ex_date:
    self._deferred_dividends.append(action)
    continue
```

```python
def _confirm_same_day_dividends(self, trade_date, portfolio, bars, rules):
    # 当日收盘后持仓就是登记在册份额
    self._dividend_locked_shares[action.action_id] = portfolio.quantity(action.code)
    ...
    self._confirm_receivable(action, impact, portfolio)
    if action.pay_date == trade_date:
        self._settle_dividends_on(trade_date, portfolio)
```

### 3.3 其他配套修复

| 项 | 修复 |
| --- | --- |
| 重复确认 | `_confirm_receivable` 检查 `_pending_receivable`，已确认则跳过 |
| 重复写库 | 分红走 `_confirm_receivable` 内部持久化，主流程不再二次 `record_application` |
| 到账时点 | `_settle_dividends_on()` 抽取为独立方法，开盘前调用一次 |
| 登记日非交易日 | `invalid_record_date` fail closed，不回退 ex_date |
| 登记日后卖出 | 已锁定份额不因卖出改变（原有行为，新增测试固化） |

### 3.4 覆盖测试（5 项）

| 测试 | 覆盖 |
| --- | --- |
| `test_same_day_record_and_ex_date_buying_today_gets_dividend` | 当日买入 → 享有分红（收盘定稿） |
| `test_same_day_record_and_ex_date_selling_today_reduces_dividend` | 当日卖出 → 不享有 |
| `test_same_day_dividend_not_locked_before_fills` | 锁定值 == 当日收盘持仓，不等于开盘前持仓 |
| `test_same_day_dividend_settles_on_pay_date` | 应收在发放日才转现金 |
| `test_same_day_dividend_not_double_confirmed` | 应收峰值 == 单次金额，到账仅 1 笔 |

## 4. 本库实际影响

### 4.1 同日事件数量

```sql
SELECT COUNT(*) FROM corporate_actions
WHERE action_type='cash_distribution' AND record_date = ex_date;  -- 4
```

| action_id | 代码 | 除息日 | 是否在回测区间 |
| ---: | --- | --- | --- |
| 6 | `159901` | 2007-07-11 | 否 |
| 38 | `511220` | 2015-06-18 | 否 |
| 39 | `511220` | 2015-09-21 | 否 |
| 60 | `159920` | 2018-06-22 | 否 |

**4 条同日事件全部在 2021 年前**，不在本次回测区间，
因此**时序修复不影响任何样本内/样本外结果**。

区间内 57 条分红的登记日与除息日间隔为 1~3 个交易日，
全部走「登记日已过去」的原有路径。

### 4.2 缺失字段事件

| 检查 | 数量 |
| --- | ---: |
| `record_date IS NULL` 的分红 | **0** |
| `pay_date IS NULL` 的分红 | **0** |

强制校验**不会拒绝任何现有事件**。

## 5. 测试结果

| 项 | 数量 |
| --- | ---: |
| 基线（3A.3.2.2.1 完成时） | **469** |
| 本轮新增 | **15** |
| **总计** | **484** |
| 通过 | **484** |
| 失败 | **0** |
| 跳过 | **0** |
| xfail | **0** |

`tests/test_corporate_actions.py`：**97 passed**（基线 82 + 15）
其余测试：**387 passed**

### 5.1 本轮 15 项明细

| # | 测试 | 归属问题 |
| ---: | --- | --- |
| 1 | `test_missing_action_table_raises` | 问题1 |
| 2 | `test_broken_action_row_raises` | 问题1 |
| 3 | `test_invalid_action_structure_raises` | 问题1 |
| 4 | `test_disable_flag_marks_non_formal` | 问题1 |
| 5 | `test_formal_run_keeps_formal_basis` | 问题1 |
| 6 | `test_cash_distribution_requires_pay_date` | 问题2 |
| 7 | `test_cash_distribution_requires_cash_per_share` | 问题2 |
| 8 | `test_record_date_after_ex_date_rejected` | 问题2 |
| 9 | `test_pay_date_before_ex_date_rejected` | 问题2 |
| 10 | `test_blocked_reason_missing_record_date_holding` | 问题2 |
| 11 | `test_same_day_record_and_ex_date_buying_today_gets_dividend` | 问题3 |
| 12 | `test_same_day_record_and_ex_date_selling_today_reduces_dividend` | 问题3 |
| 13 | `test_same_day_dividend_not_locked_before_fills` | 问题3 |
| 14 | `test_same_day_dividend_settles_on_pay_date` | 问题3 |
| 15 | `test_same_day_dividend_not_double_confirmed` | 问题3 |

### 5.2 升级但未新增的测试（2 项）

| 测试 | 改动 |
| --- | --- |
| `test_dividend_requires_record_date_in_range` | 从「引擎阻断」改为「构造阶段拒绝」 |
| `test_secondary_dividend_with_unverified_record_date_not_applied` | 同上 |

**断言更严，不是更松。**

## 6. 其他验证

### 6.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/<最新>` | 200 |
| `GET /api/validations/not_exist` | 404 |

`SMOKE_FAILED: 无`

### 6.2 Streamlit AppTest

| 页面 | 异常 | 错误 |
| --- | --- | :---: |
| `dashboard/pages/3_回测.py` | 0 | 0 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 |

### 6.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 6.4 迁移幂等性

在备份副本上连续两次 `init_db()`：

| 表 | 前 | 后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 44 | 44 
|
| `backtest_runs` | 11 | 11 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_applications` | 3,787 | 3,787 |
| `corporate_action_versions` | 704 | 704 |
| `dividend_receivables` | 785 | 785 |

数据未变，`integrity ok`。本轮**无 schema 变更**。

### 6.5 事件对账

`python scripts/reconcile_events.py` → **14 项校验，失败 0**

### 6.6 行情指纹

| 项 | 值 |
| --- | --- |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 行数 | 116,609 |
| 本轮是否改变 | **否**（连续第六阶段不变） |

### 6.7 历史记录完整性

| 表 | 数量 | 是否被删改 |
| --- | ---: | :---: |
| `backtest_runs` | 11 | **否** |
| `validation_runs` | 44 | **否** |
| `corporate_actions` | 166 | **否** |
| `corporate_action_versions` | 704 | **否** |

## 7. 样本外重放结果

### 7.1 本轮 vs 上一版本

| run | 指标 | 3A.3.2.2.1 | **本轮** | 差 |
| --- | --- | ---: | ---: | ---: |
| 样本外 MA250 | 总收益 | 20.1146% | **20.1146%** | **0** |
| 样本外 MA250 | Sharpe | 0.7210 | **0.7210** | 0 |
| 样本外 MA250 | 最大回撤 | −18.2881% | **−18.2881%** | 0 |
| 样本外 MA250 | 交易次数 | 419 | **419** | 0 |
| 样本外 MA250 | 总成本 | 9,479.81 | **9,479.81** | 0 |
| 样本外 B&H | 总收益 | 19.3094% | **19.3094%** | 0 |
| 样本内 MA250 | 总收益 | 13.6776% | **13.6776%** | 0 |
| 样本内 MA250 | Sharpe | 0.2522 | **0.2522** | 0 |

**全部指标完全不变。**

### 7.2 为什么完全不变

三个修复都是**边界防护**，不改变任何正常路径的计算：

| 修复 | 正常路径影响 |
| --- | --- |
| 问题1 fail closed | 正常加载成功时不触发 |
| 问题2 强制字段 | 库内 0 条缺字段事件，不触发 |
| 问题3 同日时序 | 4 条同日事件全在 2021 年前，区间内 0 条 |

**这是正确的结果**：安全加固不应该改变数字。
若指标变了，说明修复侵入了正常路径，那才是问题。

### 7.3 事件指纹

| 区间 | 应用事件数 | 指纹 |
| --- | ---: | --- |
| 样本内 | 29 | `855dc11a43a8…` |
| 样本外 | 30 | `d87fb1e3c926…` |

与 3A.3.2.2.1 完全一致——本轮未修改事件内容。

## 8. 非正式口径与正式口径的边界

### 8.1 正式口径（可进入策略评价）

| 条件 | 要求 |
| --- | --- |
| `config.apply_corporate_actions` | `True`（默认） |
| 事件表加载 | **必须成功**，失败即中止 |
| 事件结构 | **必须合法**，不合法即中止 |
| 分红字段 | `record_date` / `ex_date` / `pay_date` / `cash_per_share` 齐全 |
| 登记日持仓 | 必须真实取得 |
| `BacktestResult.formal_valuation` | `True` |
| `BacktestResult.accounting_basis` | `formal_receivable` |

### 8.2 非正式口径（不得进入策略评价）

| 条件 | 标记 |
| --- | --- |
| `apply_corporate_actions=False` | `accounting_basis=disabled_non_official`，`formal_valuation=False` |

**除这一种外不存在任何非正式入口**。
加载失败不再是一条「降级路径」，而是一条「中止路径」。

### 8.3 历史遗留标记

| 标记 | 记录数 |
| --- | ---: |
| `legacy_corporate_action_accounting` | 39 validation + 11 backtest |
| `ca-v2-receivable` | 4 validation |

这些是历史口径标记，与本轮的 `formal_valuation` 是两层概念：
前者标记「哪套会计规则」，后者标记「本次运行是否可信」。

## 9. 修改文件

| 文件 | 改动 |
| --- | --- |
| `app/backtest/engine.py` | 新增 `CorporateActionLoadError`、`_validate_loaded_actions`、`_record_holding_block_reason`、`calendar_has`、`_confirm_receivable`、`_settle_dividends_on`、`_confirm_same_day_dividends`、`_deferred_dividends`；主循环拆分两段处理；删除 `record_date or ex_date` 回退；去重复写库 |
| `app/backtest/corporate_actions.py` | `__post_init__` 强制分红四字段与日期顺序 |
| `tests/test_corporate_actions.py` | 新增 15 项，升级 2 项 |

**未修改**：`portfolio.py`、`db.py`、`models.py`、`broker.py`、`config.py`、任何策略代码、任何报告数据源。

## 10. 数据库变化

| 项 | 变化 |
| --- | --- |
| schema | **无变更** |
| 行情 | **无变更** |
| 事件 | **无变更**（166 条） |
| 版本表 | **无变更**（704 条） |
| 回测记录 | **无新增正式记录** |
| `integrity_check` | ok |
| 数据库大小 | 272,003,072 字节 |
| 备份 | `data/backups/fund_agent_pre_3a3_2_2_2_20261113.db`（272,003,072 字节） |

## 11. 结论

| 问题 | 根因 | 修复 | 是否改变结果 |
| --- | --- | --- | --- |
| 数据加载失败静默降级 | 吞异常 + 返回空列表 | 抛 `CorporateActionLoadError` 中止；结构校验；非正式标记 | 否（正常路径不触发） |
| 分红登记日可缺省 | `record_date or ex_date` 兜底 | 构造阶段强制四字段；删除全部回退；阻断原因细分 | 否（库内 0 条缺字段） |
| 同日登记/除息时序 | 分红在开盘前确认，当日成交未发生 | 拆两段：同日分红推迟到收盘后；幂等保护 | 否（区间内 0 条同日事件） |

**三个修复都是安全边界，不改变任何历史数字。**
这是预期的正确行为：加固不应影响正常路径。
