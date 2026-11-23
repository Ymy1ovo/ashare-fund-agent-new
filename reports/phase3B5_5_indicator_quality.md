# 阶段3B-5.5 指标级可信度评估

- 执行日期：2026-11-23
- 数据源：正式库 `data/fund_agent.db`（只读）
- 评级实现：`app/fund/research/quality.py`

> **A/B/C/D 描述的是证据强度，不是基金好坏，也不代表收益高低。**

---

## 1. 13 项指标的真实等级分布

| 指标 | `050002` | `001052` | `001938` | `000032` | `000509` | `001548` | `001549` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ret_1m` | A | A | A | A | not_applicable | A | A |
| `ret_3m` | A | A | A | A | not_applicable | A | A |
| `ret_6m` | A | A | A | A | not_applicable | A | A |
| `ret_12m` | A | A | A | A | not_applicable | A | A |
| `ret_36m` | A | A | A | A | not_applicable | A | A |
| `annualized_return` | D | A | A | A | not_applicable | A | A |
| `max_drawdown` | B | A | A | A | not_applicable | A | A |
| `daily_volatility` | A | A | A | A | not_applicable | A | A |
| `annualized_volatility` | D | A | A | A | not_applicable | A | A |
| `sharpe` | D | D | D | D | not_applicable | D | D |
| `excess_return` | D | D | D | D | not_applicable | D | D |
| `peer_comparison` | D | D | C | C | C | D | D |
| `share_cost_comparison` | not_applicable | not_applicable | not_applicable | D | not_applicable | D | D |

---

## 2. 每项指标的评级规则

### 2.1 区间收益（近1月/3月/6月/1年/3年）

| 条件 | 等级 |
| --- | --- |
| 窗口端点精确命中 + 窗口内无超阈值缺口 | **A** |
| 端点未命中 / 窗口内有缺口 / 历史不足 | **D**（`insufficient_data`） |

实现要点：

- 起点**必须精确等于** `end_date - N 天`，不向前后找替代值；
- 窗口内若有超阈值缺口，直接 `insufficient_data`，不跨越；
- 缺失日**不当 0 收益**，不插值；
- `evidence` 里写明起止日期与两端数值，可复核。

### 2.2 年化收益

| 条件 | 等级 |
| --- | --- |
| 样本 ≥ 2 且全区间无超阈值缺口 | **A** |
| 有缺口 | **D** |

`050002` 实测：

```
"status": "insufficient_data"
"reason": "首尾区间内存在 1 处超过 15 天的缺口，不跨越缺口计算年化收益"
```

### 2.3 最大回撤

| 条件 | 等级 | 说明 |
| --- | --- | --- |
| 全区间连续、`degraded=false`、`complete_interval=true` | **A** | 覆盖完整 |
| 有缺口或空值 → 分段可观测 | **B** | `degraded=true`，**可能低估** |
| 无连续可观测段 | **D** | 不可算 |

关键：分段回撤**绝不**包装成全区间完整回撤。

```json
"degraded": true,
"complete_interval": false,
"limitation": "不是全区间完整最大回撤，只是可观测连续段内的最大值，可能被低估"
```

### 2.4 日波动率 / 年化波动率

注意字段语义陷阱：`volatility.value` **可能是年化值**。
日波动必须取 `daily_vol`，否则会把年化值当日波动展示。

| 指标 | 取哪个字段 | 等级条件 |
| --- | --- | --- |
| 日波动率 | **`daily_vol`** | 能算即 A |
| 年化波动率 | `value`（仅在 `annualized=true` 时） | `annualized=false` → **D（blocked）** |

`050002` 实测：

```
"daily_vol": 0.00693535, "annualized": false
"annualization_blocked_reason": "存在 1 处超过 15 天的缺口；
                              只输出未年化日波动，不乘任何年化因子"
```

→ 日波动 **A**（0.006935），年化波动 **D**（不给值）。

### 2.5 Sharpe / Sortino

| 条件 | 等级 |
| --- | --- |
| 有可靠无风险利率序列 | B |
| 无 | **D**（`not_available`，`value=null`） |

本项目**没有**可靠无风险利率数据源，因此全部为 D。

```json
"sharpe": {"value": null, "status": "not_available",
           "reason": "无风险利率无可靠数据源，不输出常规 Sharpe",
           "note": "避免把 0 冒充真实无风险利率"}
```

### 2.6 超额收益 / 信息比率 / Beta

| 条件 | 等级 |
| --- | --- |
| 有基准收益序列 | B |
| 无（只有基准描述文本） | **D**（`not_computed`） |

库内 `fund_master.benchmark` 只有文字描述，**没有基准净值序列**，
因此全部为 D。

### 2.7 同类比较

| 条件 | 等级 | status |
| --- | --- | --- |
| 组键 unknown / 无跟踪指数 | **D** | `no_verifiable_group` |
| 本体数 < 2 | **D** | `insufficient_peer_sample` |
| 分组来源 unknown 或置信度 none | **C** | `weak_grouping` |
| 本体数 2~4 | **C** | `small_sample` |
| 本体数 ≥ 5 且分组可靠 | **B** | `usable` |

**不存在 A**：同类比较永远受「净值连续性 cannot_verify」限制。

### 2.8 A/C 份额成本比较

| 条件 | 等级 | status |
| --- | --- | --- |
| 只有 1 个份额 | `not_applicable` | `single_share` |
| 费率字段不完整（缺申购/赎回阶梯） | **D** | `insufficient_fee_evidence` |
| 字段齐全，但持有期口径 unknown、支付宝费率不可验证 | **C** | `partial_evidence` |

**不存在 A/B**，也**永远不会**给出 A/C 优劣结论。

---

## 3. 实测：每只样本的具体拖累项

### `050002` 普通指数基金

- 基金级：**B**
- 可算 7 / 不适用 1 / 算不出 5
- **算不出**：`annualized_return`, `annualized_volatility`, `sharpe`, `excess_return`, `peer_comparison`
- **类型不适用**：`share_cost_comparison`

### `001052` ETF联接基金

- 基金级：**B**
- 可算 9 / 不适用 1 / 算不出 3
- **算不出**：`sharpe`, `excess_return`, `peer_comparison`
- **类型不适用**：`share_cost_comparison`

### `001938` 主动权益基金

- 基金级：**B**
- 可算 10 / 不适用 1 / 算不出 2
- **算不出**：`sharpe`, `excess_return`
- **类型不适用**：`share_cost_comparison`

### `000032` 债券基金

- 基金级：**B**
- 可算 10 / 不适用 0 / 算不出 3
- **算不出**：`sharpe`, `excess_return`, `share_cost_comparison`

### `000509` 货币基金

- 基金级：**B**
- 可算 1 / 不适用 12 / 算不出 0
- **类型不适用**：`ret_1m`, `ret_3m`, `ret_6m`, `ret_12m`, `ret_36m`, `annualized_return`, `max_drawdown`, `daily_volatility`, `annualized_volatility`, `sharpe`, `excess_return`, `share_cost_comparison`

### `001548` ETF联接 A/C 组（A 类）

- 基金级：**B**
- 可算 9 / 不适用 0 / 算不出 4
- **算不出**：`sharpe`, `excess_return`, `peer_comparison`, `share_cost_comparison`

### `001549` ETF联接 A/C 组（C 类）

- 基金级：**B**
- 可算 9 / 不适用 0 / 算不出 4
- **算不出**：`sharpe`, `excess_return`, `peer_comparison`, `share_cost_comparison`

---

## 4. 货币基金：全部净值型指标 not_applicable

`000509` 的 13 项里 12 项 `not_applicable`，唯一有值的是同类比较（C）。

这不是「数据差」，是**产品类型不同**：

| 项 | 状态 |
| --- | --- |
| `ret_1m` ~ `ret_36m` | `not_applicable` |
| `annualized_return` | `not_applicable` |
| `max_drawdown` | `not_applicable` |
| `daily_volatility` / `annualized_volatility` | `not_applicable` |
| `sharpe` / `excess_return` | `not_applicable` |
| `peer_comparison` | C（`money_market` 组 2 个本体） |
| `share_cost_comparison` | `not_applicable`（单一份额） |

货币基金真正可用的是：

| 指标 | 值 |
| --- | --- |
| 每万份收益样本 | 4676 天 |
| 累计万份收益 | 3326.033 元/万份 |
| 折算收益率（近似） | 33.26033% |
| 7日年化最新 | 0.902%（2026-11-22） |
| 7日年化区间 | 0.869% ~ 6.702% |

任一项都**不得**与净值型收益混算。

---

## 5. 边界声明

| 项 | 值 |
| --- | --- |
| 修改计算逻辑 | **否** |
| 填充虚假数值 | **否**（全部 `null`） |
| 排名 / 推荐 / 信号 | **否** |
