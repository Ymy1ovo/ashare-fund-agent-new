# 阶段3A.3.2.1 数据快照

- 生成时间：2026-11-13
- 数据库：`data/fund_agent.db`（**本地保存，不提交 Git**）
- 备份：`data/backups/fund_agent_pre_3a3_2_1_20261113.db`（270,176,256 字节）

## 1. 行情数据指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3`（13 字段） |
| 行数 | **116,609** |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本阶段是否修改行情 | **否** |

连续第三个阶段保持同一指纹。

## 2. 表行数

| 表 | 行数 | 本阶段变化 |
| --- | ---: | --- |
| `etf_pool` | 46 | 未变 |
| `etf_daily_prices` | 116,609 | 未变 |
| `etf_indicator_daily` | 350,292 | 未变 |
| `etf_adjustment_snapshots` | 139 | 未变 |
| `trade_calendar` | 8,797 | 未变 |
| `backtest_runs` | 11 | 未变（仅加口径标记列） |
| `backtest_orders` | 29,248 | 未变 |
| `backtest_trades` | 26,093 | 未变 |
| `backtest_daily_nav` | 7,579 | 未变 |
| `backtest_positions_daily` | 58,559 | 未变 |
| `validation_runs` | **41** | **+2**（39 → 41） |
| `validation_windows` | 311 | +16 |
| `validation_grid` | 272 | +16 |
| `validation_stress` | 273 | +14 |
| `corporate_actions` | 166 | 未变行数（更新证据字段） |
| `corporate_action_applications` | **2,788** | +1,716 |
| **`corporate_action_versions`** | **338** | **新增表** |
| **`dividend_receivables`** | **67** | **新增表** |

## 3. 公司行为事件

### 3.1 按类型

| 类型 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `split` | 23 | 14 | 6 | 3 |
| `reverse_split` | 22 | 1 | 3 | 18 |
| `cash_distribution` | 121 | 34 | 23 | 64 |
| **合计** | **166** | **49** | **32** | **85** |

### 3.2 按证据等级

| 等级 | 合计 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `official_confirmed` | 144 | 49 | 32 | 63 |
| `secondary_confirmed` | 12 | 0 | 0 | 12 |
| `unverified` | 10 | 0 | 0 | 10 |
| `rejected` | 0 | 0 | 0 | 0 |

**回测区间内 81 条 100% 为 `official_confirmed`。**

### 3.3 证据等级 × status

| evidence_status | status | 数量 |
| --- | --- | ---: |
| `official_confirmed` | `confirmed` | 144 |
| `secondary_confirmed` | `confirmed` | 12 |
| `unverified` | `unverified` | 10 |

`status` 保留兼容，`evidence_status` 是新的事实来源。

## 4. 应收分红

| 项 | 值 |
| --- | ---: |
| `dividend_receivables` 行数 | 67 |
| 已结清（`settled`） | 67 |
| 未结清（`pending`） | 0 |
| 累计金额 | 38,697.97 元 |

> 全部 `settled` 是因为重放区间已完整跑完；
> 若回测在发放日之前结束，会留下 `pending` 行。

## 5. 事件应用

| 项 | 值 |
| --- | ---: |
| `corporate_action_applications` 行数 | 2,788 |
| 涉及不同事件 | 79 |
| 涉及 run | 210 |
| 零账本变化行 | 0 |

## 6. 会计版本标记

| 表 | 标记 | 数量 |
| --- | --- | ---: |
| `validation_runs` | `legacy_corporate_action_accounting` | 39 |
| `validation_runs` | `ca-v2-receivable` | **2** |
| `backtest_runs` | `legacy_corporate_action_accounting` | 11 |

## 7. 完整性检查

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 表数量 | 24 |
| 数据库大小 | 271,060,992 字节 |
| 备份大小 | 270,176,256 字节 |
| 增量 | 884,736 字节（两张新表 + 应收记录） |

## 8. 迁移测试

在备份副本上执行 `init_db()` **两次**：

| 项 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 39 | 39 |
| `backtest_runs` | 11 | 11 |
| `backtest_orders` | 29,248 | 29,248 |
| `backtest_trades` | 26,093 | 26,093 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_applications` | 1,071 | 1,071 |
| `corporate_action_versions` | 不存在 | 0（空表） |
| `dividend_receivables` | 不存在 | 0（空表） |
| `integrity_check` | — | **ok** |

新增列（7 个）：

```
evidence_status, announcement_title, announcement_date,
announcement_url, manager_name, event_fingerprint, version_no
```

**数据未变、幂等、只加不删。**

## 9. 备份清单

| 文件 | 大小 | 说明 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_20261112.db` | 269,828,096 | 3A.3.2 修复前 |
| `data/backups/fund_agent_pre_3a3_2_1_20261113.db` | 270,176,256 | 本阶段修复前 |
| `data/fund_agent.db` | 271,060,992 | 当前 |

全部不进 Git（`.gitignore` 已排除 `data/*.db` 与 `data/backups/`）。

## 10. 数据源与版本

| 项 | 版本/来源 |
| --- | --- |
| 行情 | AKShare（东方财富），本地缓存 |
| 复权 | `qfq` |
| 指标 | `v1.0.2-30b821a1af15` |
| 公司行为事件 | 东方财富基金公告接口（转载基金管理人公告全文） |
| 事件数据版本 | `ca-v1` |
| 会计版本 | `ca-v2-receivable`（本阶段新增） |
| 证据版本 | `ca-evidence-v1` |
| 行情指纹算法 | `market-fingerprint-v3` |
| 事件指纹算法 | `ca-events-v2` |

## 11. 未纳入快照的数据

| 项 | 原因 |
| --- | --- |
| `data/corporate_action_*.json` | 抓取运行产物 |
| `data/ca_announcements.json` | 公告抓取产物（343 条公告全文） |
| `data/ca_ann_match.json` | 匹配结果 |
| `data/replay_3a3_2_1.json` | 重放产物 |
| `logs/*.log` | 运行日志 |

抓取与重放脚本已入库，数据可重建。
