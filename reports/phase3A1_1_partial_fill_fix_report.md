# 阶段3A.1.1 专项整改报告：部分成交状态逻辑修复

- 项目：A股基金量化分析 Agent（jj-agent）
- 报告时间：2026-11-11
- 范围：仅修复回测引擎部分成交状态处理，未开展 3A.2 / 3B

---

## 1. 原始问题

### 问题1：部分成交后剩余订单被拒绝，状态被错误覆盖为 rejected

`app/backtest/engine.py` 原逻辑：

```python
elif order.status not in ("rejected",):
    order.status = "partial" if order.filled_quantity > 0 else "rejected"
```

Broker 在「剩余部分资金不足/持仓不足」时已把 `order.status` 设为 `rejected`。
Engine 随后判断 `order.status not in ("rejected",)`，条件为假，直接跳过状态修正。
最终出现「已成交 400、剩余 600、状态却是 rejected」的不一致状态。

### 问题2：部分成交测试覆盖不充分

- `test_partial_sell_keeps_partial_status` 名称含 partial，实际断言的是 `status == "filled"`
  （持仓 500、委托 500、全额成交），根本没有覆盖部分成交。
- `test_engine_keeps_partial_and_defers_remainder` 断言为
  `order.status in ("partial", "filled")`，宽松到无法证明任何具体状态。

## 2. 修改文件列表

| 文件 | 修改内容 |
| --- | --- |
| `app/backtest/models.py` | 新增 `has_fill` 属性、`sync_status()` 统一状态收敛；`OrderStatus` 补充 `unfilled` |
| `app/backtest/broker.py` | 新增 `append_reason()`、`_defer()`、`_terminate()`；`execute()` 用 `sync_status` 收敛；已完成订单前置拦截 |
| `app/backtest/engine.py` | 撮合后状态处理改用 `sync_status()`；缺失行情分支保留已有成交；回测结束区分 partial / unfilled |
| `tests/test_backtest_partial_fill.py` | 修正 2 个错误测试，新增 10 个专项测试（合计 18 项） |
| `reports/phase3A1_1_partial_fill_fix_report.md` | 本报告 |
| `CHANGELOG.md`、`README.md` | 阶段3A.1.1 说明 |

**未修改**：`metrics.py`（Sharpe/Sortino/CAGR）、`portfolio.py`（账本）、`costs.py`（费率模型）、
`app/quant/*`、数据库表结构、迁移文件。

---

## 3. 修复前后的状态流转差异

### 统一状态规则（修复后）

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 完全没有成交，仍在等待 | pending | pending |
| 完全没有成交，最终成交 | filled | filled |
| 部分成交，剩余继续等待 | partial | partial |
| 部分成交，剩余被取消 | partial | partial |
| 部分成交，剩余超过延期期限 | partial | partial |
| 部分成交，剩余被拒绝 | **rejected（错误）** | **partial** |
| 完全没有成交，主动拒绝 | rejected | rejected |
| 完全没有成交，超过延期期限 | expired | expired |
| 完全没有成交，回测结束仍未成交 | unfilled | unfilled |

### 实测对比（同一天然数据：委托 1000 股，首次成交 400 股）

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 部分成交后剩余被拒 | `rejected`，成交 400，剩余 600 | `partial`，成交 400，剩余 600 |
| 部分成交后回测结束 | `partial`，成交 400，剩余 600 | `partial`，成交 400，剩余 600 |
| 部分成交后过期 | `partial`，成交 400，剩余 600 | `partial`，成交 400，剩余 600 |

上表由 `git worktree` 检出修复前提交 `9c60420` 与修复后代码分别执行同一脚本得到，非推断。

## 4. 数量处理方式

```python
quantity          # 原始委托数量，建单后不变
filled_quantity   # 累计实际成交数量
remaining_quantity = max(0, quantity - filled_quantity)   # property，不重复存储
fee               # 累计实际费用
slippage_cost     # 累计实际滑点
```

Broker 每次撮合只对剩余数量下单，并在动账本前夹紧：

```python
remaining = order.remaining_quantity
quantity = min(int(quantity), order.remaining_quantity)
```

不变量：

- `0 <= filled_quantity <= quantity`
- 已完成订单（`remaining_quantity == 0`）在 `execute()` 入口即返回
  `already_fully_filled`，不产生 Trade、不动账本、不收费
- 费用只按实际成交金额计算，`Order.fee == Σ Trade.commission`

## 5. Broker 与 Engine 的状态管理逻辑

### Order.sync_status()（唯一收敛入口）

```python
def sync_status(self, terminal: str | None = None) -> str:
    quantity = int(self.quantity)
    filled = int(self.filled_quantity)
    if filled >= quantity:
        self.status = "filled"
    elif filled > 0:
        self.status = "partial"
    elif terminal:
        self.status = terminal
    return self.status
```

关键点：`terminal` 只在完全没有成交时生效。只要有成交，
任何终态传入都会被收敛为 `partial`。

### Broker

- `_defer()`：不可成交（停牌、零成交量、涨跌停）→ 延期，
  调 `sync_status()` 不带 terminal，不会倒退。
- `_terminate()`：终态（资金不足、持仓不足）→ 调 `sync_status(terminal=...)`，
  有成交时自动变成 `partial`。
- `execute()` 入口先判断 `remaining_quantity <= 0`，拦截重复撮合。

### Engine

- 撮合成功但未满 → 有延期额度则重新入队，否则 `sync_status()` + `remainder_cancelled`
- 延期超限 → `sync_status(terminal="expired")`
- 剩余被拒 → `sync_status(terminal="rejected")`（原 `order.status not in ("rejected",)` 跳过逻辑已移除）
- 缺失行情 → 有成交时追加 `missing_quote` 原因，状态保持 `partial`
- 回测结束 → 有成交的 `sync_status()`，无成交的 `sync_status(terminal="unfilled")`

`append_reason()` 保证原因分段不重复追加。

---

## 6. 买入部分成交测试结果

| 测试 | 断言重点 | 结果 |
| --- | --- | --- |
| `test_buy_reduced_by_cash_is_partial_not_filled` | 1500 元买入 1000 股 → 成交 100、状态 partial | 通过 |
| `test_buy_partial_with_cash_shortfall_keeps_books_sane` | 成交 400、剩余 600、现金不透支、费用只按 400 股收 | 通过 |
| `test_partial_then_remainder_rejected_keeps_partial` | 首次 400，二次被拒后仍 partial | 通过 |

实测数据（人工构造，成交价 10.005）：

- 初始现金 4010 → 成交 400 股，成交金额 4002.00，佣金 5.00，剩余现金 3.00
- 剩余 600 股因 `insufficient_cash` 被拒，状态保持 `partial`

## 7. 卖出部分成交测试结果

| 测试 | 断言重点 | 结果 |
| --- | --- | --- |
| `test_partial_sell_keeps_partial_status` | 持仓 300、委托 500 → 成交 300、剩余 200、状态 **partial** | 通过 |
| `test_partial_then_defer_then_fill_remainder` | 400 成交 → 零成交量延期 → 600 补满，最终 filled | 通过 |
| `test_multiple_partial_fills_sum_to_quantity` | 300 + 200 + 500 三次成交 | 通过 |
| `test_sell_rejected_when_partial_not_allowed` | 可卖量不足且不允许部分 → rejected，成交 0 | 通过 |

`test_partial_sell_keeps_partial_status` 已从「断言 filled」修正为真正的部分成交场景。

## 8. 多次部分成交测试结果

`test_multiple_partial_fills_sum_to_quantity`（人工数据）：

| 撮合 | 可卖批次 | 成交数量 | 累计成交 | 剩余 | 状态 |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | 300 股可用 | 300 | 300 | 700 | partial |
| 2 | 200 股可用 | 200 | 500 | 500 | partial |
| 3 | 500 股可用 | 500 | 1000 | 0 | filled |

断言全部通过：

- 各笔成交量 `[300, 200, 500]`
- 合计 1000 == 原始委托量
- 累计成交量不超过委托量
- `Order.fee == Σ Trade.commission`
- `Order.slippage_cost == Σ Trade.slippage_cost`

## 9. 费用核算测试结果

| 测试 | 内容 | 结果 |
| --- | --- | --- |
| `test_fee_only_on_filled_quantity` | 成交 100 股，佣金 = max(100 × 10.005 × 0.00025, 5.0) = 5.00 | 通过 |
| `test_fee_equals_sum_of_trades_across_partial_fills` | 400 + 600 两笔成交，`Order.fee == Σ`，`Portfolio.total_fees == Order.fee` | 通过 |
| `test_full_rejection_has_zero_fill` | 完全未成交订单 `fee == 0.0` | 通过 |

费率模型未改动：`commission = max(成交金额 × commission_rate, min_commission)`，
按每笔实际成交收取最低佣金，与原设计一致。

## 10. 完整 pytest 结果

```
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

| 项目 | 数值 |
| --- | --- |
| 测试总数 | 154 |
| 通过 | 154 |
| 失败 | 0 |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 21.29s |

对比：

- 阶段3A.1 原有 144 项：全部保留并通过，无回退
- 阶段3A.1.1 新增 10 项
- 合计 154 项

`tests/test_backtest_partial_fill.py`：8 → 18 项。

日志：`logs/pytest_phase3a1_1.log`

### 状态矩阵实测（人工数据，8 个场景）

| 场景 | 实际状态 | 期望 | 成交 | 剩余 |
| --- | --- | --- | ---: | ---: |
| 完全未成交/资金不足 | rejected | rejected | 0 | 1000 |
| 完全未成交/零成交量延期 | pending | pending | 0 | 1000 |
| 部分成交/剩余被拒 | partial | partial | 400 | 600 |
| 部分成交/剩余延期 | partial | partial | 400 | 600 |
| 部分成交/剩余补满 | filled | filled | 1000 | 0 |
| 完全成交 | filled | filled | 1000 | 0 |
| 部分成交/终态收敛 unfilled | partial | partial | 400 | 600 |
| 部分成交/终态收敛 expired | partial | partial | 400 | 600 |

全部符合统一状态规则。

---

## 11. SQLite 检查结果

```
PRAGMA integrity_check → ok
```

| 表 | 记录数 |
| --- | ---: |
| `etf_daily_prices` | 116,609（未变） |
| `etf_indicator_daily` | 350,292（未变） |
| `backtest_runs` | 11（新增 1 次验证回测） |
| `backtest_orders` | 28,307 |

行情、指标、复权快照均未被本次修改触碰。

### 真实数据验证回测

```
python scripts\run_backtest.py --strategy ma_trend --ma-window 20 ^
  --codes 510300 510500 159915 510050 510880 ^
  --start 2024-01-02 --end 2026-11-09 --cash 1000000
```

run_id：`cabbfe77035d40f3`

| 检查项 | 结果 |
| --- | --- |
| 订单状态分布 | filled 603 / rejected 185 / **partial 151** / unfilled 2 |
| 有成交却标 rejected/unfilled/expired | **0** |
| 有成交有剩余却标 filled | **0** |
| 超额成交订单 | **0** |
| 订单费用 ≠ 成交费用之和 | **0** |
| `remaining_quantity` 与 `quantity - filled_quantity` 不符 | **0** |
| 账本核对 `reconciliation.ok` | `true` |

与修复前同一策略回测（`dbf4bc0e46104b23`）对比：

| 指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 订单数 | 1,094 | 941 |
| partial 订单 | **0** | **151** |
| 有成交有剩余却标 filled | **222** | **0** |

修复前 222 笔「部分成交却标 filled」的错误记录在重跑后已消失。

### 部分成交订单示例（真实数据）

| 订单 | 代码 | 数量 | 成交 | 剩余 | 状态 | 原因 |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 8 | 510880 | 163,700 | 108,100 | 55,600 | partial | reduced_by_cash;insufficient_cash;remainder_rejected |
| 14 | 510050 | 424,100 | 423,600 | 500 | partial | reduced_by_cash;insufficient_cash;remainder_rejected |
| 19 | 510880 | 112,500 | 112,000 | 500 | partial | reduced_by_cash;insufficient_cash;remainder_rejected |

这些正是修复前会被错误标成 `rejected` 的场景，现在正确保留为 `partial`。

## 12. Gitee Commit ID

| 项目 | 内容 |
| --- | --- |
| 仓库 | https://gitee.com/y-mingyu/ashare-fund-agent.git |
| 修复提交 | `8b78483` — `fix: preserve partial order state and remaining quantity` |
| 同 HEAD 合并提交 | `0610efa` — `chore: merge github mirror history into main` |
| main HEAD | `0610efa7428c28f2b1d6b39cde4b57689bef9b45` |

## 13. GitHub Commit ID

| 项目 | 内容 |
| --- | --- |
| 仓库 | https://github.com/Ymy1ovo/ashare-fund-agent-new.git |
| main HEAD | `0610efa7428c28f2b1d6b39cde4b57689bef9b45` |

## 14. 双仓是否一致

**一致。**

```
git rev-parse HEAD                    → 0610efa7428c28f2b1d6b39cde4b57689bef9b45
git ls-remote origin refs/heads/main  → 0610efa7428c28f2b1d6b39cde4b57689bef9b45  (Gitee)
git ls-remote github refs/heads/main  → 0610efa7428c28f2b1d6b39cde4b57689bef9b45  (GitHub)
```

两个仓库的 main 指向同一个 Commit，文件树哈希均为
`7cfa16a88978856ea3db1d51932705f632792d03`。

### 同步方式

1. 修复完成后先提交 `8b78483` 并推送到 Gitee（`9c60420..8b78483`）。
2. GitHub 上存在上一轮镜像时引入的 `49f9740` 合并提交，直接推送被拒
   （`rejected (fetch first)`，非快进）。
3. 拉取 GitHub 历史，用 `git merge` 建立共同祖先（`0610efa`），
   合并后工作树哈希与 `8b78483` 完全相同，代码零差异。
4. 先推 GitHub（`49f9740..0610efa`），再推 Gitee（`8b78483..0610efa`），
   使两侧 main 指向同一 Commit。

**全程未使用 `--force`，未覆盖任何他人提交，未修改 Gitee 主仓历史。**

### 交付校验

| 检查项 | 结果 |
| --- | --- |
| 重新克隆 GitHub 后 HEAD | `0610efa`（一致） |
| 文件数 | 154 |
| `broker.py` 含 `sync_status` | 5 处 |
| `engine.py` 含 `sync_status` | 6 处 |
| 专项报告存在 | 是 |
| 密钥扫描（154 文件） | 0 命中 |
| `.db` / `.env` / `logs/` / `dist/` / `.venv` / `__pycache__` | 均无 |

---

## 15. 尚未解决的问题

### 实际执行验证的项目

- 全部 154 项 pytest（含 18 项部分成交专项）
- 8 场景 Broker 状态矩阵
- 修复前后状态矩阵对比（`git worktree` 检出旧提交实跑）
- 真实历史数据回测 1 次（5 只 ETF，689 个交易日）
- SQLite `integrity_check`

### 仅通过代码检查、未单独构造用例的项目

- `cancelled` 状态：代码路径保留，但当前引擎不产生该状态，无对应测试
- 卖出场景下 `cash_shortfall_policy="reject"` 的组合行为（该策略只作用于买入分支）
- 多只 ETF 同日多笔订单中，某笔部分成交对后续订单资金顺序的影响（仅由集成测试间接覆盖）

### 已知限制（沿用阶段3A）

- 回测为价格收益口径，无分红/拆分事件数据，会低估分红贡献
- 滑点为固定 bp，无冲击成本与成交量约束
- 涨跌停为整日近似
- 债券/商品 ETF 交易规则未逐一确认
- 部分成交只支持「按可卖量/可买资金缩减」，不支持按对手盘深度撮合

### 历史数据说明

数据库中 `08a4c7f1529b42e2`、`90c76130c8884212`、`c72cc00273624760` 三个修复前产生的
回测 run 里存在 478 条「有成交却标 rejected」的历史记录，另有 4 个 run 中 2,203 条
「有剩余却标 filled」的记录。

这些历史记录未做任何修改：按项目纪律不得覆盖历史回测记录。它们只是修复前代码的产物，
重跑即可得到正确状态。本次验证产生的新 run `cabbfe77035d40f3` 已完全符合规则。

---

## 16. 结论

最重要的验收标准已满足：部分成交后，无论剩余订单被拒绝、取消、延期还是回测结束，
已成交部分完整保留，订单状态不会错误地变成 `rejected`、`unfilled` 或 `filled`。

- 统一收敛入口 `Order.sync_status()`，Broker 和 Engine 不再各自覆盖状态
- 有成交即 `filled` / `partial`，其余状态只对零成交订单生效
- 数量不变量 `0 <= filled_quantity <= quantity` 全程成立
- 费用只按实际成交计算，`Order.fee == Σ Trade.commission`
- 144 项原有测试无回退，新增 10 项专项测试，合计 154 项全部通过
