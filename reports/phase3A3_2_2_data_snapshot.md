# 阶段3A.3.2.2 数据快照

- 生成时间：2026-11-13
- 数据库：`data/fund_agent.db`（**本地保存，不进 Git**）
- 备份：`data/backups/fund_agent_pre_3a3_2_2_20261113.db`（271,073,280 字节）

## 1. 行情数据指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3`（13 字段） |
| 行数 | **116,609** |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本阶段是否修改行情 | **否** |

连续第四个阶段保持同一指纹。

## 2. 表行数

| 表 | 3A.3.2.1 | 本阶段 | 变化 |
| --- | ---: | ---: | --- |
| `etf_pool` | 46 | 46 | — |
| `etf_daily_prices` | 116,609 | 116,609 | — |
| `etf_indicator_daily` | 350,292 | 350,292 | — |
| `etf_adjustment_snapshots` | 139 | 139 | — |
| `trade_calendar` | 8,797 | 8,797 | — |
| `backtest_runs` | 11 | 11 | — |
| `backtest_orders` | 29,248 | 29,248 | — |
| `backtest_trades` | 26,093 | 26,093 | — |
| `backtest_daily_nav` | 7,579 | 7,579 | — |
| `backtest_positions_daily` | 58,559 | 58,559 | — |
| `validation_runs` | 41 | **42** | **+1** |
| `validation_windows` | 311 | **319** | +8 |
| `validation_grid` | 272 | **280** | +8 |
| `validation_stress` | 273 | **280** | +7 |
| `corporate_actions` | 166 | 166 | 行数不变（列有更新） |
| `corporate_action_applications` | 2,788 | **3,787** | +999（1 次验证重放） |
| `corporate_action_versions` | 338 | **514** | +176 |
| `dividend_receivables` | 67 | **785** | +718 |
| 表数量 | 24 | 24 | — |

### 2.1 为什么 `dividend_receivables` 增加 718 行

本阶段跑了一次完整验证（41 只 / 样本内 + 样本外 + 8 窗口），
每个区间分红都写应收记录。行数增加不是重复记账：

```sql
-- 每条形如 (run_id, action_id)，run_id 不同
SELECT COUNT(DISTINCT run_id) FROM dividend_receivables;
```

### 2.2 为什么 `applications` 增加 999 行

同上，一次完整验证覆盖 41 只 × 约 3 个区间 × 每事件每 run 一行。

## 3. 公司行为事件

### 3.1 按类型 × 区间（经济权益日）

| 类型 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `split` | 23 | 14 | 6 | 3 |
| `reverse_split` | 22 | 1 | 3 | 18 |
| `cash_distribution` | 121 | 34 | 23 | 64 |
| **合计** | **166** | **49** | **32** | **85** |

### 3.2 按证据等级

| 等级 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `official_confirmed` | **137** | 49 | 27 | 61 |
| `secondary_confirmed` | **19** | 0 | 5 | 14 |
| `unverified` | 10 | 0 | 0 | 10 |
| `rejected` | 0 | 0 | 0 | 0 |

**与 3A.3.2.1 的差异**：144 official / 12 secondary → **137 official / 19 secondary**。

原因：分级规则从「分数达标且至少 2 项核对」改为
「**全部核对项通过**才算 official」。
7 条此前被判 official 但只通过 2/4 或 3/4 项的事件被降级为 secondary。

### 3.3 区间内非 official 事件（5 条）

| 代码 | 类型 | 除息日 | 缺什么 |
| --- | --- | --- | --- |
| `511260` | 分红 | 2025-09-23 | 登记日/发放日未对到 |
| `159901` | 分红 | 2025-11-17 | 登记日/发放日未对到 |
| `511260` | 分红 | 2025-12-26 | 登记日/发放日未对到 |
| `511260` | 分红 | 2026-06-25 | 登记日/发放日未对到 |
| `511260` | 分红 | 2026-09-18 | 登记日/发放日未对到 |

这 5 条**除息日与金额都对到**，只是公告正文里登记日/发放日的表述
与解析规则不匹配。它们仍是 `secondary_confirmed`（有公告 URL 可核），
引擎照常应用，但**不得称为「已人工复核」**。

### 3.4 零碎份额处置口径

| 口径 | 条数 | 依据 |
| --- | ---: | --- |
| `truncate`（舍去/尾差入基金） | **161** | 9 条公告明示 + 21 条未明说按默认 + 131 条分红（无零碎） |
| `round_up`（进位） | **5** | 公告明示「上进位」 |
| `cash_compensation`（现金补偿） | **0** | 本库无此类公告 |

5 条 `round_up`：

| 代码 | 类型 | 除息日 | 比例 |
| --- | --- | --- | ---: |
| `510500` | split | 2022-08-26 | 1.1454 |
| `512100` | reverse_split | 2022-09-02 | 0.3656 |
| `511030` | reverse_split | 2025-03-18 | 0.1 |
| `159934` | reverse_split | 2025-09-19 | 0.9481 |
| `518800` | reverse_split | 2026-04-14 | 0.9423 |

## 4. 事件版本表

| 项 | 值 |
| --- | ---: |
| `corporate_action_versions` 行数 | 514 |
| 每条事件平均版本数 | 3.1 |
| 历史版本是否删除 | **否，一条未删** |

版本增加的两次来源：

| 操作 | 影响 |
| --- | --- |
| 证据等级严格化 | 166 条各 +1 |
| 零碎处置口径回写 | 5 条各 +1（其余保持 truncate 未变） |

## 5. 应收分红

| 项 | 值 |
| --- | ---: |
| `dividend_receivables` 行数 | 785 |
| 涉及不同 run | 多（含每次验证的 is/oos/window 区间） |
| 涉及不同行动 | 见 action_id 去重 |

## 6. 会计版本标记

| 表 | 标记 | 数量 |
| --- | --- | ---: |
| `validation_runs` | `legacy_corporate_action_accounting` | **39** |
| `validation_runs` | `ca-v2-receivable` | **3** |
| `backtest_runs` | `legacy_corporate_action_accounting` | 11 |

`ca-v2-receivable` 三条：

| validation_id | input_hash | 说明 |
| --- | --- | --- |
| `e0ac2b1b3b9748ac` | `2ac80bcdfb5459c5` | 3A.3.2.1 第一次（指纹未含事件，作废不删） |
| `6e310be0193643c1` | `5f8a4c05613552fa` | 3A.3.2.1 最终 |
| **`06600b4faac146c5`** | **`63d62a67a797c55b`** | **本阶段最终** |

## 7. 完整性检查

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 表数量 | 24 |
| 数据库大小 | 271,679,488 字节 |
| 备份大小 | 271,073,280 字节 |
| 增量 | 606,208 字节 |

## 8. 迁移测试

在备份副本上执行 `init_db()` **两次**：

| 项 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 41 | 41 |
| `backtest_runs` | 11 | 11 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_applications` | 2,788 | 2,788 |
| `corporate_action_versions` | 348 | 348 |
| `dividend_receivables` | 67 | 67 |
| `integrity_check` | — | **ok** |

本阶段新增列（5 个）：

```
corporate_actions.fractional_policy
corporate_action_applications.fractional_shares
corporate_action_applications.disposed_cost_basis
corporate_action_applications.realized_pnl
corporate_action_applications.official_ratio
```

**数据未变、幂等、只加不删。**

## 9. 备份清单

| 文件 | 大小 | 说明 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_20261112.db` | 269,828,096 | 3A.3.2 前 |
| `data/backups/fund_agent_pre_3a3_2_1_20261113.db` | 270,176,256 | 3A.3.2.1 前 |
| `data/backups/fund_agent_pre_3a3_2_2_20261113.db` | **271,073,280** | 本阶段前 |
| `data/fund_agent.db` | 271,679,488 | 当前 |

全部不进 Git。

## 10. 数据源与版本

| 项 | 版本/来源 |
| --- | --- |
| 行情 | AKShare（东方财富），本地缓存 |
| 复权 | `qfq` |
| 指标 | `v1.0.2-30b821a1af15` |
| 公司行为事件 | 东方财富基金公告接口（转载基金管理人公告全文） |
| 事件数据版本 | `ca-v1` |
| 会计版本 | `ca-v2-receivable` |
| 证据版本 | `ca-evidence-v1` |
| 行情指纹算法 | `market-fingerprint-v3` |
| 事件指纹算法 | `ca-events-v2`（本阶段字段集扩展，见指纹报告第 5 节） |

## 11. 未纳入快照的数据

| 项 | 原因 |
| --- | --- |
| `data/corporate_action_*.json` | 抓取产物 |
| `data/ca_announcements.json` | 公告全文（343 条） |
| `data/ca_ann_match.json` | 匹配结果（167 KB） |
| `data/replay_3a3_2_2.json` | 重放产物 |
| `logs/*.log` | 运行日志 |

抓取、匹配、重放脚本均已入库，数据可重建。
