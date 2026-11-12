# 阶段3A.3.2 数据快照

- 生成时间：2026-11-12
- 数据库：`data/fund_agent.db`（**本地保存，不提交 Git**）
- 备份：`data/backups/fund_agent_pre_3a3_2_20261112.db`

## 1. 行情数据指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 字段数 | 13 |
| 字段 | `code, trade_date, open, high, low, close, volume, amount, adjusted_close, adjustment_type, adjustment_snapshot_id, adjustment_coverage_start, adjustment_coverage_end` |
| 行数 | **116,609** |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 修复前 | 同上（**未变**） |
| 修复后 | 同上（**未变**） |

**本阶段未修改任何行情数据。** 所有修复都在账本层与事件表。

## 2. 表行数

| 表 | 行数 | 本阶段变化 |
| --- | ---: | --- |
| `etf_pool` | 46 | 未变 |
| `etf_daily_prices` | 116,609 | 未变 |
| `etf_indicator_daily` | 350,292 | 未变 |
| `etf_adjustment_snapshots` | 139 | 未变 |
| `trade_calendar` | 8,797 | 未变 |
| `backtest_runs` | 11 | 未变 |
| `backtest_orders` | 29,248 | 未变 |
| `backtest_trades` | 26,093 | 未变 |
| `backtest_daily_nav` | 7,579 | 未变 |
| `backtest_positions_daily` | 58,559 | 未变 |
| `validation_runs` | **39** | **+2**（37 → 39） |
| `validation_windows` | 295 | 未变 |
| `validation_grid` | 256 | 未变 |
| `validation_stress` | 259 | 未变 |
| **`corporate_actions`** | **166** | **新增表** |
| **`corporate_action_applications`** | **1,071** | **新增表** |

> `validation_runs` 从 37 增至 39：新增 `c46fa37b932944c2`（正确全池重放）
> 与 `b3f1e2c89ebc4b95`（首次误配置，6 只池，不作结论依据）。
> **旧记录一条未删、一条未改。**

## 3. 公司行为事件表

| 类型 | 总数 | 样本内（≤2024-12-31） | 样本外（≥2025-01-02） |
| --- | ---: | ---: | ---: |
| `split`（拆分） | 23 | 17 | 6 |
| `reverse_split`（合并） | 22 | 19 | 3 |
| `cash_distribution`（分红） | 121 | 98 | 23 |
| **合计** | **166** | **134** | **32** |

- 全部 `status='confirmed'`，**无 unverified 记录**
- 全部 `data_version='ca-v1'`
- 覆盖 26 只 ETF（46 只池内）
- 时间跨度：2005-02-16 ~ 2026-07-07

### 3.1 应用记录

| 类型 | 应用次数 | 现金影响合计 | 零碎现金合计 |
| --- | ---: | ---: | ---: |
| `cash_distribution` | 866 | 1,128,517.36 | 0.00 |
| `reverse_split` | 70 | — | 162.79 |
| `split` | 135 | — | 25.70 |
| **合计** | **1,071** | — | **188.49** |

零碎现金合计 188.49 元，占初始资金 0.019%，可忽略但完整留痕。

## 4. 完整性检查

| 检查项 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 表数量 | 22 |
| 数据库大小 | 270,176,256 字节 |
| 备份大小 | 269,828,096 字节 |
| 增量 | 348,160 字节（两张新表） |

## 5. 迁移测试

在备份副本上执行 `init_db()` 两次（验证幂等）：

| 项 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 37 | 37 |
| `backtest_runs` | 11 | 11 |
| `backtest_orders` | 29,248 | 29,248 |
| `backtest_trades` | 26,093 | 26,093 |
| `corporate_actions` | 不存在 | 0（空表） |
| `corporate_action_applications` | 不存在 | 0（空表） |
| `integrity_check` | — | ok |

**结论**：迁移只新增表，不触碰既有数据；连续执行两次结果一致。

## 6. 备份清单

| 文件 | 大小 | 说明 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_20261112.db` | 269,828,096 | 修复前完整备份（SQLite backup API） |
| `data/fund_agent.db` | 270,176,256 | 当前库 |

备份与当前库都不进 Git（`.gitignore` 已排除 `data/*.db`）。

## 7. 数据源与版本

| 项 | 版本/来源 |
| --- | --- |
| 行情 | AKShare（东方财富），本地缓存 |
| 复权 | `qfq`，快照版本随行情记录 |
| 指标 | `v1.0.2-30b821a1af15` |
| 公司行为 | 天天基金分红送配页 + 券商转发基金公告，`ca-v1` |
| 指纹算法 | `market-fingerprint-v3` |

## 8. 未纳入快照的数据

| 项 | 原因 |
| --- | --- |
| `data/corporate_action_*.json` | 抓取运行产物，可由脚本重建 |
| `data/replay_3a3_2.json` | 重放运行产物 |
| `data/replay_validation_3a3_2.json` | 重放运行产物 |
| `data/ca_audit_final.json` | 核查运行产物 |
| `logs/*.log` | 运行日志 |

抓取与重放脚本已入库，数据可重现。
