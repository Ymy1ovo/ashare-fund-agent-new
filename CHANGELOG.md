# 变更日志

## 2026-11-11 — 阶段3A.1.1 部分成交状态专项修复

- 新增 `Order.sync_status()` 作为唯一状态收敛入口：有成交只能是 `filled` / `partial`，
  `rejected` / `expired` / `unfilled` / `cancelled` 只对零成交订单生效。
- 修复 Broker 已把剩余部分设为 `rejected` 后，Engine 因 `status not in ("rejected",)`
  跳过修正、导致「有成交却标 rejected」的问题。
- Broker 新增 `_defer()` / `_terminate()`，已完成订单在 `execute()` 入口直接拦截，
  不重复成交、不重复扣费。
- Engine 撮合后状态收敛统一走 `sync_status()`；缺失行情分支保留已有成交的 `partial`。
- 修正 2 个原有测试的错误断言，新增 10 项部分成交专项测试，`test_backtest_partial_fill.py` 由 8 项增至 18 项。
- 全量测试 144 → 154 项，全部通过。
- 新增专项报告 `reports/phase3A1_1_partial_fill_fix_report.md`。

## 2026-11-10 — 阶段3A.1 回测验收问题修复

- Sharpe/Sortino 改用日均超额收益年化，CAGR 独立计算。
- 缺失行情：缺口当日与次日日收益置 NaN，只统计持仓 ETF。
- 部分成交：保留 partial，新增 `remaining_quantity`，剩余续挂或明确取消。
- 新增迁移 `migrations/phase3a1_backtest_partial_fill.sql`。
- 新增测试 17 项，全量 144 passed。
- 新增报告：`phase3A1_report.md`、`phase3A1_test_report.md`、`phase3A1_risk_comparison.md`、`phase3A1_manual_case.md`。

## 2026-11-10 — 阶段3A 历史回测引擎 V1.0

- 新增 `app/backtest/` 完整回测架构：配置、模型、行情读取、成本、执行、撮合、账本、引擎、绩效、报告、持久化、策略。
- 严格 T+1：T 日收盘信号最早 T+1 开盘成交；停牌/零成交/涨跌停不虚构成交，延期或过期。
- 价格口径：成交与估值只用原始 OHLC；前复权价仅用于信号，不混用、不重复计分红。
- 账本：FIFO 批次、现金约束、每日总资产核对、期末现金独立推演。
- 成本：佣金（含最低佣金）、比例/固定滑点、可选印花税与过户费；ETF 规则按类别配置。
- 新增 5 张表：`backtest_runs`、`backtest_daily_nav`、`backtest_orders`、`backtest_trades`、`backtest_positions_daily`。
- 新增 API 6 个：`/api/backtests` 列表、详情、净值、成交、订单、持仓。
- 新增 `scripts/run_backtest.py` 与 Streamlit「回测结果」页面。
- 新增测试 31 项，全量 127 passed。
- 新增报告：`phase3A_design.md`、`phase3A_report.md`、`phase3A_test_report.md`、`phase3A_backtest_case.md`。

## 2026-11-09 — 阶段2.2 与交付打包规范

- 修复区间风险摘要缺失交易日压缩：
  - `summarize_range()` 在原始交易日索引上使用 `pct_change(fill_method=None)`。
  - 波动率、夏普、索提诺只使用真实相邻日收益。
  - 最大回撤使用有效价格观察序列，不填充缺失价格。
  - 摘要和 `compute_risk()` 共用 `daily_return_series()`。
- 指标引擎版本 `v1.0.2-30b821a1af15`；旧版本 v1.0.0/v1.0.1 保留。
- 46只ETF重新计算：26 success、20 partial、0 failed。
- 新增交付打包规范：
  - `source-only`：轻量源码包，不含数据库和日志。
  - `data-snapshot`：SQLite 一致性备份、完整性检查、独立快照包。
  - `full-release`：源码包 + 数据库快照包 + 测试/质量报告 + 变更说明。
- 新增 `scripts/package_project.py`，输出 ZIP SHA256 和 manifest。
