# 阶段3B-5.5 同类比较可信度（3B-5.5.1 修正版）

- 执行日期：2026-11-23
- 修正轮：3B-5.5.1
- 数据源：正式库 `data/fund_agent.db`（只读）
- 分组实现：`classification.peer_group_key()`（3B-5.1，**未改**）
- 评级实现：`quality.grade_peer_comparison()`（本修正轮已修）

> **不开放正式排名，只做有明确边界的描述性比较。**

---

## 0. 本轮修正了什么

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| `verifiable_group=False` | 读了但**没用**，样本多仍给 B/C | **直接 D** `no_verifiable_group`，样本再多也不放行 |
| 组键基准族为 unknown | 只判断字符串是否以 `unknown` 开头，`bond_pure\|unknown` 被当有效 | **解析最后一段**，family=unknown 即 **D** |
| `bond_pure\|unknown` | 评 C（小样本） | **D** |
| `active_equity\|unknown` | 可能被当有效 | **D** |
| 货币基金 | 与其他指标同路径 | 特例：产品类型独立分组，不要求基准，但**永不与净值型混组** |
| 判定顺序 | 先看样本量 | **先看依据可验证性，通过后才看样本量** |

---

## 1. 判定顺序（修正后）

```
① 货币基金 money_market → 产品类型独立分组，跳过基准检查
② verifiable_group is False → D（样本再多也不放行）
③ 组键缺失 → D
④ 组键基准/指数族为 unknown（含 bond_pure|unknown / active_equity|unknown）→ D
⑤ 组键以 unknown 开头 → D
⑥ 依据通过后才看样本量：
     本体 1 个 → D insufficient_peer_sample
     本体 2~4 个 → C small_sample
     本体 ≥5 个 且分组可靠 → B usable
   永远不到 A（净值连续性 cannot_verify 是结构性限制）
```

---

## 2. 当前研究池的真实分组

研究池：19 个本体 / 26 个份额，共 **13** 个同类组。

| 本体数 | 同类组 | 可验证 | 评级结果 |
| ---: | --- | --- | --- |
| 3 | `etf_linked|broad|沪深300` | 是 | C 小样本 |
| 2 | `bond_pure|unknown` | **否** | **D** |
| 2 | `money_market` | 产品类型 | C 小样本 |
| 2 | `active_equity|中证500` | 是 | C 小样本 |
| 2 | `active_equity|unknown` | **否** | **D** |
| 1 | `ordinary_index|broad|中证500` | 是 | D 样本不足 |
| 1 | `etf_linked|broad|中证500` | 是 | D 样本不足 |
| 1 | `etf_linked|broad|上证50` | 是 | D 样本不足 |
| 1 | `etf_linked|sector|中证全指半导体` | 是 | D 样本不足 |
| 1 | `ordinary_index|broad|沪深300` | 是 | D 样本不足 |
| 1 | `lof|active|unknown` | **否** | **D** |
| 1 | `lof|index|sector|中证白酒` | 是 | D 样本不足 |
| 1 | `active_equity|中证800` | 是 | D 样本不足 |

---

## 3. 实测：本阶段样本的同类可比性

| 代码 | 类型 | 同类组 | 本体数 | 等级 | status |
| --- | --- | --- | ---: | --- | --- |
| `050002` | 普通指数基金 | `ordinary_index|broad|沪深300` | 1 | **D** | `insufficient_peer_sample` |
| `001052` | ETF联接基金 | `etf_linked|broad|中证500` | 1 | **D** | `insufficient_peer_sample` |
| `001938` | 主动权益基金 | `active_equity|中证500` | 2 | **C** | `small_sample` |
| `000032` | 债券基金 | `bond_pure|unknown` | 2 | **D** | `no_verifiable_group` |
| `000509` | 货币基金 | `money_market` | 2 | **C** | `small_sample` |
| `001548` | ETF联接 A/C 组（A 类） | `etf_linked|broad|上证50` | 1 | **D** | `insufficient_peer_sample` |
| `001549` | ETF联接 A/C 组（C 类） | `etf_linked|broad|上证50` | 1 | **D** | `insufficient_peer_sample` |

**关键变化**：

| 代码 | 修复前 | 修复后 | 原因 |
| --- | --- | --- | --- |
| `000032` | C（small_sample） | **D**（no_verifiable_group） | `bond_pure\|unknown` 基准族未知，久期/信用暴露无可靠数据 |
| `001938` | C | C（small_sample） | `active_equity\|中证500` 是有效分组，2 个本体 |
| `000509` | C | C（small_sample） | 货币基金按产品类型分组，不受基准缺失影响 |
| 其余 | D | D | 本体重不足 |

---

## 4. 为什么不修 `classification.py`

`peer_group_key()` 的 `verifiable_group` 计算本身是对的：

```python
base["verifiable_group"] = norm["family"] != "unknown" or pc in (
    "bond_pure", "bond_mixed", "money_market")
```

问题在**评级层**没真正使用它。把它当有效是很自然的误判：
`bond_pure|unknown` 字符串不含 `unknown` 前缀、`verifiable_group=True`，
看起来「有分组」。但基准族是 unknown，等于把所有纯债基金塞进同一组，
久期与信用暴露完全没区分——这不是同类。

因此本轮**只改评级层的判定顺序**，不动分组逻辑。

---

## 5. 仍然缺什么（如实列出）

| 缺的东西 | 影响 |
| --- | --- |
| 基准收益序列 | 无法算超额收益、信息比率、Beta |
| 无风险利率 | 无法算 Sharpe，无法做风险调整比较 |
| 债券久期/信用/转债暴露 | 纯债基金无法细分，只能标 unknown |
| 完整历史规模 | 无法控制规模因子 |
| 完整历史经理 | 无法控制经理任期 |
| 真实净值公布日历 | 无法确认各基金可观测区间完全一致 |
| 完整费率 | 无法做净费后比较 |

在这些补齐之前，同类比较只能停在 **C**（小样本描述）或 **D**（拒绝）。

---

## 6. 边界声明

| 项 | 值 |
| --- | --- |
| 生成排名 | **否** |
| 跨组比较 | **禁止** |
| 货币混入净值榜 | **禁止** |
| 修改分组逻辑 | **否**（沿用 3B-5.1） |
| A/C 是否按 fund_id 去重 | **是** |
