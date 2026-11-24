# 阶段3B-6.0.4 基准证据与超额收益边界报告

- 基线 HEAD：`f64b7e554d7303c523bb6ba9ee84550b2e0a7a9d`  数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`
- 执行：2026-11-24 13:30（**实际调用本模块判定，非静态推断**）

---

## 0. 结论先行

> **`excess_return_status = not_available`**
>
> 本阶段**不计算任何超额收益**。原因见下。

| 问题 | 答案 |
| --- | --- |
| 能否计算超额收益 | **否** |
| 阻断原因 | 指数收益口径 10/10 unknown |
| 复合基准能否复现 | **否**，15/15 不可复现 |
| 同类相对表现能否称 Alpha | **否** |

---

## 1. 指数收益口径实测

| 指数代码 | 名称 | 收益口径 |
| --- | --- | --- |
| `000012` | 上证国债指数 | **`unknown`** |
| `000016` | 上证50指数 | **`unknown`** |
| `000300` | 沪深300指数 | **`unknown`** |
| `000905` | 中证小盘500指数 | **`unknown`** |
| `000906` | 中证800指数 | **`unknown`** |
| `000922` | 中证红利指数 | **`unknown`** |
| `000942` | 中证内地消费主题指数 | **`unknown`** |
| `399997` | 中证白酒指数 | **`unknown`** |
| `930930` | 中证港股通综合指数 | **`unknown`** |
| `H30184` | 中证全指半导体产品与设备指数 | **`unknown`** |

**10 / 10 全部 `unknown`。** 数据源（中证指数接口）只提供点位，
不声明是价格指数还是全收益指数，因此无从判定。

---

## 2. 阻断逻辑（实测调用结果）

```json
{
 "excess_return_status": "not_available",
 "block": "index_return_basis_unknown",
 "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较",
 "component_checks": [
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  },
  {
   "usable": false,
   "block": "index_return_basis_unknown",
   "reason": "口径 unknown：没有证据证明是全收益指数，禁止用于总收益比较"
  }
 ],
 "unusable_count": 10,
 "peer_relative_is_not_alpha": true
}
```

---

## 3. 四道独立闸门

任何一道不通过，超额收益就不可算：

| 闸门 | 规则 | 当前状态 |
| --- | --- | --- |
| ① 口径闸 | `price_return` / `unknown` 不得冒充 `total_return` | **不通过**（10/10 unknown） |
| ② 复合基准闸 | 必须全部成分齐全且有权重 | **不通过**（15/15） |
| ③ 序列闸 | 必须有基准收益序列 | **不通过**（库内无此表） |
| ④ 命名闸 | 同类相对表现不得称为 Alpha | **已强制**（`peer_relative_is_not_alpha=true`） |

---

## 4. 复合基准成分缺口

共 **15** 条复合基准，成分缺失情况：

| 成分类型 | `data_available=0` | `data_available=1` |
| --- | ---: | ---: |
| `bond_index` | 5 | 0 |
| `cash` | 10 | 0 |
| `fixed_rate` | 1 | 0 |
| `index` | 1 | 0 |
| `index` | 0 | 17 |

**债券 / 现金 / 固定利率成分全部无可用序列**，
这是复合基准不可复现的根本原因。

---

## 5. 为什么不能用单个指数替代复合基准

| 做法 | 为什么禁止 |
| --- | --- |
| 用沪深300 替代「沪深300×70% + 中债×30%」 | 收益与风险特征完全不同 |
| 只看指数成分忽略债券成分 | 债券成分占 20–40% 权重 |
| 用现金成分近似为 0 收益 | 现金有真实利息，填 0 会低估基准 |

---

## 6. 同类相对表现 ≠ 超额收益

```json
{
 "peer_relative_meaning": "同类相对表现 = 该基金在其可验证同类组内的描述性位置，**不是**相对于投资基准的超额收益",
 "ranking_is_not_alpha": true,
 "no_forward_guarantee": true,
 "why_not": [
  "同类组只保证产品类型/跟踪指数可比，不保证投资策略相同",
  "库内无基准收益序列，无法计算超额收益",
  "历史相对表现不构成未来收益保证"
 ]
}
```

**必须区分的三件事**：

| 概念 | 定义 | 本阶段能否计算 |
| --- | --- | --- |
| 同类相对表现 | 组内描述性位置 | **可以**（4 个可比较组） |
| 超额收益 | 相对可验证基准的超额 | **不可以** |
| Alpha | 风险调整后的真实超额能力 | **不可以**，且无统计检验 |

**一只基金在同类中排第一，不能说明它创造了 Alpha。**

---

## 7. 什么条件下才能解禁

| 前置条件 | 当前 | 差距 |
| --- | --- | --- |
| 指数收益口径核实为 total_return | 0/10 | 需查指数公司官方编制方案 |
| 复合基准全部成分可用 | 0/15 | 需接入债券指数 + 现金收益序列 |
| 基准收益序列表 | 无 | 需新建基准收益层 |
| 无风险利率 | 无 | 需接入国债/回购利率 |

四项全部满足后才可讨论超额收益。**本阶段不启动这些工作。**

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
| `excess_return_status` | **`not_available`** |
