# 阶段3A.3.2.2 数据快照（含 3A.3.2.2.1 收尾）

- 生成时间：2026-11-13
- 数据库：`data/fund_agent.db`（**本地保存，不进 Git**）
- 本阶段备份：`data/backups/fund_agent_pre_3a3_2_2_1_20261113.db`（271,958,016 字节）

## 1. 行情数据指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3`（13 字段） |
| 行数 | **116,609** |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本阶段是否修改行情 | **否** |

连续第五个阶段保持同一指纹。

## 2. 表行数

| 表 | 3A.3.2.1 | 3A.3.2.2 | **本阶段** |
| --- | ---: | ---: | ---: |
| `etf_pool` | 46 | 46 | 46 |
| `etf_daily_prices` | 116,609 | 116,609 | **116,609** |
| `etf_indicator_daily` | 350,292 | 350,292 | 350,292 |
| `etf_adjustment_snapshots` | 139 | 139 | 139 |
| `trade_calendar` | 8,797 | 8,797 | 8,797 |
| `backtest_runs` | 11 | 11 | 11 |
| `validation_runs` | 41 | 42 | **43** |
| `validation_windows` | 311 | 319 | 319 |
| `validation_grid` | 272 | 280 | 280 |
| `validation_stress` | 273 | 280 | 280 |
| `corporate_actions` | 166 | 166 | 166 |
| `corporate_action_applications` | 2,788 | 3,787 | **3,787** |
| `corporate_action_versions` | 338 | 514 | **704** |
| `dividend_receivables` | 67 | 785 | **785** |
| 表数量 | 24 | 24 | 24 |

## 3. 公司行为事件

### 3.1 按类型 × 区间（经济权益日）

| 类型 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `split` | 23 | 14 | 6 | 3 |
| `reverse_split` | 22 | 1 | 3 | 18 |
| `cash_distribution` | 121 | 34 | 23 | 64 |
| **合计** | **166** | **49** | **32** | **85** |

（41 只回测池视角：样本内 49 / 样本外 31，差 `588200`）

### 3.2 按证据等级

| 等级 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `official_confirmed` | **142** | 49 | 32 | 61 |
| `secondary_confirmed` | **14** | 0 | 0 | 14 |
| `unverified` | 10 | 0 | 0 | 10 |
| `rejected` | 0 | 0 | 0 | 0 |

**区间内 81 条 100% 为 `official_confirmed`。**

与 3A.3.2.2 的差异：137/19 → **142/14**。
5 条区间内 secondary 分红修正登记日/发放日后升级为 official。

### 3.3 零碎份额处置口径（仅 45 条拆分/合并）

| 口径 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `truncate`（公告明示） | **9** | 0 | 0 | 9 |
| `round_up`（公告明示） | **5** | 2 | 3 | 0 |
| `unknown`（公告未载明） | **21** | 13 | 6 | 2 |
| `unknown`（无公告正文） | **10** | 0 | 0 | 10 |
| **合计** | **45** | 15 | 9 | 21 |

与 3A.3.2.2 的差异：45 `truncate` → **9 truncate / 5 round_up / 31 unknown**。

### 3.4 区间内不明规则事件的实际持仓核查

| 项 | 数量 |
| --- | ---: |
| 区间内 `unknown` 规则事件 | **19** |
| 其中实际产生零碎份额 | **0** |
| 其中被阻断 | **0** |
| 其中可正常应用 | **19** |

全部 19 条官方比例都是整数（2/3/4/5/10/12），
持仓为整数时折算结果必然整数，零碎恒为 0。

## 4. 事件版本表

| 项 | 值 |
| --- | ---: |
| `corporate_action_versions` 行数 | **704** |
| 每事件平均版本数 | 4.24 |
| 历史版本是否删除 | **否，一条未删** |
| 版本号是否连续 | **166 条全部连续** |

### 4.1 3A.3.2.2 阶段的 176 行构成

| 时间 | 条数 | change_reason |
| --- | ---: | --- |
| 11:24 | 5 | 零碎份额口径判定：公告明示进位 |
| 11:29 | 5 | 零碎份额口径判定：公告明示进位 |
| 11:34 | 137 | 证据等级回写：official_confirmed |
| 11:34 | 19 | 证据等级回写：secondary_confirmed |
| 11:34 | 10 | 证据等级回写：unverified |
| **合计** | **176** | |

**多出的 5 行**：`round_up` 被写入两次，源自 `save_action` 幂等缺陷
（指纹相同但关键列未落库时反复写入）。缺陷已在 3A.3.2.2 修复，
重复版本按纪律保留。

### 4.2 本阶段新增 190 行

| 时间 | 条数 | change_reason |
| --- | ---: | --- |
| 13:14 | 21 | 零碎份额口径判定：公告未载明零碎处置方式 |
| 13:14 | 10 | 零碎份额口径判定：无公告正文 |
| 13:14 | 5 | 零碎份额口径判定：公告明示进位 |
| 13:17 | 123 | 证据等级回写：official_confirmed |
| 13:17 | 11 | 证据等级回写：secondary_confirmed |
| 13:17 | 9 | 零碎份额口径判定：公告明示舍去/尾差入基金 |
| 13:17 | 5 | 零碎份额口径判定：公告明示进位 |
| 13:17 | 1 | 证据等级回写：unverified |
| 13:17 | 5 | 登记日/发放日按公告场内列修正 |

## 5. 应收分红

| 项 | 值 |
| --- | ---: |
| `dividend_receivables` 行数 | 785 |
| 涉及 run | 多（每次验证的 is/oos/window 区间各一份） |

## 6. 会计版本标记

| 表 | 标记 | 数量 |
| --- | --- | ---: |
| `validation_runs` | `legacy_corporate_action_accounting` | **39** |
| `validation_runs` | `ca-v2-receivable` | **4** |
| `backtest_runs` | `legacy_corporate_action_accounting` | 11 |

`ca-v2-receivable` 四条：

| validation_id | input_hash | 说明 |
| --- | --- | --- |
| `e0ac2b1b3b9748ac` | `2ac80bcdfb5459c5` | 3A.3.2.1 第一次（指纹未含事件，作废不删） |
| `6e310be0193643c1` | `5f8a4c05613552fa` | 3A.3.2.1 最终 |
| `06600b4faac146c5` | `63d62a67a797c55b` | 3A.3.2.2 最终 |
| **`e8b052dd2db542f9`** | **`6da51a1c462b7c65`** | **本阶段最终** |

## 7. 完整性检查

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 表数量 | 24 |
| 数据库大小 | 272,003,072 字节 |
| 备份大小 | 271,958,016 字节 |

## 8. 迁移测试

在备份副本上执行 `init_db()` **两次**：

| 表 | 前 | 后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 43 | 43 |
| `backtest_runs` | 11 | 11 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_applications` | 3,787 | 3,787 |
| `corporate_action_versions` | 704 | 704 |
| `dividend_receivables` | 785 | 785 |
| `integrity_check` | — | **ok** |

新增列：

| 表 | 列 |
| --- | --- |
| `corporate_actions` | `fractional_policy`（默认改 `unknown`）、`compensation_price`、`compensation_price_source` |
| `corporate_action_versions` | `fractional_policy`、`compensation_price`、`compensation_price_source` |
| `corporate_action_applications` | `fractional_shares`、`disposed_cost_basis`、`realized_pnl`、`official_ratio` |

**数据未变、幂等、只加不删。**

## 9. 备份清单

| 文件 | 大小 | 说明 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_20261112.db` | 269,828,096 | 3A.3.2 前 |
| `data/backups/fund_agent_pre_3a3_2_1_20261113.db` | 270,176,256 | 3A.3.2.1 前 |
| `data/backups/fund_agent_pre_3a3_2_2_20261113.db` | 271,073,280 | 3A.3.2.2 前 |
| `data/backups/fund_agent_pre_3a3_2_2_1_20261113.db` | **271,958,016** | 本阶段前 |
| `data/fund_agent.db` | 272,003,072 | 当前 |

全部不进 Git（`.gitignore` 已排除 `data/*.db` 与 `data/backups/`）。

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
| 事件指纹算法 | `ca-events-v2`（字段集两次扩展，见指纹报告） |

## 11. 未纳入快照的数据

| 项 | 原因 |
| --- | --- |
| `data/corporate_action_*.json` | 抓取产物 |
| `data/ca_announcements.json` | 公告全文 |
| `data/ca_ann_match.json` | 匹配结果 |
| `data/ca_fraction_audit_final.json` | 零碎规则审计清单 |
| `data/replay_3a3_2_2_1.json` | 重放产物 |
| `logs/*.log` | 运行日志 |

抓取、匹配、审计、重放脚本均已入库，数据可重建。
