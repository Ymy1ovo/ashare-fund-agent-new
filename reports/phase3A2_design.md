# 阶段3A.2 设计说明：策略可信度验证体系

- 编写时间：2026-11-11
- 范围：只做策略验证，不提高收益、不改数据、不改已有回测引擎

## 1. 开发前现状确认（实测，非推断）

### 1.1 数据库结构

当前 15 张表：`etf_pool`、`etf_daily_prices`、`trade_calendar`、`etf_adjustment_snapshots`、
`adjustment_runs`、`indicator_runs`、`etf_indicator_daily`、`backtest_runs`、
`backtest_daily_nav`、`backtest_orders`、`backtest_trades`、`backtest_positions_daily`、
`sync_runs`、`sync_details`、`data_source_tests`。

### 1.2 数据覆盖

| 项目 | 实测值 |
| --- | --- |
| 行情区间 | 2005-02-23 ~ 2026-11-09 |
| 行情总行数 | 116,609 |
| 交易日历 | 1990-12-19 ~ 2026-12-31，8,797 条 |
| 2021-01-01 ~ 2026-11-09 交易日 | 1,416 |
| 样本内 2021-01-01~2024-12-31 | 969 个交易日 |
| 样本外 2025-01-01~2026-11-09 | 447 个交易日 |
| 2021 起覆盖 ≥95% 的 ETF | **44 只** |
| 覆盖不足 | 513180（1,324 行）、588200（979 行，2022-10 上市） |

### 1.3 现有策略与可复用模块

- `MovingAverageTrendStrategy`：**唯一参数 `ma_window`（默认 20）**，无其他参数。
- `BuyAndHoldStrategy`：支持等权或指定权重。
- `BacktestEngine(config, strategy).run(codes, indicator_version=...)`：已支持指定 ETF、日期区间、策略参数。
- `compute_performance()`：Sharpe/Sortino 已是标准日收益法（阶段3A.1 修正），缺失日不压缩。
- `save_result()`：保存 config_json、input_hash、5 张表记录。
- 指标表已有 `ma5/ma10/ma20/ma30/ma60/ma120/ma250`，可直接供 MA 窗口参数使用。

### 1.4 关键限制（实测确认）

1. **数据库没有独立指数表**。只有 510300（沪深300ETF）、510500（中证500ETF）两只 ETF。
   因此"沪深300指数基准"必须用 **510300 ETF 作为代理**，报告中明确标注差异。
2. **ma_trend 只有一个可调参数 `ma_window`**，不存在提示词中假设的其他参数。
   参数敏感性只能做 MA 窗口网格。
3. 513180、588200 数据不足 2021 起点，验证池需按真实覆盖过滤。

## 2. 实施设计

### 2.1 模块划分

新增 `app/validation/`：

| 模块 | 职责 |
| --- | --- |
| `config.py` | 验证配置、参数网格定义、数据集覆盖判定 |
| `split.py` | 样本内/外时间切分，严格按交易日索引 |
| `walkforward.py` | Walk-Forward 窗口生成与逐窗参数选择 |
| `regime.py` | 市场环境分类（只用当时可获得数据） |
| `sensitivity.py` | 参数网格扫描与稳定性分析 |
| `benchmark.py` | 基准策略构建与区间对齐 |
| `stress.py` | 成本/滑点压力场景 |
| `storage.py` | 验证结果持久化 |
| `report.py` | 统一验证报告生成 |
| `runner.py` | 统一调度入口 |

复用而非重写：`BacktestEngine`、`compute_performance`、`save_result`、`load_bars`、`load_calendar`。

### 2.2 时间切分

```text
样本内 IS：2021-01-01 ~ 2024-12-31   (969 个交易日)
样本外 OOS：2025-01-01 ~ 2026-11-09  (447 个交易日)
```

- 严格按 `trade_calendar` 的真实交易日切分，不按自然日。
- `IS ∩ OOS = ∅`，`IS` 全部早于 `OOS`。
- 预热期：MA 窗口 >= N 时需要 N-1 个历史交易日预热。预热数据**仅用于指标预热**，
  其收益从验证期起点开始计算，不计入验证收益。实现方式：回测起始日 = 验证期起点，
  但指标读取时向前多取 `warmup_days` 用于计算 MA（由 `etf_indicator_daily` 已算好的 ma 列直接提供，
  无需重算，因此不存在"预热期被计入收益"的问题）。
- 参数选择只读 IS，OOS 只做最终验证，代码层面通过 `select_on_is()` 强制分离。

### 2.3 Walk-Forward

- 训练窗（参数选择窗）：**2 年**
- 验证窗：**6 个月**
- 向前滚动步长：**6 个月**（相邻窗口不重叠验证期）
- 每个窗口：在训练窗内跑完整个 MA 网格 → 选 Sharpe 最高（并列时取夏普后按最大回撤更优）→ 在验证窗用该参数跑回测
- 训练窗数据不足或验证窗交易日 < 阈值时标记 `insufficient_data`，不填补

### 2.4 市场环境分类

- 参考标的：**510300 沪深300ETF**（数据库无指数表，明确标注为 ETF 代理）
- 分类规则（只用 T 日及之前数据）：
  ```text
  m_t = 510300 在 T 日的收盘价 / MA250(T) - 1
  m_t >  +5%  → 牛市
  m_t <  -5%  → 熊市
  |m_t| <= 5% → 震荡市
  ```
- MA250 不足 250 个交易日时 → `unclassified`（样本不足，不强行分类）
- 严格滚动窗口，不使用未来数据

### 2.5 参数敏感性

- 网格：`ma_window ∈ {5, 10, 20, 30, 60, 120, 250}`，共 7 组
- 全部在 IS 上跑，OOS 只对 IS 最优参数做一次验证
- 输出：每组的总收益、CAGR、最大回撤、Sharpe、Sortino、交易次数、换手率
- 稳定性：计算 IS 最优参数 ±1 档的表现，若相邻档位收益/夏普大幅衰减则标记过拟合风险
- **报告展示全部组合，不只展示最优**

### 2.6 基准

| 基准 | 构造方式 | 口径说明 |
| --- | --- | --- |
| 买入持有（等权） | `BuyAndHoldStrategy` 对同一 ETF 池 | ETF 原始价成交，含费用与滑点 |
| 沪深300 代理 | 510300 ETF 单只买入持有 | **ETF 而非指数**，含跟踪误差与费用 |
| 中证500 代理 | 510500 ETF 单只买入持有 | 同上 |
| ma_trend | 现有策略 | 同池、同区间、同成本 |

所有基准使用同一 `BacktestConfig`（初始资金、成本、滑点、执行价一致），区间对齐到验证区间。

### 2.7 压力测试

| 场景 | 配置 |
| --- | --- |
| base | 默认 万2.5 佣金 + 5bp 滑点 |
| cost_plus_50 | 佣金 ×1.5、最低佣金 ×1.5 |
| cost_plus_100 | 佣金 ×2、最低佣金 ×2 |
| slippage_x2 | 滑点 5bp → 10bp |
| slippage_x3 | 滑点 5bp → 15bp（"提高两倍"） |
| sparse_data | 剔除数据不足 ETF，只保留完整覆盖池 |
| insufficient | 人为缩短区间至不足 1 年，验证系统正确标记数据不足 |

- 全部为模拟假设，报告明确标注
- **不修改任何历史行情**，只改 `BacktestConfig`

### 2.8 数据库（新增 4 张表，独立迁移）

- `validation_runs`：validation_id、策略、input_hash、ETF 池、参数、区间、配置、状态、摘要
- `validation_windows`：walk-forward 每窗参数与结果
- `validation_grid`：参数网格每格结果
- `validation_stress`：压力场景结果

主键含 `validation_id`，重复运行生成新 id，不覆盖历史。

### 2.9 测试计划

新增 `tests/test_validation.py`，覆盖提示词第七章 14 项要求，
全部使用临时 SQLite + 人工构造数据。

## 3. 分批实施顺序

1. 第一批：`config.py` + `split.py` + 验证基础设施 + 切分测试
2. 第二批：`walkforward.py` + 窗口测试
3. 第三批：`regime.py` + 环境分类测试
4. 第四批：`sensitivity.py` + 参数网格测试
5. 第五批：`benchmark.py` + `stress.py` + 测试
6. 第六批：`storage.py` + `report.py` + `runner.py` + 报告与界面

每批完成后跑相关测试，确认无回归再继续。

## 4. 明确不做

- 不改 `BacktestEngine`、`Broker`、`Portfolio`、`metrics.py`
- 不改 `app/quant/*`
- 不改历史行情、指标、复权快照、历史回测记录
- 不开发新策略，不自动实盘交易
- 不为达成收益目标调整任何参数或区间
