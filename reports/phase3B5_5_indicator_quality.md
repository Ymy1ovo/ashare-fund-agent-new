# 阶段3B-5.5 指标级可信度评估（3B-5.5.1 修正版）

- 执行日期：2026-11-23
- 修正轮：3B-5.5.1
- 数据源：正式库 `data/fund_agent.db`（只读）
- 评级实现：`app/fund/research/quality.py`

> **A/B/C/D 描述的是证据强度，不是基金好坏，也不代表收益高低。**

---

## 0. 本轮修正：年化收益证据日期

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| 年化收益证据 | `起始 None，结束 None` | **真实计算区间**（取自净值序列首尾） |
| 日期来源 | 只读节点 `start_date/end_date`（`_annualized()` 不返回） | 节点优先，缺失时用质量报告 `date_min/date_max` 补充 |
| `status=ok` 但 `value=None` | 仍给 A | **降为 D `invalid_result`** |
| 无任何可验证日期 | 仍给 A（证据含 None） | **降为 D `insufficient_evidence`**，不编造日期 |

**为什么可以用质量报告日期**：`_annualized()` 取的是
`series.points[0].nav_date` 与 `series.points[-1].nav_date`，
而 `QualityReport.date_min/date_max` 正是这两个值
（`data_access.load_nav_series` 里 `q.date_min = points[0].nav_date`）。
所以这是**等价替换**，不是编造。

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
| `peer_comparison` | D | D | C | D | C | D | D |
| `share_cost_comparison` | not_applicable | not_applicable | not_applicable | D | not_applicable | D | D |

---

## 2. 年化收益证据（本轮重点）

| 代码 | 等级 | 状态 | 值 | 证据 |
| --- | --- | --- | --- | --- |
| `050002` | **D** | `insufficient_data` | — | 区间内存在超过阈值的缺口或样本不足 |
| `001052` | **A** | `ok` | -2.5595% | 成立以来年化 -0.025595，按实际自然日间隔复合年化；计算区间 2015-05-05 → 2026-11-20，跨度 4217 天（计算区间取自净值序列首尾，与质量报告一 |
| `001938` | **A** | `ok` | 10.2562% | 成立以来年化 0.102562，按实际自然日间隔复合年化；计算区间 2015-11-03 → 2026-11-20，跨度 4035 天（计算区间取自净值序列首尾，与质量报告一致 |
| `000032` | **A** | `ok` | 3.8121% | 成立以来年化 0.038121，按实际自然日间隔复合年化；计算区间 2013-04-24 → 2026-11-20，跨度 4958 天（计算区间取自净值序列首尾，与质量报告一致 |
| `000509` | **not_applicable** | `not_applicable` | — | 货币基金不使用净值口径，年化收益不适用 |
| `001548` | **A** | `ok` | 3.2862% | 成立以来年化 0.032862，按实际自然日间隔复合年化；计算区间 2015-07-16 → 2026-11-20，跨度 4145 天（计算区间取自净值序列首尾，与质量报告一致 |
| `001549` | **A** | `ok` | 3.2862% | 成立以来年化 0.032862，按实际自然日间隔复合年化；计算区间 2015-07-16 → 2026-11-20，跨度 4145 天（计算区间取自净值序列首尾，与质量报告一致 |

**验证要点**：

| 检查 | 结果 |
| --- | --- |
| 等级为 A 的年化证据是否含真实日期 | **是**（起止日期均来自净值序列首尾） |
| 是否出现 `起始 None` | **否** |
| 是否编造日期 | **否**（补充日期 == 质量报告 date_min/date_max） |
| 缺口阻断是否仍生效 | **是**（`050002` 恒 D） |

`050002` 实测：

```
"status": "insufficient_data"
"reason": "首尾区间内存在 1 处超过 15 天的缺口，不跨越缺口计算年化收益"
→ 等级 D，value=null
```

`001052` 实测（修复前证据是 `起始 None，结束 None`）：

```
"evidence": "成立以来年化 -0.025595，按实际自然日间隔复合年化；
             计算区间 2015-05-05 → 2026-11-20，跨度 4217 天
             （计算区间取自净值序列首尾，与质量报告一致）"
```

---

## 3. 每项指标的评级规则

### 3.1 区间收益

| 条件 | 等级 |
| --- | --- |
| 窗口端点精确命中 + 窗口内无超阈值缺口 | **A** |
| 端点未命中 / 窗口内有缺口 / 历史不足 | **D** `insufficient_data` |

不向前后找替代值、不插值、缺失日不当 0 收益。

### 3.2 年化收益

| 条件 | 等级 |
| --- | --- |
| 全区间无缺口 + 有真实起止日期 | **A** |
| 有缺口 | **D** `insufficient_data` |
| `status=ok` 但 `value=None` | **D** `invalid_result` |
| 无任何可验证日期 | **D** `insufficient_evidence` |

### 3.3 最大回撤

| 条件 | 等级 | 说明 |
| --- | --- | --- |
| `degraded=false` 且 `complete_interval=true` | **A** | 覆盖完整 |
| 有缺口或空值 → 分段 | **B** | **可能低估**，不冒充全区间回撤 |
| 无连续段 | **D** | — |

### 3.4 日波动率 / 年化波动率

`volatility.value` **可能是年化值**，日波动必须取 `daily_vol`。

| 指标 | 取字段 | 等级 |
| --- | --- | --- |
| 日波动率 | `daily_vol` | 能算即 **A** |
| 年化波动率 | `value`（仅 `annualized=true`） | `annualized=false` → **D** `blocked` |

### 3.5 Sharpe / Sortino

恒 **D** `not_available`，`value=null`。**不把 0 冒充无风险利率。**

### 3.6 超额收益 / 信息比率 / Beta

恒 **D** `not_computed`。库内只有基准文字，**没有基准净值序列**。

### 3.7 同类比较（本轮修正）

| 条件 | 等级 | status |
| --- | --- | --- |
| 货币基金 `money_market` | C（<5） / B（≥5） | `small_sample` / `usable` |
| `verifiable_group=False` | **D** | `no_verifiable_group` |
| 组键基准族 unknown | **D** | `no_verifiable_group` |
| 本体 1 个 | **D** | `insufficient_peer_sample` |
| 本体 2~4 个 | **C** | `small_sample` |
| 本体 ≥5 个且分组可靠 | **B** | `usable` |

**永远不到 A**。

### 3.8 A/C 份额成本比较

| 条件 | 等级 | status |
| --- | --- | --- |
| 只有 1 个份额 | `not_applicable` | `single_share` |
| 费率字段不完整 | **D** | `insufficient_fee_evidence` |
| 字段齐全但仍不可验证 | **C** | `partial_evidence` |

**永远不给 A/C 优劣结论。**

---

## 4. 实测：每只样本的拖累项

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
- 可算 9 / 不适用 0 / 算不出 4
- **算不出**：`sharpe`, `excess_return`, `peer_comparison`, `share_cost_comparison`

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

## 5. 货币基金：净值型指标全部 not_applicable

`000509` 的 13 项里 12 项 `not_applicable`，唯一有值的是同类比较。

| 指标 | 值 |
| --- | --- |
| 每万份收益样本 | 4676 天 |
| 累计万份收益 | 3326.033 元/万份 |
| 折算收益率（近似） | 33.26033% |
| 7日年化最新 | 0.902%（2026-11-22） |
| 7日年化区间 | 0.869% ~ 6.702% |

任一项都**不得**与净值型收益混算。

---

## 6. 边界声明

| 项 | 值 |
| --- | --- |
| 修改计算逻辑 | **否** |
| 修改窗口/缺口规则 | **否** |
| 填充虚假数值 | **否**（全部 `null`） |
| 排名 / 推荐 / 信号 | **否** |
