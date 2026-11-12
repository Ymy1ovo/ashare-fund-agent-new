# 阶段3A.3.2 会计设计：公司行为如何进入账本

- 编写时间：2026-11-12
- 前置：`reports/phase3A3_2_corporate_action_audit.md`
- 性质：**设计说明**。本文件定义规则，实现见 `app/backtest/corporate_actions.py` 与修复报告。

## 1. 三条不可让渡的原则

| # | 原则 | 反面做法（明确禁止） |
| ---: | --- | --- |
| 1 | 成交与估值**只用原始价格** | 把 `close` 换成 `adjusted_close` 掩盖账本问题 |
| 2 | 份额变化**只通过事件调整数量**，分红**只通过事件进入现金** | 用复权因子「隐含」分红，账本里没有对应记录 |
| 3 | 事件**必须来自官方证据**，未确认事件不得应用 | 看到价格跳变就反推比例并写库 |

## 2. 三个价格口径的职责划分

| 字段 | 含义 | 用途 | 本阶段是否改动 |
| --- | --- | --- | --- |
| `close` / `open` / `high` / `low` | 真实历史原始成交价 | **撮合成交价、每日估值价** | 否 |
| `adjusted_close` | 含分红再投资的前复权价 | 技术指标（MA 等）、收益分析 | 否 |
| 账本 `positions[code]` + `cash` | 真实份额与现金 | 组合净值 | **是（新增事件调整）** |

**为什么不能用 `adjusted_close` 估值**：它把分红折算进了价格，
账本中不会出现「现金分红」这一笔。一旦用复权价估值，
组合净值会「看起来正确」但账本不可审计——
无法回答「这笔钱是从哪来的」，也无法核对券商的现金对账单。

## 3. 事件模型

### 3.1 表结构

```sql
corporate_actions (
    action_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,                 -- ETF 代码
    action_type TEXT NOT NULL,          -- split / reverse_split / cash_distribution / other
    ex_date TEXT NOT NULL,              -- 除权除息日（官方公告的折算日/除息日）
    effective_date TEXT NOT NULL,       -- 实际生效交易日（下一个交易日）
    share_ratio REAL,                   -- 份额比例（拆分>1，合并<1）
    cash_per_share REAL,                -- 每份现金分红
    record_date TEXT,                   -- 权益登记日
    pay_date TEXT,                      -- 发放日
    source TEXT NOT NULL,               -- 来源 URL
    evidence TEXT,                      -- 证据摘要
    status TEXT NOT NULL DEFAULT 'unverified',  -- confirmed / unverified / rejected
    data_version TEXT NOT NULL DEFAULT 'ca-v1',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(code, action_type, ex_date)  -- 幂等导入
)
```

### 3.2 应用记录表

```sql
corporate_action_applications (
    application_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    action_id INTEGER NOT NULL,
    code TEXT, effective_date TEXT, action_type TEXT,
    shares_before INTEGER, shares_after INTEGER,
    cash_delta REAL, fractional_cash REAL,
    applied_at TEXT NOT NULL,
    UNIQUE(run_id, action_id)           -- 同一事件对同一次回测只能应用一次
)
```

**为什么单独建表而不是写进 `backtest_orders`**：公司行为不是成交，
没有对手方、没有价格、没有滑点。混进成交流水会污染
「交易次数 / 换手率 / 胜率」等所有基于 trade 的统计。

## 4. 账本规则

### 4.1 份额拆分 / 合并

```
新数量 = floor(旧数量 × 比例)
零碎部分 = (旧数量 × 比例) - 新数量
零碎现金 = 零碎部分 × 当日原始收盘价   （若无价格则为 0，并留痕）
```

**经济价值连续性**：拆分后价格理论上按 1/比例 调整，因此
`旧数量 × 旧价格 = 新数量 × 新价格`。测试 13/14 用构造行情验证：
给定「数量 ×10、价格 ÷10」，总资产必须完全不变。

**成本基准**：每批次 `lot.price` 按 1/比例 反比调整，
保证 `Σ(批次数量 × 批次成本) ` 守恒。这样卖出时的已实现盈亏不会因为拆分而失真。

**零碎股处理**：ETF 拆分极少产生零碎（比例多为整数），
但 `1.1454`、`0.3656` 这类非整数比例会产生。按当日收盘价折现金，
并在 `fractional_cash` 字段留痕。实测全部 166 个事件中，
零碎现金合计 188.49 元（占比 < 0.02%），可忽略但必须记录。

### 4.2 现金分红

```
现金增量 = 事件日持仓数量 × 每份分红
```

- **入账时点**：除息日（`ex_date`）的下一交易日（`effective_date`），
  与价格除息下跌同一天，保证「价格跌、现金补」在净值上抵消。
- **不使用登记日**：登记日只决定「谁有资格」，经济价值变化发生在除息日。
- **发放日差异**：官方发放日通常晚 3~5 个交易日。
  本阶段按除息日入账（经济价值已确定），**不模拟可用现金时点差异**；
  该差异只影响「能否立即再投资」，在回测中体现为极小的机会成本，已在局限中说明。
- **不重复计入**：账本用原始价格估值，分红不会同时出现在价格和现金里。

### 4.3 同日多事件

同一标的可能在同一天既有拆分又有分红（如 `512690` 2021-05-17 拆分 + 之后的除息）。
处理顺序：**先调整份额，再记现金分红**。
理由：分红金额按「除息日持仓」计算，而除息日持仓已经是拆分后的数量。

### 4.4 未确认事件

```
status != 'confirmed'  →  Engine 完全跳过，不调整任何数量或现金
                        →  result.notes 写入「未确认事件未应用（unverified_corporate_action）」
                        →  报告中必须标注该标的的回测结果带数据质量风险
```

**实测**：本阶段 166 条事件全部 confirmed，**0 条 unverified**，
因此不影响后续结论。但机制必须存在，防止未来误用。

## 5. 与引擎的集成点

```
BacktestEngine.run()
  ├─ _load_corporate_actions()      读事件表（只取 confirmed，区间内）
  └─ for trade_date in calendar:
       ├─ 0) _apply_corporate_actions()   ← 新增，在开盘撮合之前
       ├─ 1) 开盘撮合（signal_date < trade_date）
       ├─ 2) 收盘估值（原始 close）
       └─ 3) 生成下一批订单
```

**为什么放在开盘撮合之前**：拆分/合并生效日当天，开盘价已经是调整后的价格。
如果先撮合再调整，会用「新价格 × 旧数量」下错单。

**input_hash 纳入 `corporate_action_version`**：
口径变化必须改变哈希，否则修复前后的结果无法区分。
实测新记录 `input_hash=2ac80bcdfb5459c5`，旧记录 `dbfac114e6900c87`。

## 6. 开关与回归对照

| 配置 | 行为 |
| --- | --- |
| `apply_corporate_actions=True`（默认） | 应用全部 confirmed 事件 |
| `apply_corporate_actions=False` | 完全跳过，退化为修复前口径，用于回归对照 |
| `apply_cash_distributions=False` | 只调份额不记分红，仅用于诊断，不得用于生产 |

测试 `test_no_action_etf_unaffected` 验证：**无公司行为的 ETF，
开关前后净值序列必须完全一致**。

## 7. 数据版本与可追溯

| 项 | 做法 |
| --- | --- |
| 事件版本 | `data_version='ca-v1'`，未来口径变化升版 |
| 事件更新 | `save_action()` 按 `(code, action_type, ex_date)` 更新，`created_at` 保留首次时间，`updated_at` 记录最后修改 |
| 不覆盖历史 | 事件表只增改，不删除；应用记录表永久保留 |
| 回测可追溯 | `corporate_action_applications` 记录每次回测用了哪些事件、影响多少份额与现金 |

## 8. 已知局限

| # | 局限 | 影响 |
| ---: | --- | --- |
| 1 | 分红按除息日入账，不模拟发放日 | 极小机会成本，不影响收益结论 |
| 2 | 零碎股按当日收盘价折现金，非官方规则 | ETF 实际多为整数比例，影响 < 0.02% |
| 3 | 未处理分红所得税 | ETF 对个人免税，当前无影响 |
| 4 | 2005-2019 年历史复权异常未处理 | 不在回测区间内 |
| 5 | 事件数据依赖第三方（天天基金） | 已用券商公告交叉验证 `511030` 一条；其余 165 条只有单一来源 |
| 6 | 不处理基金合同变更导致的比例调整 | 本阶段未发现此类事件 |
