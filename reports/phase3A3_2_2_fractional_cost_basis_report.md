# 阶段3A.3.2.2 零碎份额成本基准修复

- 生成时间：2026-11-13
- 文件：`app/backtest/portfolio.py::apply_corporate_action()`
- 性质：**账本修复**，不影响任何行情数据

## 1. 上一阶段的缺陷

3A.3.2.1 的份额调整逻辑：

```python
ratio = new_quantity / old_quantity          # ← 被整数取整污染
for lot, quantity in zip(lots, floors):
    lot.price = lot.price / ratio            # ← 用污染后的比例折成本
```

**问题**：`new_quantity = floor(old × 官方比例)`，
因此 `new_quantity / old_quantity` **不是**官方比例，而是「取整后的实际比例」。

### 1.1 具体错在哪

原持仓 100 份、总成本 10,000 元、官方比例 1.145：

| 概念 | 值 |
| --- | ---: |
| 官方比例 | 1.145 |
| 理论份额 | 114.5 |
| 实际份额 | 114 |
| 零碎份额 | 0.5 |
| 上一阶段实际用的比例 | 114 / 100 = **1.14** |

用 1.14 折成本 → 全部 10,000 元成本被保留在 114 份上，
**零碎 0.5 份对应的成本没有转出**，剩余持仓成本偏高。

实测（修复前）：

```
qty 100->114  成本 10000.00 -> 10000.00（应 9956.33）
```

### 1.2 两个后果

| 后果 | 说明 |
| --- | --- |
| 剩余持仓成本偏高 | 卖出时已实现亏损被低估 |
| 零碎份额补偿的盈亏漏记 | 现金补偿进账了，但没有对应成本转出，盈亏对不上 |

## 2. 修复设计

### 2.1 用官方比例

```python
def apply_corporate_action(
    self, code, new_quantity, cash_delta=0.0, *,
    official_ratio: float | None = None,      # ← 官方比例，不是推算比例
    compensation_price: float | None = None,
    fractional_policy: str = "truncate",
    ...
):
```

`official_ratio` 来自事件的 `share_ratio` 字段（官方公告值）。
若未提供，退化为 `new_quantity / old_quantity`（等价于「没有零碎份额」）。

### 2.2 校验目标份额与官方比例一致

```python
raw_total = old_quantity * ratio
expected_new = int(raw_total // 1)          # 或按 round_up 进位
if abs(new_quantity - expected_new) > 0:
    raise PortfolioError("目标份额与官方比例推算不一致")
```

防止引擎与账本对「该变成多少份」有分歧。

### 2.3 零碎份额的成本转出：**组合层面**，不是逐批次

```python
cost_before_total = sum(lot.quantity * lot.cost_basis for lot in lots)
disposed_total = cost_before_total * (fractional_shares / raw_total)

for lot, allocated in zip(lots, floors):
    share = lot_cost_before / cost_before_total
    lot_remaining = lot_cost_before - disposed_total * share
    per_share_after = lot_remaining / allocated
    lot.price = lot.price * (per_share_after / lot.cost_basis)
```

**为什么不用逐批次的余数**：
最大余数法把整数份额分配给哪个批次，只是**账本拆分方式**，
不代表该批次多处置或少处置了份额。
用逐批次余数会导致「哪个批次分配到了整数份额，哪个批次的零碎就被吃掉」。

实测对比：

| 方法 | 1000 份 0.36555 合并，转出成本 |
| --- | ---: |
| 逐批次余数（错误） | 27.49 元 |
| 组合层面（正确） | **18.06 元** |
| 理论值 `12002 × (0.55/365.55)` | **18.06 元** |

### 2.4 三种零碎处置口径

公告必须能判断口径，不能统一套用估值：

| 口径 | 常量 | 含义 | 成本处理 |
| --- | --- | --- | --- |
| 现金补偿 | `cash_compensation` | 按公告价折现金 | 转出对应成本，差额计已实现盈亏 |
| 舍去 | `truncate` | 尾差计入基金财产 | 转出对应成本，全额计损失 |
| 进位 | `round_up` | 小数点后份额进位补足 | **不转出**，成本单价被动稀释 |

`round_up` 的新增份额由基金管理人补足，不带来成本，
因此成本总额不变、单价被稀释。

### 2.5 逐条判定口径（不是统一估值）

`scripts/set_fractional_policy.py` 从公告正文判定：

| 判据 | 口径 | 条数 |
| --- | --- | ---: |
| 「上进位」/「进位为 1 份」 | `round_up` | **5** |
| 「尾差计入基金」/「舍去」 | `truncate` | 9 |
| 「现金补偿」 | `cash_compensation` | **0** |
| 公告未明说 | 默认 `truncate` | 21 |
| 无公告正文（unverified） | 默认 `truncate` | 10 |

**实测结果**：本库 166 条事件中，
**没有一条公告规定「按现金补偿」**——全部是「舍去」或「进位」。
这意味着 3A.3.2.1 中「按收盘价折现金补偿」的处理方式
**根本不符合任何一条真实公告**。

5 条 `round_up`：

| 代码 | 类型 | 除息日 | 比例 |
| --- | --- | --- | ---: |
| `510500` | split | 2022-08-26 | 1.1454 |
| `512100` | reverse_split | 2022-09-02 | 0.3656 |
| `511030` | reverse_split | 2025-03-18 | 0.1 |
| `159934` | reverse_split | 2025-09-19 | 0.9481 |
| `518800` | reverse_split | 2026-04-14 | 0.9423 |

## 3. 修复前后对照

### 3.1 非整数拆分（1:1.145，100 份）

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 剩余份额 | 114 | 114 |
| 剩余成本 | 10,000.00 | **9,956.33** |
| 转出成本 | 0 | **43.67** |
| 零碎现金补偿 | 50.00 | 50.00 |
| 已实现盈亏 | 0 | **+6.33** |

### 3.2 非整数合并（1:0.36555，1000 份，多批次）

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 剩余份额 | 365 | 365 |
| 剩余成本 | 12,002.00 | **11,983.94** |
| 转出成本 | 0 | **18.06** |
| 已实现盈亏 | 0 | **-12.56** |

### 3.3 整数比例

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 1:2 拆分（1000 份） | 成本 10,000 不变 | 成本 10,000 不变，转出 0 |
| 1:0.1 合并（1000 份） | 成本 10,000 不变 | 成本 10,000 不变，转出 0 |

整数比例无零碎，行为不变。

### 3.4 进位口径（round_up）

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 份额 | 114（舍去） | **115（进位）** |
| 成本 | 10,000.00 | **10,000.00**（不转出） |
| 已实现盈亏 | 0 | **0** |

## 4. 账本留痕

`apply_corporate_action()` 现在返回完整 dict：

```python
{
    "action_id": 114,
    "action_type": "reverse_split",
    "code": "512100",
    "fractional_policy": "round_up",
    "shares_before": 1000,
    "shares_after": 365,
    "official_ratio": 0.36555,
    "ratio_source": "official",          # 或 "implied"
    "fractional_shares": 0.55,
    "compensation_cash": 0.0,
    "disposed_cost_basis": 18.06,
    "realized_pnl": -18.06,
    "cost_basis_before": 12002.0,
    "cost_basis_after": 11983.94,
    "compensation_price": None,
}
```

写入位置：

| 位置 | 用途 |
| --- | --- |
| `engine.corporate_action_ledger` | 内存留痕，供分析 |
| `corporate_action_applications`（新列） | 持久化：`fractional_shares` / `disposed_cost_basis` / `realized_pnl` / `official_ratio` |
| `portfolio.corporate_action_realized` | 单独列表，与 `closed_trade_pnls` 分开 |

**公司行为不是成交**：
- 不进 `trade_count`
- 不进 `closed_trade_pnls`（成交平仓盈亏）
- 不进 `closed_holding_days`

## 5. 满足的 7 条要求

| # | 要求 | 实现 | 验证测试 |
| ---: | --- | --- | --- |
| 1 | 用官方比例而非推算比例 | `official_ratio` 参数 | `test_fractional_split_disposes_cost_and_records_pnl` |
| 2 | 零碎成本必须转出 | 组合层面按占比转出 | `test_multi_lot_fractional_disposal_uses_portfolio_level_cost` |
| 3 | 补偿与转出成本比较算盈亏 | `realized_pnl = cash - disposed` | 同上 |
| 4 | 剩余成本与剩余份额匹配 | `cost_after = cost_before - disposed` | `test_fractional_split_...` |
| 5 | 多批次统一规则 | 组合层面 + 按成本占比分摊 | `test_multi_lot_...` |
| 6 | 整数份额分配不改变经济权益 | 成本转出与批次分配解耦 | `test_multi_lot_...`、`test_consecutive_actions_do_not_double_charge_cost` |
| 7 | 现金补偿与盈亏可追溯 | ledger 返回 + DB 新列 | `test_truncate_policy_records_loss_not_cash` |
| 附 | 按公告实际规则，不套统一估值 | `fractional_policy` 三值 + 逐条判定 | `test_round_up_policy_adds_share_without_cost` |

## 6. 边界情况

| 场景 | 行为 |
| --- | --- |
| 无持仓 | 成本 0、盈亏 0、现金不变 |
| 持仓被全部清零 | 全部成本转为处置成本 |
| 目标份额与官方比例不符 | 抛 `PortfolioError` |
| 连续两次事件 | 成本不重复计算（1:2 拆分 + 1:0.5 合并后回到原成本） |
| `round_up` 且零碎 | 不转出成本，`fractional_shares` 记为 0 |

## 7. 对回测结果的影响

样本外 MA250：

| 指标 | 3A.3.2.1 | 3A.3.2.2 | 差 |
| --- | ---: | ---: | ---: |
| 总收益 | 20.1070% | **20.1186%** | +0.0116 pp |
| Sharpe | 0.7208 | **0.7211** | +0.0003 |
| 最大回撤 | −18.2937% | **−18.2853%** | 收窄 0.0084 pp |
| 交易次数 | 417 | **419** | +2 |
| 总成本 | 9,482.76 | **9,480.91** | −1.84 |

**影响极小**（收益 +0.01 pp），原因是：
- 回测区间内只有 5 条 `round_up` 事件
- 其余都是 `truncate`，零碎份额本来就「不产生现金」
- 3A.3.2.1 的「按收盘价现金补偿」实际上给了并不存在的现金，
  但金额极小（全库零碎现金合计 < 200 元）

**这不是「策略变好」，而是账本不再虚构现金。**

## 8. 局限

| # | 局限 | 影响 |
| ---: | --- | --- |
| 1 | 21 条公告未明说零碎处置口径 | 按默认 `truncate`，可能与实际不符 |
| 2 | 10 条 unverified 事件无公告 | 默认 `truncate` |
| 3 | `compensation_price` 未从公告读取 | 本库无 `cash_compensation` 事件，暂不需要 |
| 4 | 未区分「舍去」与「尾差入基金」的细微差别 | 两者在当前数据里等价 |
