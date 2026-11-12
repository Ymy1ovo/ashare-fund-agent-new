# 阶段3A.2.1.1.2 设计说明：佣金累计模型与零碎股完整清仓

- 编写时间：2026-11-12
- 基线提交：`6c9fedf5a64674e53ce50c6b75b5640d92d31110`
- 范围：只修三个已知缺陷，不进入 3A.3 / 3B

## 1. 问题一：最低佣金被重复收取

### 1.1 原模型（per_fill）

```python
fee = commission(gross, self.config.costs)   # max(gross × 费率, 5 元)
```

每次撮合都独立调用，同一订单分两次成交就收两次 5 元。

**实测**：300 + 200 两笔卖出，原模型收 5.00 + 5.00 = **10.00 元**，
但两笔累计金额约 5,000 元，按 0.025% 只需 1.25 元，应收上限是 **5.00 元**。

### 1.2 新模型（per_order，默认）

```text
订单累计应收佣金 = max(累计成交金额 × 佣金费率, 最低佣金)
本次新增佣金     = 订单累计应收佣金 − 此订单此前已收佣金
```

实际计算放在 `app/backtest/costs.py`：

```python
def order_commission(cumulative_gross, config):
    return 0.0 if cumulative_gross <= 0 else max(
        cumulative_gross * config.commission_rate, config.min_commission
    )

def incremental_commission(cumulative_gross, already_charged, config, *, fill_gross, model=None):
    resolved = model or config.min_commission_model
    if resolved == "per_fill":
        return commission(fill_gross, config)
    due = order_commission(cumulative_gross, config)
    return max(0.0, due - already_charged)
```

### 1.3 两个模型的取舍

| 模型 | 定义 | 本项目是否默认 |
| --- | --- | --- |
| `per_fill` | 每笔成交各自 `max(金额×费率, 最低佣金)` | 否，保留为可选项 |
| `per_order` | 同一订单多次成交共用一份最低佣金额度 | **是（默认）** |

**为什么选 per_order**：实际券商对同一笔委托的分笔成交通常按一笔委托结算，
本项目模拟的是「一次下单 → 可能分多日部分成交」的场景，用 per_order 更贴近真实结算，
也避免多日小额成交被反复收取最低佣金而人为放大成本、压低策略表现。

配置项 `CostConfig.min_commission_model`（默认 `"per_order"`），可切换为 `"per_fill"` 做对比。
两种模型都要在报告中标注清楚，不声称所有券商完全一致。

### 1.4 订单需要记录累计成交金额

`Order` 新增 `gross_amount: float = 0.0`，每次成交累加，
用于计算「订单累计应收佣金」。`Order.fee` 语义不变，仍是累计已收费用。

### 1.5 买入可负担量必须同步修正

`Broker._max_affordable()` 原来用 `commission(gross)` 判断现金是否够，
在 per_order 模型下会重复计算最低佣金，导致低估可买数量。
改为传入 `order`，用 `incremental_commission(prior_gross + gross, already_charged, ...)`。

### 1.6 税费与佣金分离

最低佣金只作用于**佣金本身**：

```python
fee = incremental_commission(...)          # 佣金
stamp, transfer = taxes(gross, config)     # 印花税、过户费
fee += stamp + transfer
```

印花税、过户费按成交金额独立计算，不参与 `max(..., 最低佣金)`。
滑点单独记录在 `Trade.slippage_cost` 与 `Order.slippage_cost`，不进 `fee`。

## 2. 问题二：清仓时整手与零股未合并

### 2.1 原行为

`sell_quantity(raw, available, lot_size)` 只在「可卖不足一手」时才允许非整手。
持仓 130,400 股、策略算出 130,399.7 时返回 130,300，剩余 100 股；
若 `liquidate` 语义未贯通，还可能出现其它残量。

### 2.2 新规则

```python
def sell_quantity(raw_quantity, available, lot_size, *, liquidate=False):
    if liquidate:
        return int(available)          # 清仓：整手+零股合并成一笔
    want = floor(min(raw, available))
    lots = (want // lot_size) * lot_size
    return lots if lots > 0 else min(want, available)
```

**必须区分「全部清仓」与「部分减仓」，不能只看是否超过 100 份。**

| 意图 | 判定 | 申报数量 |
| --- | --- | --- |
| 全部清仓 | `Order.liquidate == True`（引擎侧 `target_weight <= 1e-9`） | 全部可卖数量，一笔 |
| 部分减仓 | `liquidate == False` | 按整手向下取整 |
| 部分减仓但只剩零股 | `liquidate == False` 且 `available < lot_size` | 整笔卖掉该零股 |

### 2.3 标记如何贯通

1. `engine._orders_from_weights()`：`liquidate = target <= 1e-9`，写入 `Order.liquidate`
2. `broker.execute()`：卖出分支调用 `sell_quantity(..., liquidate=bool(order.liquidate))`
3. 兜底夹紧 `quantity = min(quantity, order.remaining_quantity)` 保持不变
4. T+N 可卖约束不变：仍先取 `portfolio.available(code, trade_date)`

### 2.4 实测场景

| 场景 | 委托 | 成交 | 剩余持仓 |
| --- | ---: | ---: | ---: |
| 持仓 130,400 清仓 | 130,400 | 130,400 | 0 |
| 持仓 537 清仓 | 537 | 537 | 0 |
| 持仓 1,237 清仓 | 1,237 | 1,237 | 0 |
| 持仓 1,237 卖 500 | 500 | 500 | 737 |
| 持仓 537 卖 500 | 500 | 500 | 37 |
| 持仓 99 清仓 | 99 | 99 | 0 |
| 持仓 100 清仓 | 100 | 100 | 0 |

## 3. 问题三：全池 sparse 统计口径不一致

### 3.1 差异来源

| 数字 | 来源 | 计算方式 |
| --- | --- | --- |
| 256 | `validation_stress.evaluation.valid_return_days` | `len(risk_return_series(...)[1])`，即 `usable.dropna()` 后的长度，**已剔除首日和无前值** |
| 269 | `sparse_stress_result.json` 独立复算 | 同一函数的同一输出，但用了**不同的 MA 窗口**（MA250 vs MA60） |

**不是口径冲突，是两次运行用了不同参数**：
验证流程用样本内选出的 MA250，独立复算脚本写死了 MA60。
MA250 换手更低、持仓更少，缺口日更多（190 vs 177），有效日更少（256 vs 269）。

### 3.2 真正的口径问题

即使数字来源正当，报告里同时出现两个数字而没有说明参数差异，属于**表述缺陷**。

另外原 `evaluate_sparse_result()` 只接收三个数，无法校验加总关系：

```python
nan_days = daily_rows - valid_return_days - gap_days_excluded
```

这个 `nan_days` 把「首日无收益」也算成了 NaN，语义混淆。

### 3.3 统一口径

新增 `app/backtest/metrics.return_sample_stats()`，全项目唯一入口：

```text
nav_days == first_day + held_price_gap + prior_day_price_gap
                       + missing_nav + valid_return_days
```

| 字段 | 定义 |
| --- | --- |
| `nav_days` | 每日快照总数 |
| `first_day` | 首日无前值，不产生日收益 |
| `held_price_gap` | 持仓 ETF 缺有效报价，估值不完整 |
| `prior_day_price_gap` | 前一日估值不完整，本日收益不可信 |
| `missing_nav` | 净值缺失或前值为 0 |
| `valid_return_days` | 可用日收益数量 |
| `excluded_days` | `held_price_gap + prior_day_price_gap + missing_nav` |
| `identity_holds` | 加总恒等式是否成立 |
| `definition` | 口径版本标签 `return-sample-stats-v1` |

`evaluate_sparse_result()` 改为接收五个数并强制校验加总，不成立直接判 `failed`。
`runner._run_data_stress()` 与市场环境 OOS 诊断全部改为调用 `return_sample_stats()`。

## 4. 修改文件清单

| 文件 | 修改内容 |
| --- | --- |
| `app/backtest/config.py` | `CostConfig` 新增 `min_commission_model`（per_order / per_fill） |
| `app/backtest/costs.py` | 新增 `order_commission()`、`incremental_commission()`；`sell_quantity()` 支持 `liquidate` |
| `app/backtest/models.py` | `Order` 新增 `gross_amount`、`liquidate` |
| `app/backtest/broker.py` | 佣金改 `incremental_commission`；`_max_affordable` 按订单累计；卖出尊重 `liquidate` |
| `app/backtest/engine.py` | 清仓意图写入 `Order.liquidate` |
| `app/backtest/metrics.py` | 新增 `return_sample_stats()` |
| `app/validation/stress.py` | `evaluate_sparse_result()` 接收五元统计并校验加总 |
| `app/validation/runner.py` | 数据场景与 OOS 诊断统一调用 `return_sample_stats()` |
| `app/validation/report.py` | 报告按新口径展示 |
| `tests/test_validation_fix.py` | 1 项断言适配新口径 |
| `tests/test_validation_fix_3.py` | **新增** 34 项专项测试 |

## 5. 不修改的部分

- `portfolio.py` 账本算术（`cash += gross - fee`）本身正确，未动
- 现金非负检查保留，未删除
- 行情、指标、复权快照、历史回测、历史 validation 一行未动
- 数据库结构无变更，无需迁移
- 策略逻辑未改，只改交易成本与申报数量

## 6. 已知限制

1. per_order 是**本项目的模拟假设**，不代表所有券商结算方式；实际券商可能按分笔成交逐笔计费
2. 未模拟「同一委托跨营业日拆分」的券商侧费用差异
3. 清仓合并申报假设券商接受整手+零股单笔申报，实际交易所对零股申报有更细的规定
4. 涨跌停仍为整日近似
