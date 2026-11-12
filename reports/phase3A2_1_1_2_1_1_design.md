# 阶段3A.2.1.1.2.1.1 设计说明：绩效总交易成本漏计税费修复

- 编写时间：2026-11-12
- 基线提交：`8cbf77e429fd71ea8fae6ed21f38ebeca39a7fe9`
- 范围：只修绩效成本统计口径，不增加功能，不进入 3B

## 1. 原始问题根因

### 1.1 缺陷代码

`app/backtest/metrics.py`（修复前）：

```python
result.total_commission = float(sum(trade.commission for trade in trades))
result.total_slippage   = float(sum(trade.slippage_cost for trade in trades))
result.total_cost = result.total_commission + result.total_slippage
```

### 1.2 为什么错

上一阶段（3A.2.1.1.2.1）把 `Trade.commission` 的语义从「全部费用」收窄为「纯佣金」，
但 `total_cost` 的公式没同步更新，仍用 `commission + slippage`。

于是 `total_cost` **漏掉了印花税与过户费**。

### 1.3 量化影响（实测）

3 只 ETF、2025-01-02 ~ 2026-11-09、非零税费、264 笔成交：

| 项目 | 数值 |
| --- | ---: |
| `total_commission`（佣金） | 25,068.8621 |
| `total_stamp_tax`（印花税） | 50,041.1562 |
| `total_transfer_fee`（过户费） | 1,000.8231 |
| `total_trade_fees`（费用合计） | 76,110.8414 |
| `total_slippage`（滑点） | 47,320.2449 |
| **修复后 `total_cost`** | **123,431.0862** |
| 修复前（旧公式） | 72,389.1069 |
| **漏计金额** | **51,041.9793** |
| **漏计比例** | **41.4%** |

每 100 元真实成本里有 41 元被隐藏。任何基于 `total_cost` 的换手成本分析、
策略比价、成本敏感性结论都会失真。

## 2. 修复后的成本口径

```python
result.total_commission    = sum(t.commission        for t in trades)   # 只含佣金
result.total_stamp_tax     = sum(t.stamp_tax         for t in trades)   # 只含印花税
result.total_transfer_fee  = sum(t.transfer_fee      for t in trades)   # 只含过户费
result.total_slippage      = sum(t.slippage_cost     for t in trades)   # 只含滑点
result.total_trade_fees    = sum(t.total_fees        for t in trades)   # 佣金+税
result.total_cost          = result.total_trade_fees + result.total_slippage
```

### 2.1 Performance 字段

| 字段 | 含义 |
| --- | --- |
| `total_commission` | 只统计佣金（含最低佣金规则） |
| `total_stamp_tax` | 只统计印花税（**新增**） |
| `total_transfer_fee` | 只统计过户费（**新增**） |
| `total_trade_fees` | 佣金 + 印花税 + 过户费（**新增**） |
| `total_slippage` | 只统计滑点 |
| `total_cost` | 佣金 + 印花税 + 过户费 + 滑点 |

恒等式：

```text
total_trade_fees == total_commission + total_stamp_tax + total_transfer_fee
total_cost       == total_trade_fees + total_slippage
```

### 2.2 不重复计算

滑点**不进入** `total_fees`（`Trade.total_fees` 只含三项现金费用），
只在 `total_cost` 末尾加一次。因此不会重复计。

最低佣金只作用于佣金本身，滑点不参与 `max(..., min_commission)`。

## 3. 检查其余成本统计位置

全文搜索 `total_cost` / `total_commission` / `total_fees` / `stamp_tax` /
`transfer_fee` / `slippage_cost` / `trade.commission` 的结果：

| 位置 | 修复前 | 处理 |
| --- | --- | --- |
| `metrics.compute_performance()` | ❌ 漏税费 | **已修** |
| `report.render_report()` 绩效表 | ❌ 显示「总费用」实为佣金 | **改为分项列示** |
| `report.render_report()` 交易明细表 | ❌ 只显示佣金列 | **改为佣金/印花税/过户费/费用合计/滑点/盈亏** |
| `validation.runner._metrics_payload()` | ✅ 复制 `performance.total_cost`，无需改 | 自动沿用正确值 |
| `scripts/run_backtest.py` | ✅ 打印 `performance.total_cost` | 自动沿用 |
| `scripts/report_backtest_3a.py` | ✅ 人工案例手算，不读 metrics | 无需改 |
| `portfolio.total_fees` | ✅ 累加传入的 `fee`（三项和） | 无需改 |
| `api.get_trades()` | ✅ 直读数据库，不做二次汇总 | 无需改 |
| `dashboard/pages/3_回测.py` | ✅ 不展示成本汇总 | 无需改 |

**结论**：只有 `metrics` 与 `report` 两处需要改，其余位置自动沿用正确值或本就不涉及。

## 4. 历史记录语义兼容

### 4.1 问题

历史 11 条回测记录的 `summary_json.performance.total_cost` 是旧公式产物。
当时 `stamp_duty_rate` 与 `transfer_fee_rate` **均为 0**（已逐条核对 `config_json`），
所以旧 `total_cost` 在数值上等于「佣金 + 滑点」，**没有失真**。

但不能「不加区分地把历史和新记录混算」——如果将来引入含税历史数据，
旧记录的 `total_cost` 就会失真。

### 4.2 兼容方案

新增成本语义标记（`app/backtest/api.py`）：

```python
COST_SEMANTICS = "commission+taxes+slippage"
```

- 新回测 `save_result()` 写入 `summary_json["cost_semantics"] = COST_SEMANTICS`
- 历史记录缺少该字段 → `cost_semantics_of()` 返回 `"legacy"`
- `describe_cost_semantics()` 返回可读说明，明确标注：
  - `legacy`：`includes_taxes = False`，附注「当时两个税率均为 0，
    total_cost = 佣金 + 滑点，与实际总成本数值一致」
  - 新语义：`includes_taxes = True`

**不猜测历史税费**：不给历史记录补造 `stamp_tax` / `total_transfer_fee`。
历史记录保持原样，只通过标记区分口径。

### 4.3 历史记录实测

| run_id | 旧 total_cost | 旧 total_commission | stamp_tax |
| --- | ---: | ---: | --- |
| `7181d2a6ed3f4555` | 595.94 | 248.86 | 无（旧语义） |
| `d08db2c030a64458` | 130,431.33 | 50,053.63 | 无（旧语义） |
| `2ecc9c0803174978` | 196,010.80 | 99,807.08 | 无（旧语义） |

这些记录**未做任何修改**，读取时按 `legacy` 口径解释。

## 5. 修改文件清单

| 文件 | 修改内容 |
| --- | --- |
| `app/backtest/metrics.py` | `total_cost` 改为 `total_trade_fees + total_slippage`；新增三个费用字段 |
| `app/backtest/report.py` | 绩效表分项列示成本；交易明细表增加税费列 |
| `app/backtest/api.py` | 新增 `COST_SEMANTICS`、`cost_semantics_of()`、`describe_cost_semantics()` |
| `app/backtest/storage.py` | 新回测 `summary_json` 写入成本口径标记 |
| `tests/test_cost_aggregation.py` | **新增** 15 项专项测试 |

## 6. 不修改的部分

- 现金结算逻辑（`portfolio.apply_buy/apply_sell`）未动
- 佣金计算公式（`order_commission` / `incremental_commission`）未动
- 印花税、过户费的费率与规则未动
- 滑点模型未动
- ETF 行情、历史回测数据、历史 validation 记录未动
- 数据库结构无变更，无需迁移

## 7. 已知限制

1. 历史记录的 `total_cost` 仍是旧语义，需通过 `cost_semantics` 字段区分读取
2. `total_cost` 只含可量化的现金费用与滑点，不含冲击成本、机会成本
3. 滑点为固定 bp 近似，非真实成交价差
4. 未对历史记录重算成本（会破坏「历史结果不被覆盖」的约束）
