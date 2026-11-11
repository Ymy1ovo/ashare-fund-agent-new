# 阶段2 交付报告：量化指标引擎 V1.0

> 本文件是阶段2历史报告；CAGR/EMA/MACD 的后续修复见 `phase2.1_report.md`。

- 项目：A股基金量化分析 Agent V1.0
- 阶段：2（量化指标引擎 + 阶段1B.1小修复）
- 完成时间：2026-11-09
- 数据库：`data/fund_agent.db`
- 数据源：AKShare（行情、前复权、交易日历）
- 结论：**阶段2验收项已完成；所有 46 只 ETF 已实际计算指标，0 只计算失败。**

## 1. 验收结论

| 验收项 | 实际结果 |
| --- | --- |
| 1B.1 退出码修复 | success=0、partial=2、failed=1；原始/复权状态分开记录 |
| 原始行情未被修改 | 通过；复权一致性检查哈希未变化 |
| 前复权 OHLC 口径统一 | 通过；统一因子生成 adjusted_open/high/low，含价格关系校验 |
| 缺失行情处理 | 缺失复权价、日历缺口、零成交量分别标记，不填充 |
| 第一批指标 | 收益、趋势、动量、波动/回撤、ATR、风险收益全部实现 |
| 指标版本可追踪 | `calculation_version` + 参数哈希 + `run_id` |
| 复权快照可追踪 | 每行记录 `adjustment_snapshot_id`；混用拒绝 |
| 未来函数测试 | 修改 T 日后行情，T 日及之前指标逐行一致 |
| 指标数据库 | `indicator_runs`、`etf_indicator_daily`，主键 UPSERT |
| API | 详情、最新、overview、ranking 实际 200 |
| Streamlit | 主看板 + 指标页 AppTest 0 异常 |
| 原功能回归 | 82 项测试全部通过 |
| 46 只 ETF 实际计算 | 46 只均完成；26 success、20 partial、0 failed |
| 数据不足标记 | 通过；250 日/252 日窗口和真实缺口返回空值并报告覆盖率 |
| 伪造数据 | 未使用模拟行情冒充真实行情；测试数据仅用于离线测试 |

## 2. 阶段1B.1小修复

### 问题

- `refresh_adjusted_prices.py` 只检查 failed/empty，忽略 partial，返回 0。
- `sync_data.py` 只按原始+复权 failed/empty 判断，复权 partial 被误报为整体成功。
- 没有区分原始同步状态和复权刷新状态。

### 修复

新增 `app/data/processors/task_status.py`：

- success → 0
- partial → 2
- failed → 1

`refresh_adjusted_prices.py`、`sync_data.py`、`ingest_history.py` 全部使用统一状态函数；`sync_data.py` 新增 `sync_combined_summary.json`，同时保存 raw、adjustment、overall 状态和各类数量。

测试覆盖：全部成功、部分失败、空数据、全部失败、原始成功+复权 partial、复权失败不被忽略。

## 3. 统一价格口径

新增 `app/quant/price_adjustment.py`：

```text
factor = adjusted_close / raw_close
adjusted_open/high/low = raw_open/high/low × factor
adjusted_close = 数据库已有值
```

- `raw_close>0`、`adjusted_close>0`、因子有限正数。
- 原始和转换后 OHLC 均校验价格关系；浮点舍入使用 1e-6 容差。
- 同一 ETF 只允许一个快照 ID；多快照直接抛错。
- 原始 OHLC 不写回。
- 零成交量和成交量缺失分开标记；不把停牌/无成交混同数据缺失。
- 交易日历来自 `trade_calendar`，非交易日不进入缺失判断。

实际结果：116,609 条原始行情未改动；指标层增加 155 条交易日历缺口占位行，共 116,764 行。

## 4. 指标模块

新增：

- `returns.py`：1/5/10/20/60/120/250 日收益、扩展 CAGR
- `trend.py`：MA5/10/20/30/60/120/250、EMA12/26
- `momentum.py`：Wilder RSI6/12/24、MACD(12,26,9)
- `volatility.py`：20/60/120 日年化波动率、20/60/120 日及扩展最大回撤、ATR14
- `risk.py`：滚动 252 日夏普/索提诺/Calmar；区间摘要
- `engine.py`：统一调度、快照拒绝、日历索引、质量报告
- `validation.py`：行级质量与指标覆盖率
- `config.py`：默认参数、参数哈希、指标版本

完整公式与口径见 `reports/phase2_formula_spec.md`。

## 5. 实际计算

- 命令：`python scripts/calculate_indicators.py --all --full-rebuild`
- ETF 数：46
- 状态：success 26 / partial 20 / failed 0
- 指标行：116,764
- 指标版本：`v1.0.0-30b821a1af15`
- 计算耗时：约 48 秒（46 只，全历史）
- 当前快照：46 只均非 stale

### 指标覆盖率（全部 116,764 行）

| 指标 | 覆盖率 |
| --- | ---: |
| return_1d | 99.58% |
| return_20d | 97.70% |
| return_60d | 94.96% |
| return_250d | 83.72% |
| ma20 | 97.77% |
| ma60 | 95.02% |
| ma250 | 83.78% |
| rsi6 | 98.94% |
| rsi12 | 98.33% |
| rsi24 | 97.39% |
| macd_dif/dea/hist | 99.01% / 98.70% / 98.70% |
| volatility_20d | 97.70% |
| volatility_60d | 94.96% |
| volatility_120d | 91.31% |
| max_drawdown_20d | 97.77% |
| max_drawdown_60d | 95.02% |
| max_drawdown_120d | 91.37% |
| max_drawdown_all | 99.74% |
| atr14 | 98.25% |
| sharpe/sortino/calmar | 均为 83.60% |

覆盖率低于 100% 的原因：上市初期历史不足、250/252 日窗口未满、155 条交易日历缺口、149 条复权价缺失。没有用 0 或前值填充。

完整逐指标、逐 ETF 表见 `reports/phase2_indicator_quality.md`。

## 6. 数据质量问题

行质量统计：

- valid：116,416
- warning：44（全部为零成交量）
- invalid：304

invalid 构成：

- 复权价缺失：149 条（510050 108 条、510880 41 条）。
- 交易日历缺口：155 条（无实际行情行）。
- 合计 304 条。

逐 ETF 部分覆盖：

| 类型 | ETF |
| --- | --- |
| 复权价缺失 | 510050（108）、510880（41） |
| 交易日历缺口 | 159901、159915、159936、159972、510150、510500、511030、511220、511260、512010、512100、512170、512480、512690、512890、513030、513100、513500 |
| 零成交量 | 511030（42）、511220（2） |

- 零成交量不判为价格无效，保留原始数据并标记 `zero_volume`。
- 510050/510880 的缺失复权价不猜测、不填旧基准。
- 20 只 `partial` 是数据质量状态，不是计算失败。

## 7. 数据库

新增表：

- `trade_calendar`：8,797 个真实交易日（1990-12-19 ~ 2026-12-31）。
- `indicator_runs`：每次计算任务、参数、快照、状态、有效/缺失行、摘要、质量。
- `etf_indicator_daily`：每日指标，主键 `(etf_code, trade_date, calculation_version, adjustment_snapshot_id)`。

版本规则：

- `calculation_version = v1.0.0 + 参数哈希`。
- 相同版本/快照重复计算 UPSERT，不重复插入。
- 参数变化生成新版本，旧版本保留。
- 快照更新后旧指标保留，API 标记 `stale=true`。
- 迁移通过 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN`，不删除行情。

## 8. API

新增：

- `GET /api/indicators/{etf_code}?start_date=&end_date=&indicators=&version=`
- `GET /api/indicators/{etf_code}/latest`
- `GET /api/indicators/overview`
- `GET /api/indicators/ranking?metric=&order=&limit=&version=`

实际冒烟：

- `/api/indicators/overview`：200，46 只，stale=0。
- `/api/indicators/510300?...`：200，6 行，status=success，snapshot=110，stale=false。
- `/api/indicators/ranking?metric=return_20d`：200，5 条。

错误处理：未知 ETF、非法日期、非法指标、未计算、版本不存在、过期快照均明确返回；ranking 带“不构成投资建议”声明。

## 9. Streamlit

- 主看板：行情、快照、同步、质量，AppTest 0 异常。
- 新增 `dashboard/pages/2_量化指标.py`：
  - ETF、日期区间、指标版本选择；
  - 概览、收益、趋势、动量、波动与回撤、数据质量六标签页；
  - 展示快照 ID、快照是否过期、指标版本、质量原因、覆盖率；
  - 图表读取真实 SQLite 指标，不生成模拟行情。

## 10. 测试

- 测试文件：82 项。
- 结果：**82 passed，0 failed**，约 10.10 秒。
- 关键新增：价格口径 9 项、公式 10 项、引擎 8 项、任务状态 9 项、指标 API 2 项。
- 未来函数测试：修改 T 日之后行情后，T 日及之前指标逐行一致。
- 全部测试使用临时 SQLite，不改正式库。
- 详细见 `reports/phase2_test_report.md`、`reports/phase2_api_test.md`。
- 实际全池命令因 20 只 partial 返回退出码 2；这是数据质量状态，不是计算失败，46 只均产出了指标。
- 交付 ZIP：`dist/Ashare-Fund-Agent_phase2_20261109.zip`

## 11. 实际运行命令

```powershell
cd D:\ymy\jj-agent
.\.venv\Scripts\Activate.ps1

python scripts\sync_trade_calendar.py
python scripts\calculate_indicators.py --all --full-rebuild
python scripts\indicator_quality_report.py
python scripts\data_quality_report.py
python -m pytest -v
python scripts\smoke_test_servers.py
python scripts\package_release.py
```

## 12. 修改/新增文件

### 修改

- `app/database/db.py`：指标表、交易日历表、指标列迁移、count 白名单
- `app/data/collectors/worker.py`、`akshare_collector.py`：交易日历采集
- `app/main.py`：指标 API、health 指标计数
- `scripts/refresh_adjusted_prices.py`、`sync_data.py`、`ingest_history.py`：统一退出码/组合状态
- `README.md`、`scripts/package_release.py`、`scripts/smoke_test_servers.py`
- `tests/test_database.py`、`test_database_migration.py`、`test_api_market_data.py` 等回归适配
- `migrations/phase2_indicators.sql`：新增指标表/交易日历迁移说明

### 新增

- `app/data/processors/task_status.py`
- `app/quant/config.py`、`price_adjustment.py`、`returns.py`、`trend.py`、`momentum.py`、`volatility.py`、`risk.py`、`validation.py`、`engine.py`
- `app/database/indicators.py`
- `scripts/sync_trade_calendar.py`、`calculate_indicators.py`、`indicator_quality_report.py`
- `dashboard/pages/2_量化指标.py`
- `tests/test_task_status.py`、`test_price_adjustment.py`、`test_indicator_formulas.py`、`test_indicator_engine.py`、`test_api_indicators.py`
- `reports/phase2_formula_spec.md`、`phase2_indicator_quality.md`、`phase2_test_report.md`、`phase2_api_test.md`、`phase2_report.md`

## 13. 未完成事项

- 未开发策略信号、回测交易、自动交易；本阶段只做指标。
- 未用分红公告独立重算复权因子；仍采用 AKShare qfq 口径。
- 未实现跨数据源复核。
- 未做后复权落地表。
- 20 只 ETF 的 `partial` 来自真实数据缺口，未通过删除异常样本或填充来提高成功率。
- 指标公式未与商业终端逐项对拍。

## 14. 是否建议进入阶段3

建议进入阶段3的**方案设计**，但前提是：

1. 项目负责人确认当前指标口径与缺失数据策略；
2. 先明确策略/回测使用的复权快照固定规则；
3. 对 20 只 partial ETF 决定是否接受缺口，或补充数据源；
4. 阶段3先做单因子/组合验证，不直接进入实盘。

本轮不开始阶段3，等待验收。
