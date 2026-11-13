# 阶段3A.3.2.1 现金分红入账时点修复

- 生成时间：2026-11-13
- 上一阶段：3A.3.2（`0916b21551ff69f6ed3380137802beb7694022a9`）
- 性质：**账本修复说明**。核查见 `phase3A3_2_1_evidence_quality_report.md`。

## 1. 上一阶段的缺陷

3A.3.2 对拆分和现金分红**套用了同一条规则**：都在「下一交易日」应用。

`scripts/seed_corporate_actions.py`：

```python
def build_events(raw, conn):
    for item in info["splits"]:
        eff = _next_trading_day(conn, item["date"])       # 份额折算日 → 次一交易日
    for item in info["dividends"]:
        eff = _next_trading_day(conn, item["ex_date"])    # 除息日 → 次一交易日  ← 错误
```

### 后果

现金分红在**除息日之后一天**才计入现金，而价格在除息日当天就已经除息下跌：

| 日期 | 价格 | 现金 | 账面总资产 | 问题 |
| --- | ---: | ---: | ---: | --- |
| 除息日 | 已下跌 | 未增加 | **凭空减少** | 虚假日亏损 |
| 次日 | 已恢复 | 增加 | 恢复 | 补回，但时点错 |

实测 `510300` 2021-01-19 除息（每份 0.072 元）：

- 修复前：当日收益 **−1.343%**
- 修复后：当日收益 **−0.054%**

而且影响不止净值：**除息日收盘后生成的订单会把不存在的现金当成可用资金**。

## 2. 核查：除息日价格调整确实发生在 ex_date

用「原始收益 vs 复权收益」的差额定位复权调整发生在哪一天，
对 121 条分红事件逐条判定：

| 判定 | 数量 |
| --- | ---: |
| 复权调整发生在 `ex_date` 当天 | **113** |
| 复权调整发生在 `ex_date` 次一交易日 | 8 |
| 无法判定 | 0 |

8 条「次一日」集中在 2009-2016 年的老数据，
属于历史复权因子按周对齐的遗留问题，**不影响回测区间**（2021 起全部为 `ex_date` 当天）。

结论：**价格在除息日当天调整，现金必须在同一天确认经济权益。**

## 3. 采用的会计模型

采用「**应收分红 + 发放日到账**」两段式，而不是简单的「除息日加现金」：

```
除息日（ex_date）
    ├─ 价格除息下跌              ← 市场行为，无需干预
    └─ 确认应收分红              ← dividend_receivable 增加，cash 不变
       金额 = 权益登记日收盘持仓 × 每份分红

发放日（pay_date）
    └─ 应收转现金                ← dividend_receivable 减少，cash 等额增加
```

### 3.1 为什么不用「除息日直接加现金」

| 做法 | 问题 |
| --- | --- |
| 除息日直接加现金 | 违反实际结算规则：ETF 分红通常在 T+3~T+7 到账，期间这笔钱不能用于交易。若当作可用现金，会在除息日当天买入本不该买得起的标的 |
| 发放日才确认 | 除息日价格已跌、权益未记，制造虚假亏损（就是 3A.3.2 的问题） |
| **应收 + 到账（本阶段）** | 除息日经济价值连续（应收计入总资产），但现金不可交易；发放日才变成可用资金 |

### 3.2 总资产恒等式

```
total_assets = cash + market_value + dividend_receivable
```

- `cash`：**可用**现金，可用于下单
- `dividend_receivable`：已确认未到账，计入总资产但**不能下单**
- 每日快照新增 `dividend_receivable` 字段

## 4. 权益登记日份额锁定

分红金额按「**权益登记日收盘时登记在册的份额**」计算，不是除息日持仓。

若在登记日与除息日之间买卖，用除息日持仓会算错。
因此在 `record_date` 收盘后、估值快照之前锁定份额：

```python
# engine.py 主循环
self._capture_dividend_shares(trade_date, record_index, portfolio)   # 登记日收盘锁定
total = portfolio.total_assets(prices)
snapshot = portfolio.snapshot(...)
```

锁定时点很关键：
- 必须在**当日成交完成之后**（登记以收盘后结果为准）
- 必须在**估值快照之前**（否则当日快照用的是旧份额）

实测：`510300` 2021-01-18 登记日锁定 180,200 份，除息日确认 180,200 × 0.072 = 12,974.40 元。

## 5. 拆分/合并继续按官方生效日

**没有**把拆分改成和分红一样的规则：

| 类型 | 索引日期 | 依据 |
| --- | --- | --- |
| 拆分 / 合并 | `effective_date`（官方公告的「恢复交易首日」） | 份额在拆分日变更登记，次一交易日复牌并按新份额交易 |
| 现金分红 | `ex_date`（除息日）确认 + `pay_date` 到账 | 价格在除息日调整，现金在发放日到账 |

`511030` 2021-01-08 拆分（1:10）：
- 权益登记日 2021-01-07
- 份额拆分日 2021-01-08（当日停牌）
- **恢复交易 2021-01-11** ← 引擎在 2021-01-11 应用

## 6. 非交易日映射

| 事件类型 | 规则 |
| --- | --- |
| 拆分 / 合并 | `effective_date` 必须落在交易日；若不是（数据异常），引擎当日跳过并在 notes 留痕 |
| 现金分红 · 应收确认 | `ex_date` 必须是交易日；不是则顺延至下一个交易日确认 |
| 现金分红 · 到账 | `pay_date` 不是交易日时，按 `pay_date <= 当日` 判定，即在**下一个交易日**开盘前到账 |

`settle_dividend_receivable(on_date)` 用 `pay_date <= on_date` 判定，
天然处理跨周末、跨节假日。

## 7. 同一事件不重复入账

三道防线：

1. `corporate_actions` 表 `UNIQUE(code, action_type, ex_date)`
2. `corporate_action_applications` 表 `UNIQUE(run_id, action_id)`
3. `Portfolio.confirm_dividend_receivable` 用 `action_id` 标识，
   同一 action_id 在同一 run 内只会确认一次

测试 `test_same_action_applied_twice_raises` 覆盖第 2 道。

## 8. 修复前后对照（真实数据）

`510300` 2021-01-15 ~ 2021-01-25，初始资金 100 万，满仓买入：

| 日期 | 修复前现金 | 修复前总资产 | 修复后现金 | 修复后应收 | 修复后总资产 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021-01-15 | 402.14 | 996,187.34 | 402.14 | 0 | 996,187.34 |
| 2021-01-18（除息） | 402.14 | **993,844.74** | 402.14 | **12,974.40** | **1,006,819.14** |
| 2021-01-19 | 402.14 | 980,329.74 | 402.14 | 12,974.40 | 993,304.14 |
| 2021-01-20 | 402.14 | 985,735.74 | 402.14 | 12,974.40 | 998,710.14 |
| 2021-01-21（发放） | 402.14 | 1,002,674.54 | **13,376.54** | 0 | **1,015,648.94** |

## 9. 新增测试（13 项）

| 场景 | 测试 | 结果 |
| --- | --- | :---: |
| 除息日价格下跌，经济价值连续 | `test_cash_distribution_increases_cash` | ✅ |
| 除息日应收分红正确 | `test_dividend_receivable_not_available_cash` | ✅ |
| 发放日前分红不是可用现金 | `test_dividend_receivable_not_available_cash` | ✅ |
| 发放日现金正确转入可用现金 | `test_cash_distribution_increases_cash` | ✅ |
| 除息日收盘后订单不得用未到账分红 | `test_order_after_ex_date_cannot_use_unsettled_dividend` | ✅ |
| 除息日与发放日跨周末 | `test_dividend_across_weekend_pay_date` | ✅ |
| 除息与到账之间发生其他交易 | `test_trades_between_ex_and_pay_do_not_change_receivable` | ✅ |
| 无持仓不产生分红 | `test_no_position_no_dividend` | ✅ |
| 同一事件不重复确认 | `test_same_action_applied_twice_raises` | ✅ |
| 应收 + 现金 + 市值 == 总资产 | `test_receivable_cash_total_identity` | ✅ |
| 缺发放日必须被拒 | `test_dividend_requires_pay_date` | ✅ |
| 拆分与分红同日（顺序正确） | `test_split_and_distribution_same_day` | ✅ |
| 多批次份额调整 | `test_multi_lot_split_keeps_lot_sum` | ✅ |

全部走完整 Engine + Broker + Portfolio + 估值链路。

## 10. 已知局限

| # | 局限 | 影响 |
| ---: | --- | --- |
| 1 | 发放日按官方公告的「现金红利发放日」字面使用 | 实际到账可能有 1 日银行延迟，回测不模拟 |
| 2 | 未到账分红不计利息 | 影响可忽略（占比 < 0.1%） |
| 3 | 登记日锁定用「当日收盘持仓」 | 若当日有成交，以成交后份额为准，符合实际登记规则 |
| 4 | 8 条 2009-2016 历史分红复权调整晚一天 | 不在回测区间内 |
