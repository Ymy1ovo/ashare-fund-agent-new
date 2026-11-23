# 阶段3B-5.4 研究分析验证报告

- 基线 HEAD：`a94325080a449a4a84e40b8a1bc4bbabcb0bab03`
- 执行日期：2026-11-23
- 引擎：3B-5.1 `app/fund/research/engine.py`（未改口径）
- 数据源：正式库 `data/fund_agent.db`

> 本报告全部为**真实运行结果**，不是构造数据。

---

## 1. 净值覆盖与数据质量

| 代码 | 分类 | 行数 | 起始 | 结束 | 最大缺口 | 超阈值缺口 | 连续性 |
| --- | --- | ---: | --- | --- | ---: | ---: | --- |
| `050002` | `ordinary_index` | 5644 | 2003-08-26 | 2026-11-20 | 31 天 | 1 | `cannot_verify` |
| `001052` | `etf_linked` | 2802 | 2015-05-05 | 2026-11-20 | 11 天 | 0 | `cannot_verify` |
| `001938` | `active_equity` | 2678 | 2015-11-03 | 2026-11-20 | 11 天 | 0 | `cannot_verify` |
| `519066` | `active_equity` | 4461 | 2008-07-08 | 2026-11-20 | 11 天 | 0 | `cannot_verify` |
| `000032` | `bond_pure` | 3288 | 2013-04-24 | 2026-11-20 | 11 天 | 0 | `cannot_verify` |
| `000509` | `money_market` | 4676 | 2014-01-15 | 2026-11-22 | 7 天 | 0 | `cannot_verify` |
| `001548` | `etf_linked` | 2764 | 2015-07-16 | 2026-11-20 | 11 天 | 0 | `cannot_verify` |

---

## 2. 收益与风险指标（净值型基金）

### 2.0 口径声明：全部基于 `acc_nav`（累计净值）

本节及后续所有净值型基金的**收益、年化收益、最大回撤、波动率**，
**全部使用 `acc_nav`（累计净值）**，不使用 `unit_nav`。

| 项 | 实际取值 | 依据 |
| --- | --- | --- |
| `return_field` | **`acc_nav`** | `engine.py:124` `compute_nav_indicators(series, field_name="acc_nav")` |
| 收益 | `acc_nav` | `indicators.py` `_window_return(..., field_name=...)` |
| 年化收益 | `acc_nav` | `_annualized(series, field_name=...)` |
| 最大回撤 | `acc_nav` | `_max_drawdown(series, field_name=...)` |
| 波动率 | `acc_nav` | 同上，净值序列差分 |
| `dividend_repair_used` | **`false`** | 未用分红数据修复 |

**为什么用 `acc_nav`**：累计净值含分红再投资，是总回报的合理代理；
`unit_nav`（单位净值）**不含分红**，直接拿它算收益会低估总回报，
因此**不能**当作主要收益口径。

**`unit_nav` 是独立对照输出**，位于 `indicators_unit_nav`，标注为
「unit_nav 口径，不含分红，**不是总回报**，仅供对照」，
不与本节主口径混淆。

引擎原样输出：

```json
"return_field": "acc_nav",
"return_field_note": "acc_nav 是累计净值，含分红再投资，作为总回报代理；
                      unit_nav 是不含分红的单位净值，**不能**直接当总回报",
"dividend_repair_used": false,
"dividend_repair_note": "分红记录不完整（3B-4.4 已核验），**未**用分红数据修复历史收益；
                         收益全部基于 acc_nav 原值"
```

### 2.1 两种口径的实测差异（证明未混用）

同一只基金、同一时间窗，两种口径结果**明显不同**，说明代码确实各走各的：

| 代码 | `acc_nav` 近1年收益 | `unit_nav` 近1年收益 | 差异 |
| --- | --- | --- | --- |
| `050002` | -4.0993% | -8.9623% | 4.8630 个百分点 |

若两者被混为一谈，不会出现这种稳定差异。

### 2.2 指标表（`acc_nav` 口径）

| 代码 | 分类 | 近1年收益 | 最大回撤 | 年化收益 | 波动率（日） | 波动率年化 |
| --- | --- | --- | --- | --- | --- | --- |
| `050002` | `ordinary_index` | -4.0993% | 33.4992% | — | 0.006935 | **否** |
| `001052` | `etf_linked` | -12.5516% | 62.7810% | -2.5595% | 0.233920 | 是 |
| `001938` | `active_equity` | -6.5170% | 29.2096% | 10.2562% | 0.153860 | 是 |
| `519066` | `active_equity` | -8.5714% | 42.2377% | 7.7922% | 0.157856 | 是 |
| `000032` | `bond_pure` | 2.3151% | 4.9652% | 3.8121% | 0.012363 | 是 |
| `001548` | `etf_linked` | -3.3548% | 39.1939% | 3.2862% | 0.178010 | 是 |

### 2.3 为什么 `050002` 年化收益不可计算

```
status: insufficient_data
reason: 首尾区间内存在 1 处超过 15 天的缺口，不跨越缺口计算年化收益
gaps:   [{'from': '2003-08-26', 'to': '2003-09-26', 'days': 31}]
```

**引擎拒绝计算，而不是硬算**。同口径下波动率也不年化：

```
status: ok, annualized: false
annualization_blocked_reason: 存在 1 处超过 15 天的缺口；
                              只输出未年化日波动，不乘任何年化因子
```

---

## 3. 货币基金独立口径

| 项 | 值 |
| --- | --- |
| `is_money_fund` | **True** |
| `uses_unit_nav` | **False** |
| 每万份收益样本 | 4676 天 |
| 累计万份收益 | 3326.033 元/万份 |
| 折算收益率（近似） | 33.26033% |
| 7日年化最新 | 0.902%（2026-11-22） |
| 7日年化区间均值 | 2.616558% |
| 7日年化最小~最大 | 0.869% ~ 6.702% |

### 3.1 口径隔离证据

```json
"nav_based_indicators": {
  "status": "not_applicable",
  "reason": "货币基金不使用 unit_nav / acc_nav，**不得**计算净值型收益、回撤、波动率"
}
"per_10k_yield": {"usable_for_net_value_comparison": false, ...}
```

| 检查 | 结果 |
| --- | --- |
| 货币基金近1年收益 | **未计算**（不是 0） |
| 货币基金最大回撤 | **未计算** |
| 货币基金波动率 | **未计算** |
| 每万份收益是否当作收益率 | **否**，明确标注「不是收益率、不是净值」 |
| 7日年化是否当作已实现收益 | **否**，标注「参考值，不是已实现收益」 |

---

## 4. A/C 份额归并

| 本体 | 份额数 | 代表份额 | 成本对比含份额 |
| --- | ---: | --- | --- |
| `000032` | 2 | `000032` | `000032`, `000033` |
| `001548` | 2 | `001548` | `001548`, `001549` |

| 检查 | 结果 |
| --- | --- |
| A/C 是否被算成两只独立基金 | **否**，按 `fund_id` 去重 |
| 表现比较维度 | `fund_id`（本体） |
| 成本比较维度 | `share_class`（份额） |

---

## 5. 同类分组

| 代码 | 分类 | peer_key | 分组来源 |
| --- | --- | --- | --- |
| `050002` | `ordinary_index` | `ordinary_index|broad|沪深300` | `benchmark` |
| `001052` | `etf_linked` | `etf_linked|broad|中证500` | `benchmark` |
| `001938` | `active_equity` | `active_equity|中证500` | `benchmark` |
| `519066` | `active_equity` | `active_equity|中证800` | `benchmark` |
| `000032` | `bond_pure` | `bond_pure|unknown` | `unknown` |
| `000509` | `money_market` | `money_market` | `unknown` |
| `001548` | `etf_linked` | `etf_linked|broad|上证50` | `benchmark` |

| 检查 | 结果 |
| --- | --- |
| 货币基金是否与净值型混组 | **否**，peer_key 为独立的 `money_market` |
| 不同指数族是否混组 | **否**，沪深300 / 中证500 / 上证50 分开 |
| 分组依据 | benchmark 族（`tracking_index` 全 NULL，走回落） |

---

## 6. 指数与主动基金基准

| 代码 | 分类 | 基准族 | 说明 |
| --- | --- | --- | --- |
| `050002` | `ordinary_index` | `unknown` | `benchmark` |
| `001052` | `etf_linked` | `unknown` | `benchmark` |
| `001938` | `active_equity` | `active_equity|中证500` | `benchmark` |
| `519066` | `active_equity` | `active_equity|中证800` | `benchmark` |
| `000032` | `bond_pure` | `bond_pure|unknown` | `unknown` |
| `000509` | `money_market` | `money_market` | `unknown` |
| `001548` | `etf_linked` | `unknown` | `benchmark` |

> 主动基金的「基准」只用于分组，**不据此计算超额收益**——
> 库内无基准收益序列。

---

## 7. 未计算指标（明确拒绝，不硬算）

| 指标 | 状态 | 原因 |
| --- | --- | --- |
| Sharpe | `not_available` | 无风险利率无可靠数据源，**不把 0 冒充真实利率** |
| Sortino | `not_available` | 同上 |
| 超额收益 | 不计算 | 无基准收益序列 |
| 信息比率 | 不计算 | 无基准序列 |
| Beta | 不计算 | 无基准序列 |
| 风格稳定性 | 不计算 | 无持仓数据 |

原始输出：

```json
"sharpe": {"value": null, "status": "not_available",
           "reason": "无风险利率无可靠数据源，不输出常规 Sharpe",
           "note": "避免把 0 冒充真实无风险利率"}
"not_computed": {"excess_return": "无基准收益序列，禁止计算超额收益", ...}
```

---

## 8. 不同类型是否使用正确口径

| 类型 | 主要收益口径 | 风险口径 | 分组口径 | 结论 |
| --- | --- | --- | --- | --- |
| 普通指数 | **`acc_nav` 累计净值** | `acc_nav` 回撤/波动 | benchmark 族 | ✅ |
| ETF 联接 | **`acc_nav` 累计净值** | `acc_nav` 回撤/波动 | benchmark 族 | ✅ |
| 主动权益 | **`acc_nav` 累计净值** | `acc_nav` 回撤/波动 | 类型 + 基准 | ✅ |
| 混合型 | **`acc_nav` 累计净值** | `acc_nav` 回撤/波动 | 类型 + 基准 | ✅ |
| 债券 | **`acc_nav` 累计净值** | `acc_nav` 回撤/波动 | 类型（无基准） | ✅ |
| 货币 | **每万份收益 / 7日年化**（独立口径） | **不适用** | 独立 `money_market` | ✅ |

无一类型被套用错误口径。

### 8.1 口径边界（三条硬约束）

| # | 约束 | 实际状态 |
| ---: | --- | --- |
| 1 | 净值型主口径必须是 `acc_nav`，不得写成 `unit_nav` | ✅ `return_field = "acc_nav"` |
| 2 | `unit_nav` 只能作独立对照，不得与总回报混淆 | ✅ 单独在 `indicators_unit_nav`，带「不是总回报」标注 |
| 3 | 累计净值用原始数据，不用不完整分红修复 | ✅ `dividend_repair_used = false` |

### 8.2 货币基金口径（独立，不参与净值口径）

| 项 | 口径 |
| --- | --- |
| 收益 | `per_10k_yield`（每万份收益，元/万份/日） |
| 参考收益 | `seven_day_annual`（7 日年化，参考值） |
| `unit_nav` / `acc_nav` | **not_applicable**，两种净值口径都不适用 |
| 与净值型可比性 | **不可比**，`usable_for_net_value_comparison = false` |

### 8.3 本节修正说明

本报告初版第 8 节曾把净值型收益口径误写为「单位净值」，
与 `engine.py` / `indicators.py` 实际代码及 JSON 不一致。

**已按实际代码修正为累计净值口径**：
- 计算代码**未改动任何一行**；
- 历史结果数值**未改动任何一个**；
- 仅修正文档表述，使文档与代码/JSON 一致。


---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
