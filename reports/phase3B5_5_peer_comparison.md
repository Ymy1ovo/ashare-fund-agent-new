# 阶段3B-5.5 同类比较可信度

- 执行日期：2026-11-23
- 数据源：正式库 `data/fund_agent.db`（只读）
- 分组实现：`classification.peer_group_key()`（3B-5.1，未改）
- 评级实现：`quality.grade_peer_comparison()`（本阶段新增）

> **不开放正式排名，只做有明确边界的描述性比较。**

---

## 1. 当前研究池的真实分组

研究池：19 个本体 / 6 个份额，共 **13** 个同类组。

| 本体数 | 同类组 |
| ---: | --- |
| 3 | `etf_linked|broad|沪深300` |
| 2 | `bond_pure|unknown` |
| 2 | `money_market` |
| 2 | `active_equity|中证500` |
| 2 | `active_equity|unknown` |
| 1 | `ordinary_index|broad|中证500` |
| 1 | `etf_linked|broad|中证500` |
| 1 | `etf_linked|broad|上证50` |
| 1 | `etf_linked|sector|中证全指半导体` |
| 1 | `ordinary_index|broad|沪深300` |
| 1 | `lof|active|unknown` |
| 1 | `lof|index|sector|中证白酒` |
| 1 | `active_equity|中证800` |

---

## 2. 分组依据（不靠名称相似）

| 产品类型 | 分组键 | 依据 |
| --- | --- | --- |
| 普通指数 | `ordinary_index|<宽基/行业>|<指数族>` | tracking_index 优先，缺失回落 benchmark |
| ETF 联接 | `etf_linked|<宽基/行业>|<指数族>` | 同上 |
| 指数 LOF | `lof|index|<宽基/行业>|<指数族>` | 同上 |
| 主动权益 | `active_equity|<基准族>` | 只用 benchmark |
| 债券 | `bond_pure|<unknown>` 或带久期/信用桶 | benchmark 族 |
| 货币 | `money_market` | **独立组，绝不与净值型混合** |

**关键规则**：

- 基准与跟踪指数都识别不出 → `unknown`，**不强行归组**；
- 不同指数族（沪深300 / 中证500 / 上证50）**必须分开**；
- 主动与被动**必须分开**（`product_class` 不同）；
- A/C/E 按 `fund_id` 去重，一个本体只算一次。

---

## 3. 评级规则

| 条件 | 等级 | status | 结论 |
| --- | --- | --- | --- |
| 组键 unknown | **D** | `no_verifiable_group` | 拒绝比较 |
| 本体数 < 2 | **D** | `insufficient_peer_sample` | **拒绝比较** |
| 分组来源 unknown / 置信度 none | **C** | `weak_grouping` | 只并列，不判断强弱 |
| 本体数 2~4 | **C** | `small_sample` | 只描述性对照 |
| 本体数 ≥ 5 且分组可靠 | **B** | `usable` | 描述性并列 |

**A 不存在**：连续性 `cannot_verify` 是结构性限制，不会因样本多而消失。

---

## 4. 实测：本阶段样本的同类可比性

| 代码 | 类型 | 同类组 | 本体数 | 等级 | status |
| --- | --- | --- | ---: | --- | --- |
| `050002` | 普通指数基金 | `ordinary_index|broad|沪深300` | 1 | **D** | `insufficient_peer_sample` |
| `001052` | ETF联接基金 | `etf_linked|broad|中证500` | 1 | **D** | `insufficient_peer_sample` |
| `001938` | 主动权益基金 | `active_equity|中证500` | 2 | **C** | `small_sample` |
| `000032` | 债券基金 | `bond_pure|unknown` | 2 | **C** | `small_sample` |
| `000509` | 货币基金 | `money_market` | 2 | **C** | `weak_grouping` |
| `001548` | ETF联接 A/C 组（A 类） | `etf_linked|broad|上证50` | 1 | **D** | `insufficient_peer_sample` |
| `001549` | ETF联接 A/C 组（C 类） | `etf_linked|broad|上证50` | 1 | **D** | `insufficient_peer_sample` |

**结论：全部为 D（样本不足）或 C（小样本），没有一只可以真正做同类比较。**

这是**如实结论**，不是能力缺陷：研究池目前只有 19 个本体、13 个组，
最大的组也只有 3 个本体。在这种样本量下发「同类排名」就是造假。

---

## 5. 为什么不能强行比较

| 陷阱 | 本框架怎么挡 |
| --- | --- |
| 名称相似就判同类 | 分组只看 tracking_index / benchmark，名称不参与 |
| 基准未知硬构造排名 | 组键 unknown → **D** `no_verifiable_group` |
| 样本少也出排名 | 本体数 < 2 → **D**；2~4 → **C**，都标「只描述性」 |
| 货币与净值型同榜 | `money_market` 独立组键，物理隔离 |
| A/C 算两只基金 | `deduped_by_fund_id=true`，成员按 fund_id 去重 |
| 跨组横向比较 | `cross_group_comparison_allowed=false` |
| 输出排名 | `ranking_generated=false`（固定值，不由参数控制） |

---

## 6. 现有可用的描述性对照（唯一一组本体数 ≥ 3）

同类组 `etf_linked|broad|沪深300`，本体数 **3**：

| 本体 | 代码 | 代表份额 | 近1年收益 | 最大回撤 |
| ---: | --- | --- | --- | --- |
| 14 | `000051` | `000051` | -10.0981% | 43.4343% |
| 66 | `000961` | `000961` | -10.4936% | 46.3499% |
| 15 | `110020` | `110020` | -9.7926% | 43.6093% |

**这只是并列展示，不是排名**：

- 3 个样本不足以支撑任何「谁更好」的结论；
- 净值连续性 `cannot_verify`，三者的可观测区间未必一致；
- 未做风险调整（Sharpe 不可算）；
- 未考虑费率、规模、经理。

---

## 7. 同类比较里缺什么（如实列出）

| 缺的东西 | 影响 |
| --- | --- |
| 基准收益序列 | 无法算超额收益、信息比率、Beta |
| 无风险利率 | 无法算 Sharpe，无法做风险调整比较 |
| 完整历史规模 | 无法控制规模因子 |
| 完整历史经理 | 无法控制经理任期 |
| 真实净值公布日历 | 无法确认各基金可观测区间完全一致 |
| 完整费率 | 无法做净费后比较 |

在这些补齐之前，同类比较只能停在 **C**（小样本描述）或 **D**（拒绝）。

---

## 8. 边界声明

| 项 | 值 |
| --- | --- |
| 生成排名 | **否** |
| 跨组比较 | **禁止** |
| 货币混入净值榜 | **禁止** |
| 修改分组逻辑 | **否**（沿用 3B-5.1） |
