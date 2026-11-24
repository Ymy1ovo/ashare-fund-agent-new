# 阶段3B-6.0.3 同类样本覆盖报告

- 基线 HEAD：`4be8b044b2cc8f2d0a40c2cc8241bc66f2249dab`
- 执行日期：2026-11-24

---

## 0. 覆盖总览

| 项 | 扩容前 | 扩容后 |
| --- | ---: | ---: |
| 同类组数 | 13 | **26** |
| ≥5 本体的组 | **0** | **5** |
| ≥10 本体的组 | 0 | **1** |
| 最大组 | 3 | **14** |
| 仍 <2 本体的组 | 8 | 10 |

---

## 1. 达标组（≥5 本体）

| 组键 | 本体数 | 是否可验证 |
| --- | ---: | --- |
| `bond_pure|unknown` | **14** | 否 |
| `money_market` | **7** | 产品类型 |
| `active_equity|中证800` | **5** | 是 |
| `etf_linked|broad|沪深300` | **5** | 是 |
| `ordinary_index|broad|中证500` | **5** | 是 |

### 1.1 注意：只有 4 组是「可验证基准组」

| 组键 | 是否可验证 | 原因 |
| --- | --- | --- |
| `bond_pure\|unknown` | **否** | 久期/信用/转债字段全 NULL |
| `money_market` | 产品类型隔离 | 独立收益口径 |
| `etf_linked\|broad\|沪深300` | **是** | 基准可识别 |
| `ordinary_index\|broad\|中证500` | **是** | 基准可识别 |
| `active_equity\|中证800` | **是** | 基准可识别 |

**纯债组虽然有 14 个本体，但组键是 `bond_pure|unknown`，
按 3B-5.5.1 规则必须评 D**——数量达标不等于可比较。

---

## 2. 全部 26 组明细

| 本体数 | 组键 | 可验证 | 按规则评级 |
| ---: | --- | --- | --- |
| 14 | `bond_pure|unknown` | **否** | **D** |
| 7 | `money_market` | 产品类型 | B |
| 5 | `active_equity|中证800` | 是 | B |
| 5 | `etf_linked|broad|沪深300` | 是 | B |
| 5 | `ordinary_index|broad|中证500` | 是 | B |
| 4 | `active_equity|unknown` | **否** | **D** |
| 4 | `active_equity|沪深300` | 是 | C |
| 4 | `ordinary_index|broad|沪深300` | 是 | C |
| 3 | `etf_linked|broad|上证50` | 是 | C |
| 3 | `etf_linked|broad|中证500` | 是 | C |
| 3 | `etf_linked|broad|中证A500` | 是 | C |
| 3 | `etf_linked|broad|创业板指` | 是 | C |
| 3 | `ordinary_index|broad|中证A500` | 是 | C |
| 2 | `active_equity|中证500` | 是 | C |
| 2 | `bond_mixed|unknown` | **否** | **D** |
| 2 | `etf_linked|unknown|unknown` | **否** | **D** |
| 1 | `active_equity|中证A500` | 是 | D |
| 1 | `etf_linked|broad|unknown` | **否** | **D** |
| 1 | `etf_linked|sector|中证全指半导体` | 是 | D |
| 1 | `lof|active|unknown` | **否** | **D** |
| 1 | `lof|active|中债综合` | 是 | D |
| 1 | `lof|index|sector|中证白酒` | 是 | D |
| 1 | `ordinary_index|broad|上证50` | 是 | D |
| 1 | `ordinary_index|broad|创业板指` | 是 | D |
| 1 | `ordinary_index|unknown|unknown` | **否** | **D** |
| 1 | `ordinary_index|unknown|上证50` | 是 | D |

---

## 3. 仍不足的类别

| 类别 | 本体数 | 缺口 | 原因 |
| --- | ---: | ---: | --- |
| 混合债券基金 | 2 | 距 5 缺 3 | 库内类型字段与天天基金分类不一致（16/17 只债券基金）|
| LOF 场外份额 | 3 | 距 5 缺 2 | 5 只 LOF 简称不含「(LOF)」，分类器识别不到 |

**这两个缺口是数据层面的，不是样本量不够。**

### 3.1 为什么不强行凑数

| 做法 | 为什么不做 |
| --- | --- |
| 把混合债券并入纯债 | 风险特征不同，混淆后组键失去意义 |
| 改分类器认全称 | 属于修改 3B-5.0 定稿规则，不在本轮授权 |
| 用 C 类份额凑数 | A/C 是同一本体，重复计数 |

---

## 4. 可进入下一阶段的客观结论

| 问题 | 结论 |
| --- | --- |
| 能否做同类描述性对照 | **部分可以**：4 个可验证组 ≥5 本体 |
| 能否做正式同类排名 | **否**：门禁未开 |
| 能否做超额收益验证 | **否**：指数口径全 unknown |
| 能否做正式回测 | **否** |
| 纯债 14 只能否直接比较 | **否**：组键 unknown，必须评 D |

---

## 5. 边界

| 项 | 值 |
| --- | --- |
| 把所有指数基金合成一个组 | **否** |
| A/C 重复计数 | **否** |
| 为凑数合并不可比类别 | **否** |
| 修改分类规则 | **否** |
