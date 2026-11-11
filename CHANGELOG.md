# 变更日志

## 2026-11-11 — 阶段3A.2.1 验证体系缺陷整改

- 修复市场环境分类缺少 OOS 前预热数据：额外加载 OOS 前全部历史交易日（实测 3,064 天）
  做 MA250 预热，预热数据不进入输出、不计入 OOS 绩效。OOS `unclassified` 从 246 天降到 0 天。
- 新增 `app/validation/fingerprint.py`：`market-fingerprint-v2`，覆盖
  code / trade_date / open / high / low / close / volume / amount / adjusted_close /
  adjustment_snapshot_id 十个字段，按 (code, trade_date) 排序后 SHA256，
  算法版本纳入 `input_hash`。
- 数据类压力测试落到实跑：
  - `sparse_data`：SQLite backup 生成独立副本，删除零散 4,047 行 + 连续缺失 32 行，
    源库零写入；447 天中 270 天有效日收益、176 天缺口，状态 success。
  - `insufficient`：截取 41 个交易日（低于 120 阈值），引擎算出的 Sharpe/CAGR 被隐藏，
    状态 insufficient，不再标记 skipped。
- `regime_stats()` 重写：输入改为保留 NaN 的原始交易日序列，逐环境统计
  total_days / valid_days / missing_days，不再有压缩跨缺口收益的空间。
- 新增 `tests/test_validation_fix.py` 40 项测试，全量 209 → 249 项，全部通过。
- 新增 `regime_ma_window`、`min_validation_days` 配置项。
- 无数据库迁移；历史 validation 记录、行情、指标、复权快照、历史回测全部保留。
- 新增报告：`phase3A2_1_design.md`、`phase3A2_1_test_report.md`、`phase3A2_1_validation_report.md`。

## 2026-11-11 — 阶段3A.2 策略可信度验证体系

- 新增 `app/validation/`：配置、切分、Walk-Forward、市场环境、参数敏感性、基准、压力、存储、报告、调度共 11 个模块。
- 新增 `migrations/phase3a2_validation.sql`：`validation_runs`、`validation_windows`、`validation_grid`、`validation_stress` 四张表，全部 `CREATE TABLE IF NOT EXISTS`。
- 新增 `scripts/run_validation.py`、`scripts/smoke_validation_api.py`。
- 新增 `dashboard/pages/4_策略验证.py` 看板页。
- 新增 `/api/validations`、`/api/validations/{id}` 两个接口。
- 新增 `tests/test_validation.py` 55 项测试，全量 154 → 209 项，全部通过。
- 实际运行代表性池（6 只）与全池（41 只）两次验证：
  - 代表性池 `5ec77faf42d64162`：结论「不通过」，样本内 0/7 组合正收益。
  - 全池 `e725034e46ff47e5`：结论「有条件通过」，样本外 Sharpe 0.7637、收益 30.71%。
- 关键发现：样本外等权买入持有（31.97%、Sharpe 0.8805）优于 MA250 趋势（30.71%、Sharpe 0.7637），
  趋势择时未创造超额收益。
- 新增报告：`phase3A2_design.md`、`phase3A2_report.md`、`phase3A2_test_report.md`。
- 未修改 `app/backtest/`、`app/quant/`、`app/data/`，历史行情/指标/快照/回测记录一行未动。

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
