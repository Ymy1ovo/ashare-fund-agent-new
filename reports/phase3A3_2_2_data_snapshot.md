# 阶段3A.3.2.2 数据快照（含 3A.3.2.2.1 / 3A.3.2.2.2）

- 生成时间：2026-11-13
- 数据库：`data/fund_agent.db`（**本地保存，不进 Git**）
- 本轮备份：`data/backups/fund_agent_pre_3a3_2_2_2_20261113.db`（272,003,072 字节）

## 1. 行情数据指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3`（13 字段） |
| 行数 | **116,609** |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本轮是否修改行情 | **否** |

连续第六个阶段保持同一指纹。

## 2. 表行数

| 表 | 3A.3.2.1 | 3A.3.2.2 | 3A.3.2.2.1 | **本轮** |
| --- | ---: | ---: | ---: | ---: |
| `etf_pool` | 46 | 46 | 46 | 46 |
| `etf_daily_prices` | 116,609 | 116,609 | 116,609 | **116,609** |
| `etf_indicator_daily` | 350,292 | 350,292 | 350,292 | 350,292 |
| `etf_adjustment_snapshots` | 139 | 139 | 139 | 139 |
| `trade_calendar` | 8,797 | 8,797 | 8,797 | 8,797 |
| `backtest_runs` | 11 | 11 | 11 | **11** |
| `validation_runs` | 41 | 42 | 43 | **44** |
| `validation_windows` | 311 | 319 | 319 | **335** |
| `validation_grid` | 272 | 280 | 280 | **296** |
| `validation_stress` | 273 | 280 | 280 | **294** |
| `corporate_actions` | 166 | 166 | 166 | **166** |
| `corporate_action_applications` | 2,788 | 3,787 | 3,787 | **3,787** |
| `corporate_action_versions` | 338 | 514 | 704 | **704** |
| `dividend_receivables` | 67 | 785 | 785 | **785** |
| 表数量 | 24 | 24 | 24 | **24** |

### 2.1 本轮 schema 变化

**无**。本轮只改代码逻辑，不动数据库结构。

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
| `official_confirmed` | **142** | 49 | 32 | 61 |
| `secondary_confirmed` | **14** | 0 | 0 | 14 |
| `unverified` | 10 | 0 | 0 | 10 |
| `rejected` | 0 | 0 | 0 | 0 |

**区间内 81 条 100% `official_confirmed`。**

### 3.3 零碎份额处置口径（45 条拆分/合并）

| 口径 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `truncate`（公告明示） | 9 | 0 | 0 | 9 |
| `round_up`（公告明示） | 5 | 2 | 3 | 0 |
| `unknown`（公告未载明） | 21 | 13 | 6 | 2 |
| `unknown`（无公告正文） | 10 | 0 | 0 | 10 |

### 3.4 分红日期完整性（本轮新增检查）

| 检查 | 数量 | 说明 |
| --- | ---: | --- |
| `record_date IS NULL` 的分红 | **0** | 构造阶段已强制 |
| `pay_date IS NULL` 的分红 | **0** | 构造阶段已强制 |
| `record_date == ex_date` | **4** | 全部在 2021 年前，不进回测 |
| `record_date > ex_date` | **0** | 构造阶段拒绝 |
| `pay_date < ex_date` | **0** | 构造阶段拒绝 |

4 条同日事件：

| action_id | 代码 | 除息日 | 在回测区间 |
| ---: | --- | --- | :---: |
| 6 | `159901` | 2007-07-11 | 否 |
| 38 | `511220` | 2015-06-18 | 否 |
| 39 | `511220` | 2015-09-21 | 否 |
| 60 | `159920` | 2018-06-22 | 否 |

## 4. 事件版本表

| 项 | 值 |
| --- | ---: |
| `corporate_action_versions` 行数 | **704** |
| 本轮是否新增版本 | **否** |
| 历史版本是否删除 | **否** |
| 版本号是否连续 | **166 条全部连续** |

704 行的来源链：

| 阶段 | 新增 | 累计 |
| --- | ---: | ---: |
| 3A.3.2.1 | 338 | 338 |
| 3A.3.2.2 | 176 | 514 |
| 3A.3.2.2.1 | 190 | 704 |
| **3A.3.2.2.2** | **0** | **704** |

## 5. 应收分红

| 项 | 值 |
| --- | ---: |
| `dividend_receivables` 行数 | 785 |
| 本轮是否新增 | **否** |

## 6. 会计版本标记

| 表 | 标记 | 数量 |
| --- | --- | ---: |
| `validation_runs` | `legacy_corporate_action_accounting` | 39 |
| `validation_runs` | `ca-v2-receivable` | **5** |
| `backtest_runs` | `legacy_corporate_action_accounting` | 11 |

`ca-v2-receivable` 五条：

| validation_id | input_hash | 说明 |
| --- | --- | --- |
| `e0ac2b1b3b9748ac` | `2ac80bcdfb5459c5` | 3A.3.2.1 第一次（作废不删） |
| `6e310be0193643c1` | `5f8a4c05613552fa` | 3A.3.2.1 最终 |
| `06600b4faac146c5` | `63d62a67a797c55b` | 3A.3.2.2 最终 |
| `e8b052dd2db542f9` | `6da51a1c462b7c65` | 3A.3.2.2.1 最终 |
| **`0df22f3810974bea`** | **`6da51a1c462b7c65`** | **本轮最终（input_hash 与上一轮相同）** |

> 本轮 `input_hash` 与 3A.3.2.2.1 完全相同，
> 因为本轮没有修改任何事件内容或配置——只加了安全边界。

## 7. 完整性检查

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 表数量 | 24 |
| 数据库大小 | 272,039,936 字节 |
| 备份大小 | 272,003,072 字节 |
| 增量 | 36,864 字节（一次验证重放的窗口/网格记录） |

## 8. 迁移测试

在备份副本上执行 `init_db()` **两次**：

| 表 | 前 | 后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 44 | 44 |
| `backtest_runs` | 11 | 11 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_applications` | 3,787 | 3,787 |
| `corporate_action_versions` | 704 | 704 |
| `dividend_receivables` | 785 | 785 |
| `integrity_check` | — | **ok** |

**数据未变、幂等、本轮无 schema 变更。**

## 9. 备份清单

| 文件 | 大小 | 说明 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_20261112.db` | 269,828,096 | 3A.3.2 前 |
| `data/backups/fund_agent_pre_3a3_2_1_20261113.db` | 270,176,256 | 3A.3.2.1 前 |
| `data/backups/fund_agent_pre_3a3_2_2_20261113.db` | 271,073,280 | 3A.3.2.2 前 |
| `data/backups/fund_agent_pre_3a3_2_2_1_20261113.db` | 271,958,016 | 3A.3.2.2.1 前 |
| `data/backups/fund_agent_pre_3a3_2_2_2_20261113.db` | **272,003,072** | 本轮前 |
| `data/fund_agent.db` | 272,039,936 | 当前 |

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
| 事件指纹算法 | `ca-events-v2`（字段集两次扩展） |

## 11. 未纳入快照的数据

| 项 | 原因 |
| --- | --- |
| `data/corporate_action_*.json` | 抓取产物 |
| `data/ca_announcements.json` | 公告全文 |
| `data/ca_ann_match.json` | 匹配结果 |
| `data/ca_fraction_audit_final.json` | 零碎规则审计清单 |
| `data/replay_3a3_2_2_2.json` | 本轮重放产物 |
| `logs/*.log` | 运行日志 |

抓取、匹配、审计、重放脚本均已入库，数据可重建。
