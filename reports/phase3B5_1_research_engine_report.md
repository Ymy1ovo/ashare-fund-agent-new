# 阶段3B-5.1 支付宝场外基金研究性分析引擎 V1.0

- 基线 HEAD：`28e2448cfa97f62ab813dd093119d6b1d256f2e6`
- 执行日期：2026-11-20
- 引擎代码：`app/fund/research/`
- CLI：`python -m app.fund.research`
- 专项测试：`tests/test_3b5_1_fund_research.py`

> **本阶段交付可运行的只读分析引擎。**
> 不写库、不采集、不排名、不出信号、不开回测门禁。

---

## 0. 结论先行

| 项 | 结果 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
| 研究池 | 12 份额 / 9 本体 |
| 同类组 | 8 个 |
| 真实排名 | **未生成** |
| 买卖信号 | **未生成** |

> 研究性描述分析可用；正式回测与真实排名仍不具备条件（净值连续性 cannot_verify、无风险利率与基准序列缺失、费率无历史生效日、支付宝状态 unknown）

---

## 1. 实际完成的功能

| 层 | 模块 | 内容 |
| --- | --- | --- |
| 数据读取 | `data_access.py` | 研究池加载、净值序列、货币序列、费率、质量审计 |
| 质量审计 | `data_access.py` | 重复日期、乱序、空值、非正净值、超阈值缺口 |
| 指标计算 | `indicators.py` | 窗口收益、年化、回撤、波动率、下行波动、滚动稳定性 |
| 分类 | `classification.py` | 九类产品、LOF 独立结构、宽基/行业、同类组键 |
| 费用比较 | `fees.py` | 年化费率边界、阶梯费率、份额成本对比 |
| 同类分析 | `engine.py` | 按 peer_group 分组描述性对照（不排名） |
| 报告生成 | `engine.py` | 单只基金完整研究报告 |
| CLI | `__main__.py` | `--list` / `--code` / `--all` |

---

## 2. 未完成的功能及原因

| 功能 | 状态 | 原因 |
| --- | --- | --- |
| 超额收益 | **不可算** | 无基准收益序列；`benchmark` 只是自由文本 |
| 与基准偏离 | **不可算** | 同上 |
| 信息比率 / Beta | **不可算** | 同上 |
| 风格稳定性 | **不可算** | 无持仓数据 |
| 常规 Sharpe | **不输出** | 无风险利率无可靠数据源 |
| 常规 Sortino | **不输出** | 同上 |
| 完整历史交易成本模拟 | **不可算** | 79 条费率无生效日、阶梯不完整、持有期口径未确认 |
| 支付宝实际费率 | **unknown** | 无公开合法数据源 |
| 支付宝可购买状态 | **unknown** | 同上 |
| 正式综合排名 | **不生成** | 样本量小、连续性 cannot_verify、缺基准与无风险利率 |

---

## 3. 指标公式与口径

### 3.1 窗口收益

```
ret(window) = acc_nav_end / acc_nav_start - 1
```

| 窗口 | 自然日 |
| --- | ---: |
| ret_1m | 30 |
| ret_3m | 91 |
| ret_6m | 182 |
| ret_12m | 365 |
| ret_36m | 1095 |

**硬约束**：

- 端点必须**精确命中**某条净值；命不中就 `insufficient_data`，**不向前后找近似值**。
- 区间内存在超过 15 天的缺口时拒绝计算，**不跨越缺口**。
- 不使用「过去 20/60/120 条记录」冒充自然月。

### 3.2 年化收益

```
annualized = (acc_nav_end / acc_nav_start) ^ (365.25 / span_days) - 1
```

按**实际自然日间隔**，跨度不足 1 年返回 `insufficient_data`。

### 3.3 波动率年化

**不无条件使用 252。** 年化需同时满足：

1. 1 天间隔占比 ≥ 60%（证明逐交易日公布）
2. 无超过 15 天的缺口
3. 跨度 ≥ 365 天

满足后用**观测频率**年化（有效点数 / 年数），不硬套 252：

```
annualized_vol = daily_std × sqrt(observed_per_year)
```

不满足时只输出**未年化日波动率**，并附 `annualization_blocked_reason`。

### 3.4 最大回撤与修复时间

```
drawdown_t = 1 - NAV_t / max(NAV_0..t)
max_drawdown = max(drawdown_t)
```

**修复时间** = 谷底到再次达到前高的**自然日**数。
尚未恢复标记 `ongoing`，**不当作已修复**。

### 3.5 风险调整指标

| 指标 | 公式 | 状态 |
| --- | --- | --- |
| sharpe | (年化收益 − 无风险利率) / 年化波动 | `not_available`（无风险利率缺失） |
| zero_hurdle_sharpe | (年化收益 − 0) / 年化波动 | 可算时输出，**明确标注不是常规 Sharpe** |
| sortino | (年化收益 − 无风险利率) / 下行波动 | `not_available` |
| calmar | 年化收益 / 最大回撤 | 可算时输出 |

### 3.6 货币基金口径

| 指标 | 定义 |
| --- | --- |
| 累计万份收益 | Σ 每日每万份收益（元/万份） |
| 折算累计收益率 | 累计金额 / 10000（近似，未考虑复利） |
| 7 日年化 | 原值统计：最新、均值、最小、最大 |

**货币基金不计算**：净值型收益、最大回撤、波动率、Sharpe。

---

## 4. 数据准入与缺失情况

### 4.1 字段级准入等级

| 字段 | 等级 | 说明 |
| --- | --- | --- |
| `unit_nav` | A / B | 单序列描述性；有重复日期或空值降 B |
| `acc_nav` | A / B | 同上；含分红再投资，作总回报代理 |
| `per_10k_yield` | A | 货币基金专用 |
| `seven_day_annual` | A | 货币基金专用参考值 |
| 年化费率（有生效日） | B | 仅生效日之后可用 |
| 年化费率（无生效日） | C | 仅当前情景 |
| 申购/赎回阶梯 | C | 不完整、持有期口径未确认 |
| 分红 | **C** | 完整性未验证，**禁止修正历史收益** |
| 基金规模 | **C** | 平台观测日期，**禁止作时点因子** |
| 经理历史 | B | 部分快照，不可回填 |
| 清盘事件 | B | 非全量名录 |
| 支付宝可购买 | **unknown** | 不得推断 true/false |

### 4.2 本轮样本缺失统计

| 缺失项 | 处理 |
| --- | --- |
| 基准收益序列 | 超额收益类指标全部 `not_computed` |
| 无风险利率 | Sharpe/Sortino `not_available` |
| 持仓数据 | 风格稳定性 `not_computed` |
| 久期/信用/转债字段 | 债券同类组统一标 `unknown` |
| 支付宝费率与状态 | 全部 `unknown` |

---

## 5. 样本运行统计

### 5.1 研究池

| 项 | 数量 |
| --- | ---: |
| 份额 | 12 |
| 基金本体 | 9 |
| 场内 ETF 混入 | **否** |

| 产品分类 | 份额数 |
| --- | ---: |
| `active_equity` | 1 |
| `bond_pure` | 2 |
| `etf_linked` | 4 |
| `lof` | 3 |
| `money_market` | 1 |
| `ordinary_index` | 1 |

### 5.2 同类组

| 同类组 | 成员数 |
| --- | ---: |
| `bond_pure|unknown` | 2 |
| `etf_linked|broad` | 2 |
| `money_market` | 1 |
| `ordinary_index|broad` | 1 |
| `etf_linked|sector` | 2 |
| `active_equity|has_text` | 1 |
| `lof|active` | 1 |
| `lof|index` | 2 |

> 跨组比较：**False**；生成排名：**False**

### 5.3 各基金实际指标

| 份额 | 产品分类 | 近1年收益 | 最大回撤 | 年化波动 | 状态 |
| --- | --- | ---: | ---: | ---: | --- |
| `000015` | bond_pure | 1.87% | 4.10% | 1.13% | ok |
| `000016` | bond_pure | 1.62% | 4.16% | 1.13% | ok |
| `000051` | etf_linked | -10.10% | 43.43% | 20.22% | ok |
| `000198` | 货币（独立口径） | — | — | — | — |
| `000478` | ordinary_index | -11.36% | 51.32% | 23.41% | ok |
| `007300` | etf_linked | 9.65% | 59.42% | 35.49% | ok |
| `007301` | etf_linked | 9.38% | 59.67% | 35.48% | ok |
| `110020` | etf_linked | -9.79% | 43.61% | 19.74% | ok |
| `110022` | active_equity | -15.43% | 57.32% | 22.03% | ok |
| `161005` | lof | -5.38% | 33.60% | 11.86% | ok |
| `012414` | lof | -24.59% | 64.87% | 25.48% | ok |
| `161725` | lof | -8.60% | 36.01% | 19.26% | ok |

---

## 5.4 验收修正（本轮）

ChatGPT 静态验收发现 3 项阻断问题，本轮窄范围修正。

### 修正 1：同类分析按基金本体去重

**问题**：`analyze_universe()` 曾把**份额级** `reports` 直接传给 `peer_analysis()`，
导致 A/C/E 被当成多个独立基金（12 份额会被数成 12 个成员）。

**修正**：

| 项 | 修正后 |
| --- | --- |
| 统计单位 | **`fund_id`**（唯一） |
| 传入 `peer_analysis` | `merge_by_fund()` 的结果（本体级） |
| 双保险 | `peer_analysis` 内部再用 `seen[fund_id]` 去重 |
| 费用比较 | **保留份额维度**，`cost_comparison.share_count` 仍是全部份额 |
| 代表份额 | 显式规则 + `representative_reason` 记录原因 |
| 数据不足 | `status=insufficient_data`，`performance=None`，**不静默取** |

**代表份额选择规则**（`REPRESENTATIVE_RULES`）：

1. 主份额（`share_code == fund_code`）且净值记录数 > 0；
2. 否则取净值记录数最多的份额（并列取代码最小）；
3. 全部份额无净值记录 → `insufficient_data`；
4. 记录数未知时不当作 0，在原因中说明「数据充分性未确认」。

**实测（真实数据库）**：

| 项 | 值 |
| --- | --- |
| 份额数 | 12 |
| 基金本体数 | 9 |
| 同类成员总数 | **9**（等于本体数，不再重复计数） |
| `deduped_by_fund_id` | **true** |

三对 A/C 都只算一个本体：

| 本体 | 份额 | 代表份额 | 原因 |
| --- | --- | --- | --- |
| `000015` | `000015` / `000016` | `000015` | 主份额且有 3310 条净值 |
| `007300` | `007300` / `007301` | `007300` | 主份额且有 1799 条净值 |
| `161725` | `161725` / `012414` | `161725` | 主份额且有 2794 条净值 |

### 修正 2：同类分组依据可验证的基准/跟踪指数

**问题**：主动权益只判断 `benchmark` 是否为空（`has_text`）；
指数基金只分 `broad`/`sector`，不同跟踪指数会混组。

**修正**：新增 `normalize_benchmark()`——**保守、可解释**的标准化，
**不新增未经验证的映射表**，认不出来就 `unknown`。

| 情况 | 处理 |
| --- | --- |
| 基准文本与已知写法完全一致 | 直接取族名，`confidence=high` |
| 含**唯一**一个可识别指数族 | 取该族，加权复合表述降为 `medium` |
| 含**多个**指数族 | `unknown`，**不强行归组** |
| 认不出任何指数族 / 为空 | `unknown` |
| 只有名称、无基准 | **不猜**（不凭基金名推断基准） |

**分组键变化**：

| 产品类 | 旧键 | 新键 |
| --- | --- | --- |
| 普通指数 / ETF联接 | `{pc}\|{broad/sector}` | `{pc}\|{scope}\|{指数族}` |
| LOF index | `lof\|index` | `lof\|index\|{scope}\|{指数族}` |
| LOF active | `lof\|active` | `lof\|active\|{基准族}` |
| 主动权益 | `active_equity\|has_text` | `active_equity\|{基准族}` |
| 债券 | `{pc}\|unknown` | 不变（久期/信用/转债全 `unknown`） |

**实测分组（8 组）**：

| 同类组 | 成员 | 基准族 |
| --- | ---: | --- |
| `etf_linked\|broad\|沪深300` | 2 | 沪深300 |
| `etf_linked\|sector\|中证全指半导体` | 1 | 中证全指半导体 |
| `ordinary_index\|broad\|中证500` | 1 | 中证500 |
| `lof\|index\|sector\|中证白酒` | 1 | 中证白酒 |
| `lof\|active\|unknown` | 1 | unknown |
| `active_equity\|unknown` | 1 | unknown |
| `bond_pure\|unknown` | 1 | 中债综合（但久期仍 unknown） |
| `money_market` | 1 | unknown |

> **沪深300 与 中证500 已分到不同组**。复合基准
> 「中证内地消费主题×85% + 中债总×15%」含两个指数族 → `unknown`，
> 不被强行塞进任一指数组。

**债券**：`duration_bucket` / `credit_bucket` / `convertible_bucket` 全 `unknown`，
**不解释成相同久期或相同风险暴露**。

### 修正 3：所有时间序列指标统一缺口安全检查

| 指标 | 修正前 | 修正后 |
| --- | --- | --- |
| 年化收益 | 只查端点有效 | 查区间缺口 + 查区间空值，命中即 `insufficient_data` |
| 滚动稳定性 | 只查端点命中 | **每个窗口独立**查缺口/空值，不合格跳过并计数 |
| 最大回撤 | 跳过空值继续连线 | 按空值/缺口**切段**，只报可观测连续段，明确 `degraded` |
| 回撤修复 | 全序列找恢复点 | 只在**同一连续段内**找，不跨越缺口 |
| Calmar | 只看底层 status | 继承年化与回撤可用性，底层降级则一并降级 |

**统一缺口入口**：`_gaps_in_range()` / `_null_count_in_range()`，
全部指标共用 `MAX_GAP_DAYS_FOR_RETURN = 15`，不再各写一套标准。

**最大回撤不再输出「无警告的完整回撤」**：

```json
{
  "degraded": true,
  "degraded_reason": "区间内存在 N 处超过 15 天的缺口；缺口与空值两端不视为连续路径。本值只是可观测连续段内的最大回撤，不是全区间完整最大回撤，可能被低估",
  "complete_interval": false,
  "segments": [{"segment_start": "...", "segment_end": "...", "max_drawdown": ...}]
}
```

**实测**：本轮 12 个份额中 11 个净值型份额均 `degraded=false`
（实际数据无超阈值缺口），货币基金走独立口径；
`000198` 货币基金年化/回撤/滚动/Calmar 全部 `None`（不适用）。

---

## 6. 测试结果

### 6.1 专项测试（真实运行）

```
$ pytest tests/test_3b5_1_fund_research.py -q
83 passed
```

覆盖 24 项要求 + 本轮验收修正 26 项：

| # | 要求 | 对应测试 |
| ---: | --- | --- |
| 1 | 正常累计净值收益 | `test_normal_acc_nav_return` |
| 2 | 单位/累计净值语义区分 | `test_unit_nav_is_not_total_return` |
| 3 | 分红不完整不修复收益 | `test_no_dividend_repair` |
| 4 | 非交易日与自然月窗口 | `test_return_uses_exact_endpoint` |
| 5 | 重复日期 | `test_duplicate_dates_detected` |
| 6 | 日期乱序 | `test_out_of_order_detected` |
| 7 | 净值缺失 | `test_null_nav_detected` |
| 8 | 连续缺口不跨越 | `test_gap_not_crossed_for_return` |
| 9 | 历史样本不足 | `test_insufficient_sample_annualized` |
| 10 | 年化自然日口径 | `test_annualized_uses_calendar_days` |
| 11 | 波动率年化条件不足拒绝 | `test_volatility_not_annualized_when_gap` |
| 12 | 无风险利率缺失不出常规 Sharpe | `test_sharpe_not_available_without_risk_free` |
| 13 | 回撤修复与 ongoing | `test_drawdown_ongoing` |
| 14 | A/C/E 份额归并 | `test_merge_by_fund_groups_shares` |
| 15 | A/C 费用独立比较 | `test_share_cost_compare_not_comparable_when_unknown` |
| 16 | 货币基金独立计算 | `test_money_indicators_isolated` |
| 17 | LOF index / active 分类 | `test_lof_index_classified_as_lof` |
| 18 | ETF 联接与场内 ETF 隔离 | `test_onshore_etf_excluded` |
| 19 | 宽基与行业主题隔离 | `test_peer_group_separates_broad_and_sector` |
| 20 | 费率生效日期边界 | `test_fee_with_effective_from_usable_after` |
| 21 | 无生效日费率禁历史回填 | `test_fee_without_effective_from_not_historical` |
| 22 | 规模不得作时点因子 | `test_aum_not_point_in_time` |
| 23 | 支付宝 unknown 不变成 true/false | `test_alipay_unknown_stays_unknown` |
| 24 | 准入等级与不可算原因 | `test_all_indicators_have_status` |

### 6.2 全量测试（真实运行）

```
$ pytest -q
1366 passed, 1 warning in 289.12s (0:04:49)
```

---

## 7. 已知限制

| # | 限制 | 影响 |
| ---: | --- | --- |
| 1 | 净值连续性 `cannot_verify` | 所有指标都是可观测区间内的估计 |
| 2 | 无基准收益序列 | 超额收益、IR、Beta 全部不可算 |
| 3 | 无风险利率缺失 | 常规 Sharpe/Sortino 不输出 |
| 4 | 无持仓数据 | 风格稳定性不可算 |
| 5 | 债券分层字段缺失 | 债券同类组只能标 unknown |
| 6 | 79 条费率无生效日 | 历史成本模拟不可算 |
| 7 | 支付宝费率与状态 unknown | 无法按真实渠道建模 |
| 8 | 规模日期是平台观测日期 | 禁止作时点因子 |
| 9 | 分红不完整 | 禁止修正历史收益 |
| 10 | 41 条清盘非全量 | 幸存者偏差未消除 |

---

## 8. 是否具备进入下一阶段的条件

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

**研究性分析引擎已可用。**
**正式回测与正式排名继续阻塞**，原因：

- 净值连续性 `cannot_verify`
- 无风险利率与基准收益序列缺失
- 费率无历史生效日，无法还原历史成本
- 支付宝可购买状态 unknown
- 样本仅 9 个本体，不足以支撑统计显著性

---

## 9. 一句话

> **引擎跑通了：9 个本体 / 12 个份额全部产出可追溯的研究报告，
> 每个指标都带状态和原因，算不出来的明确写算不出来。**
> **但样本量、净值连续性、基准与无风险利率的硬缺口都还在，
> 所以正式回测与正式排名继续关闭。**
