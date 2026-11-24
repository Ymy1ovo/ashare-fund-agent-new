# 阶段3B-6.0.4.1 数据质量报告（修正版）

- 本轮基线 HEAD：`a31270683f1417813ad8ac650fc5ebd9be32b79f`  数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`
- 执行：2026-11-24 14:16

> **本版修正两处**：① `bond_pure|unknown` / `bond_mixed|unknown` 由 C 改 **D**；
> ② 组级等级改由 `quality.grade_peer_comparison()` 唯一权威计算。

---

## 0. 修正说明

| 组键 | 3B-6.0.4 | 本版 | 原因 |
| --- | --- | --- | --- |
| `bond_pure\|unknown` | C（**错**） | **D** | 基准族 unknown |
| `bond_mixed\|unknown` | C（**错**） | **D** | 基准族 unknown |
| `active_equity\|unknown` | C | **D** | 基准族 unknown |
| `money_market` | B | **B** | 产品类型特例，保持 |

**根因**：旧报告自建「状态→等级」映射，绕过了既定规则。已改为单一权威来源。

---

## 1. 维度质量总览

| 维度 | 状态 | 等级 |
| --- | --- | --- |
| 净值覆盖率 | 86/86 份额 | **A** |
| 净值连续性 | 3 只有 >15 天缺口 | **B** |
| 净值重复 | 0 处 | **A** |
| 累计净值可用性 | 214,383/214,466 | **A** |
| 分红完整性 | 40/79，acc_nav 已含分红 | **B** |
| A/C 归并 | 0 对重复本体 | **A** |
| 基准证据 | 0/10 口径核实 | **D** |
| 复合基准 | 0/15 可复现 | **D** |
| 规模时点 | 0/683 | **D** |
| 经理时点 | 12/21 | **C** |
| 费率有效期 | 11/90 | **D** |
| 无风险利率 | 无 | **D** |

---

## 2. 28 组质量等级（全部）

| 组键 | 本体数 | 等级 | 状态 |
| --- | ---: | --- | --- |
| `bond_pure|unknown` | 12 | **D** | no_verifiable_group |
| `money_market` | 7 | **B** | usable |
| `etf_linked|broad|沪深300` | 5 | **B** | usable |
| `ordinary_index|broad|中证500` | 5 | **B** | usable |
| `active_equity|unknown` | 4 | **D** | no_verifiable_group |
| `ordinary_index|broad|沪深300` | 4 | **C** | small_sample |
| `active_equity|中证800` | 3 | **C** | small_sample |
| `etf_linked|broad|中证500` | 3 | **C** | small_sample |
| `active_equity|沪深300` | 3 | **C** | small_sample |
| `etf_linked|broad|上证50` | 3 | **C** | small_sample |
| `etf_linked|broad|创业板指` | 3 | **C** | small_sample |
| `lof|active|unknown` | 3 | **D** | no_verifiable_group |
| `etf_linked|broad|中证A500` | 3 | **C** | small_sample |
| `ordinary_index|broad|中证A500` | 3 | **C** | small_sample |
| `bond_mixed|unknown` | 2 | **D** | no_verifiable_group |
| `lof|active|中证800` | 2 | **C** | small_sample |
| `active_equity|中证500` | 2 | **C** | small_sample |
| `etf_linked|unknown|unknown` | 2 | **D** | no_verifiable_group |
| `active_equity|中证A500` | 1 | **D** | insufficient_peer_sample |
| `lof|active|中债综合` | 1 | **D** | insufficient_peer_sample |
| `ordinary_index|broad|创业板指` | 1 | **D** | insufficient_peer_sample |
| `lof|active|沪深300` | 1 | **D** | insufficient_peer_sample |
| `ordinary_index|unknown|上证50` | 1 | **D** | insufficient_peer_sample |
| `ordinary_index|broad|上证50` | 1 | **D** | insufficient_peer_sample |
| `etf_linked|sector|中证全指半导体` | 1 | **D** | insufficient_peer_sample |
| `etf_linked|broad|unknown` | 1 | **D** | no_verifiable_group |
| `ordinary_index|unknown|unknown` | 1 | **D** | no_verifiable_group |
| `lof|index|sector|中证白酒` | 1 | **D** | insufficient_peer_sample |

| 等级 | 组数 |
| --- | ---: |
| **A** | 0 |
| **B** | 3 |
| **C** | 10 |
| **D** | 15 |

**没有 A 级组**：基准证据全 unknown，同类比较缺可验证基准。

---

## 3. 与 3B-6.0.4 的差异

| 项 | 3B-6.0.4 | 本版 |
| --- | ---: | ---: |
| 组数 | 26 | **28** |
| A 级 | 0 | 0 |
| B 级 | 4 | **3** |
| C 级 | 20（含错标） | **10** |
| D 级 | 2 | **15** |

**D 级从 2 增到 15**：因为所有基准族 unknown 的组现在都按规则评 D，
不再被错标为 C。

---

## 4. 关键：数量达标 ≠ 可比较

| 组键 | 本体数 | 等级 | 说明 |
| --- | ---: | --- | --- |
| `bond_pure\|unknown` | **12** | **D** | 样本多但基准族 unknown |
| `bond_mixed\|unknown` | 2 | **D** | 同上 |

**3B-5.5.1 铁律：分组依据不可验证 → D，与样本量无关。**

---

## 5. 净值质量（未变）

| 项 | 数值 |
| --- | ---: |
| 净值序列覆盖 | 86/86 |
| `net_value` / `money_yield` | 79 / 7 |
| 重复 `(share,date)` | **0** |
| `acc_nav` 非空 | 214,383 |
| 有分红但 acc==unit | **0** |

超阈值缺口 3 只：`000037`（2,498 天）、`050002`（31 天）、`000001`（17 天）。

---

## 6. 基准证据（最弱维度，未变）

| 项 | 数值 | 等级 |
| --- | ---: | --- |
| 指数收益口径 unknown | 10/10 | **D** |
| 复合基准可复现 | 0/15 | **D** |
| 复合基准缺失成分 | 17/34 | **D** |
| `tracking_index` 覆盖 | 0/79 | **D** |

---

## 7. 本轮新增的已知问题（已修）

| 问题 | 状态 |
| --- | --- |
| LOF 只按简称识别，5 只漏识别 | **已修**（综合全称） |
| `bond_pure\|unknown` 错标 C | **已修**（改 D） |

## 8. 仍未修的问题

| 问题 | 影响 |
| --- | --- |
| 库内 `fund_type_l1` 与天天基金分类在 16/17 只债券基金上不一致 | 混合债组只有 2 只 |
| 41 个清盘本体缺 `fund_type_l1` | 无法分类 |
| `000037` 2,498 天缺口 | 该基金早期窗口不可用 |
| `161725` 全称缺 LOF 标记 | 已按简称识别并标注，不影响结论 |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
