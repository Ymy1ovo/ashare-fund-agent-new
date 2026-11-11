# 阶段3A 设计说明：A股 ETF 历史回测引擎 V1.0

- 项目：A股基金量化分析 Agent V1.0
- 阶段：3A
- 日期：2026-11-10
- 目标：建立可复现、无未来函数、计入真实交易成本的回测基础设施；不追求高收益，不做参数优化，不接实盘。

## 1. 现有可复用资源

| 资源 | 位置 | 用途 |
| --- | --- | --- |
| 原始 OHLC + 成交量 | `etf_daily_prices` | 成交价格、可交易性判断、持仓估值 |
| 前复权收盘 | `etf_daily_prices.adjusted_close` | 信号指标（MA/动量） |
| 调整快照 | `etf_adjustment_snapshots` | 记录每次回测使用的复权口径 |
| 交易日历 | `trade_calendar`（1990-12-19 ~ 2026-12-31） | 回测日历、缺口识别 |
| 指标日表 | `etf_indicator_daily`（v1.0.0/1/2） | 可作为信号输入，不重复计算 |
| ETF 池与分类 | `etf_pool.category` | 交易规则分类 |
| 风险函数 | `app/quant/risk.py`、`volatility.py` | 复用收益率/回撤口径原则 |

不重复实现阶段2指标；不修改阶段1/2已验收逻辑。

## 2. 架构

```text
app/backtest/
├─ config.py        回测参数、成本参数、ETF 交易规则
├─ models.py        订单/成交/批次/持仓/每日快照
├─ data.py          DB 读取、日历对齐、可交易性判定
├─ costs.py         佣金、最低佣金、滑点
├─ execution.py     成交价、涨跌停、T+0/T+1、整手
├─ broker.py        撮合：成交/拒绝/延期/部分成交
├─ portfolio.py     现金与持仓账本（FIFO 批次）
├─ engine.py        主循环、信号→目标权重→订单
├─ metrics.py       绩效统计
├─ report.py        Markdown 报告
├─ storage.py       回测记录持久化
└─ strategies/      base / buy_and_hold / ma_trend
```

## 3. 交易时序（严格 T+1）

```text
T 日收盘后：
  1. 读取截至 T 日（含）的行情与指标
  2. 策略计算目标权重（只用 <= T 的数据）
  3. 生成订单，signal_date = T，最早可执行日 = T+1
T+1 日开盘：
  4. 撮合昨日及以前挂起的订单（顺序固定：signal_date, seq, code）
  5. 成交价默认 = 当日原始 open（可配置 close）
T+1 日收盘：
  6. 按原始 close 估值，生成每日净值
  7. 再用 T+1 数据生成下一批信号
```

- 不允许“T 日收盘信号按 T 日收盘价成交”。
- 若 T+1 无有效行情/停牌/成交量为 0/价格非法/涨跌停不可成交，订单延期，超过 `max_defer_days` 过期并记录原因。
- 同一日订单顺序确定（按 signal_date、seq、code），保证可复现。

## 4. 价格口径与公司行为

**成交价与估值只用原始 OHLC**：`open/high/low/close/volume`。前复权价格只用于信号。

**不做分红再投资，也不伪造分红记录**：

- 当前数据库没有可靠的分红/拆分/份额变动事件表，无法逐笔还原公司行为。
- 因此回测按“价格收益”口径：持仓按原始收盘价估值，不额外计入现金分红。
- 这会**低估**含分红策略的实际总收益，属于已知限制，明确写入报告，不用虚构数据弥补。
- 由于只使用原始价格，不存在“复权收益 + 现金分红”重复计入的问题。

**复权快照记录**：每次回测记录每只 ETF 使用的 `adjustment_snapshot_id` 与指标版本。若某 ETF 历史行存在多个快照，拒绝回测并报错（与阶段2一致）。

**信号口径限制**：前复权序列含“未来分红导致的历史价格调整”。本阶段使用单一快照，属于口径一致性问题而非未来函数；报告中记录快照版本，便于复核。

## 5. ETF 交易规则

规则按 `etf_pool.category` 配置，可被单只代码覆盖，也可标记为“未确认”。

| 类别 | T+N | 最小单位 | 涨跌幅 | 说明 |
| --- | --- | ---: | ---: | --- |
| 宽基指数ETF | T+1 | 100 | 10% | 股票型 |
| 科技成长ETF | T+1 | 100 | 10% | 588xxx 覆盖为 20% |
| 消费与医药ETF | T+1 | 100 | 10% | 股票型 |
| 跨境ETF | T+0 | 100 | 10% | 当日可回转 |
| 债券ETF | T+0 | 100 | 10% | 保守上限 |
| 黄金ETF | T+0 | 100 | 10% | 商品类 |
| 商品ETF | T+0 | 100 | 10% | 保守上限 |
| 未知类别 | T+1 | 100 | 10% | 保守默认，标记 unconfirmed |

- 佣金默认万2.5、最低 5 元、滑点 5bp，均可配置。
- ETF 免印花税，不计过户费。
- 涨跌停用保守判定：买入价达到上限视为不可买，卖出价达到下限视为不可卖。
- 未确认的规则会写入回测记录并提示，不假装已准确支持。

## 6. 资金与持仓账本

- 持仓按 FIFO 批次记录：每笔买入生成批次（数量、成本价、日期、冻结到何时、分摊费用）。
- 卖出按 FIFO 消耗批次，逐批计算已实现盈亏与持有天数。
- T+1 标的当日买入的份额当日不可卖；T+0 标的当日可卖。
- 约束：不允许负现金；买入前校验现金，不足则按整手缩减，缩减为 0 则拒单；卖出不得超过可用份额。
- 每日核对：`总资产 = 现金 + Σ(份额 × 当日原始收盘)`；并用“期初现金 + 累计现金流 - 费用”做独立校验。

## 7. 绩效指标

- 总收益率、CAGR（按阶段2.1：交易日索引跨度，不用自然日）
- 年化波动率、Sharpe、Sortino：只用“当天所有持仓均有有效报价”的完整日收益，缺失日保留 NaN（阶段2.2 原则）
- 最大回撤：有效净值序列的峰值/谷值
- 胜率、盈亏比：按卖出批次的已实现盈亏
- 交易次数、换手率、总交易成本、平均持仓天数、资金使用率、年度收益
- 无风险利率可配置，默认 0

## 8. 数据隔离与版本

新增表（独立迁移，不破坏原表）：

- `backtest_runs`：回测 ID、策略名/版本、参数 JSON、初始资金、起止日期、ETF 池、指标版本、快照 ID、成本配置、输入哈希、结果摘要、创建时间
- `backtest_daily_nav`：每日现金、市值、总资产、净值、当日收益、净值状态
- `backtest_orders`：订单全字段（信号日、下单日、成交日、数量、价格、状态、原因）
- `backtest_trades`：成交明细、费用、滑点、已实现盈亏
- `backtest_positions_daily`：每日持仓快照

相同输入 + 相同参数 → 相同 `input_hash`；重复运行不覆盖历史记录。

## 9. 已知限制（实现前即明确）

1. 无分红/拆分事件表：回测是价格收益口径，低估分红贡献，不伪造。
2. 无逐笔成交与盘口：成交价用开盘价或收盘价，滑点用固定 bp 近似。
3. 无冲击成本模型：大额订单不会自动恶化价格。
4. 涨跌停判定为保守近似，不模拟排队与部分成交的真实概率。
5. 前复权快照是当前版本，不代表历史时点已知信息。
6. 不支持融资融券、T+0 以外的日内交易、期权、组合申赎套利。
7. 不接券商接口，纯离线模拟。

## 10. 验收测试计划

人工构造数据覆盖：初始净值、买入/卖出账本、费用、滑点、现金不足、超卖、T+1 时序、无未来函数、停牌/零成交、缺失行情、每日资产核对、最大回撤、Sharpe/波动率缺失、多 ETF 调仓、同日多单顺序、重复运行一致、参数版本区分。

所有测试使用临时 SQLite，不污染正式库。


---

# 阶段3A.1 设计修订（2026-11-10）

阶段3A 独立审查发现三个问题，本轮只做针对性修复，不改架构。

## 修订1：Sharpe / Sortino 口径

**原实现**：`Sharpe = (CAGR - rf) / 年化波动率`，分子是多年复合年化收益，与分母的单期波动率量纲不一致。

**现实现**：

```text
daily_rf   = (1 + risk_free_rate) ^ (1 / annualization) - 1
excess_t   = r_t - daily_rf                     # 只用可用日收益
Sharpe     = mean(excess) × annualization / (std(r, ddof=1) × sqrt(annualization))
           = mean(excess) × sqrt(annualization) / std(r, ddof=1)
下行波动率 = sqrt(mean(min(excess_t, 0)^2)) × sqrt(annualization)
Sortino    = mean(excess) × annualization / 下行波动率
```

- CAGR 单独计算，仍用交易日跨度（阶段2.1 口径），不再参与 Sharpe/Sortino。
- `std=0`、样本 < 2、分母非有限 → 返回 None，不输出 inf。
- 报告中同时输出 `mean_daily_return`、`daily_rf`、`mean_daily_excess`、`downside_deviation`、`risk_sample_days`，便于复核。

## 修订2：缺失行情对日收益的污染

**问题**：Engine 在缺行情时沿用上一有效收盘估值并标记 `stale_price`，但原绩效统计仍把估值变动当成正常单日收益。

**现实现**（`risk_return_series()`）：

- 缺口判定只看**当日实际持仓数量 > 0** 的 ETF；未持仓 ETF 缺行情不影响组合。
- 缺口当日 → `return_status = held_price_gap`，该日收益置 NaN。
- 缺口次日 → `return_status = prior_day_price_gap`，同样置 NaN（避免跨缺口收益压缩成单日）。
- 估值净值序列（含 stale）仍保留，最大回撤用它计算，但报告标注 `nav_days_with_price_gaps` 与 `gap_return_days_excluded`。
- 无持仓日按实际净值变化（通常为 0）计入，不受影响。

## 修订3：部分成交状态与剩余数量

**问题**：Engine 在成交后统一覆盖为 `filled`，部分成交被抹掉。

**现实现**：

- `Order.remaining_quantity = max(0, quantity - filled_quantity)`，入库新增 `remaining_quantity` 列。
- Broker 在动账本**之前**夹紧数量：`quantity = min(quantity, remaining_before)`，累计成交量永不超过原始订单量。
- 只有 `filled_quantity >= quantity` 才是 `filled`，否则严格 `partial`。
- 剩余部分：`max_defer_days > 0` 时继续挂到下一交易日；否则标记 `remainder_cancelled`。
- 已部分成交的订单即使剩余被拒/过期，状态仍为 `partial`（`remainder_rejected` / `max_defer_exceeded`），不降级为 `rejected`。
- 费用只按实际成交金额计算。
- 迁移：`migrations/phase3a1_backtest_partial_fill.sql`（新增列 + 回填 + 索引），幂等执行。

## 新增/修改文件

- 修改：`app/backtest/metrics.py`、`broker.py`、`engine.py`、`models.py`、`storage.py`、`report.py`
- 修改：`app/database/db.py`（幂等加列与索引）
- 新增：`migrations/phase3a1_backtest_partial_fill.sql`
- 新增：`tests/test_backtest_risk_fix.py`、`tests/test_backtest_partial_fill.py`
- 新增：`scripts/compare_phase3a1.py`
- 新增报告：`phase3A1_risk_comparison.md`、`phase3A1_manual_case.md`、`phase3A1_test_report.md`、`phase3A1_report.md`
