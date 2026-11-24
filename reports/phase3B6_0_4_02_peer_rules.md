# 阶段3B-6.0.4 同类比较规则文档

- 基线 HEAD：`f64b7e554d7303c523bb6ba9ee84550b2e0a7a9d`  数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`

---

## 0. 铁律

| # | 规则 | 实现位置 |
| ---: | --- | --- |
| 1 | 同一基金主体按 `fund_id` 只计 1 个 | `peer_engine.analyze_group` |
| 2 | 不为了增加样本合并不可比较基金 | `group_usability` |
| 3 | 基准族 unknown → 只能描述性，**永不可比较** | `is_verifiable_group` |
| 4 | 货币基金独立口径，不与净值型混算 | `analyze_group` money 分支 |
| 5 | LOF 保持独立组键，不与指数/ETF联接合并 | `classify_fund` + `peer_group_key` |
| 6 | 组内 <2 本体 → 排除 | `group_usability` |

---

## 1. 六类场外基金的比较规则

### 1.1 普通指数基金（`ordinary_index`）

| 项 | 规则 |
| --- | --- |
| 分组依据 | `product_class` + `index_scope`（broad/sector）+ 基准族 |
| 组键格式 | `ordinary_index\|<index_scope>\|<家族>` |
| 可否合并不同指数 | **否** |
| 宽基/行业是否分开 | **是** |
| 当前组数 | 3（中证500=5、沪深300=4、中证A500=3 之外还有 3 个单只组） |

### 1.2 ETF 联接基金（`etf_linked`）

| 项 | 规则 |
| --- | --- |
| 分组依据 | 同普通指数：产品类型 + 指数范围 + 基准族 |
| 与场内 ETF 是否混排 | **否**（`is_offmarket_pool` 排除） |
| 与普通指数基金是否混排 | **否**（`product_class` 不同 → 组键不同） |
| 当前可比较组 | `etf_linked\|broad\|沪深300`（5 本体） |

### 1.3 主动权益基金（`active_equity`）

| 项 | 规则 |
| --- | --- |
| 分组依据 | **可验证的业绩基准族** |
| 基准不明时 | `unknown` 组，**不得按名称猜** |
| 组键格式 | `active_equity\|<基准族>` |
| `unknown` 组可否声称同类可比 | **否**，只能描述性 |
| 当前可比较组 | `active_equity\|中证800`（5 本体） |

### 1.4 债券基金（`bond_pure` / `bond_mixed`）

| 项 | 规则 |
| --- | --- |
| 纯债与混合债 | **必须分开**（不同 `product_class`） |
| 久期/信用/转债字段 | 全库 NULL → `duration_bucket=unknown` |
| 数量达标能否判定可比较 | **不能**（组键含 unknown → 只能描述性） |
| 当前状态 | `bond_pure\|unknown` 14 本体、`bond_mixed\|unknown` 2 本体 |
| 评级影响 | `bond_pure\|unknown` 按 3B-5.5.1 必须评 **D** |

**这是本阶段最重要的边界**：14 个纯债基金数量充足，
但组键中含 `unknown`，**不构成本轮认定的可比较组**。

### 1.5 货币基金（`money_market`）

| 项 | 规则 |
| --- | --- |
| 收益口径 | 每万份收益 + 7 日年化 |
| 与净值型混算 | **绝对禁止** |
| 共同净值区间 | 不适用（`metric_basis=money_yield`） |
| 组键 | `money_market`（产品类型隔离） |
| 当前状态 | 7 本体，**可比较** |

### 1.6 LOF 场外份额（`lof`）

| 项 | 规则 |
| --- | --- |
| 是否独立识别 | **是**（产品结构优先于是否跟踪指数） |
| 与普通指数/ETF联接合并 | **禁止** |
| 组键格式 | `lof\|index\|<scope>\|<家族>` 或 `lof\|active\|<家族>` |
| 当前状态 | 3 本体，分别 1/1/1 → 全部 excluded |

### 1.7 A/C 份额

| 项 | 规则 |
| --- | --- |
| 同类数量计数 | 按 `fund_id`，A/C 只算 **1** 个 |
| 成本分析 | 可分别计算，单位是**份额** |
| 表现比较 | 按代表份额或按本体，**不得**两份额各算一次 |

---

## 2. 可比较性判定树

```
组内本体数 < 2      → excluded
组内本体数 >= 2:
  基准族 unknown  → descriptive_only  （数量再多也不能可比）
  基准族已知:
    本体数 < 5    → descriptive_only  （样本偏小）
    本体数 >= 5   → comparable
```

---

## 3. 本轮 26 组的判定结果

| 级别 | 组数 |
| --- | ---: |
| `comparable` | **4** |
| `descriptive_only` | **12** |
| `excluded` | **10** |

---

## 4. 明确禁止的做法

| 做法 | 为什么禁止 |
| --- | --- |
| 把所有指数基金合成一个组 | 不同指数不可比 |
| ETF联接与场内 ETF 混排 | 产品结构不同 |
| A/C 各算一个同业 | 重复计数 |
| 按基金名称猜跟踪指数 | 无证据 |
| 纯债 14 只就判可比 | 组键 unknown，按规则必须 D |
| LOF 并入普通指数 | 产品结构不同 |
| 货币基金混入净值排名 | 收益口径不同 |

---

## 5. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
