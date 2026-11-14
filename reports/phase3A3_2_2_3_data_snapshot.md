# 阶段3A.3.2.2.3 数据快照报告

- 生成时间：2026-11-14
- 数据库：`data/fund_agent.db`（本地，**不上传**）
- 结论：**本轮无 schema 变更、无数据改写**

## 1. 结构变化

无。`accounting_basis` / `formal_valuation` 写入既有 `backtest_runs.summary_json`，
不新增列、不新增表、不新增索引。`init_db()` 的建表与迁移语句本轮未修改。

## 2. 行数核对

| 表 | 本轮 | 3A.3.2.2.2 | 变化 |
| --- | ---: | ---: | --- |
| `etf_pool` | 46 | 46 | 0 |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |
| `trade_calendar` | 8,797 | 8,797 | 0 |
| `backtest_runs` | 11 | 11 | 0 |
| `backtest_daily_nav` | 7,579 | 7,579 | 0 |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `corporate_action_applications` | 3,787 | 3,787 | 0 |
| `dividend_receivables` | 785 | 785 | 0 |
| `validation_runs` | 44 | 44 | 0 |

## 3. 完整性

```
PRAGMA integrity_check -> ok
```

## 4. 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

连续第五个阶段未变。

## 5. 历史记录保全

| 类别 | 数量 | 状态 |
| --- | ---: | --- |
| 历史 `backtest_runs` | 11 | 未删未改 |
| 历史 `validation_runs` | 44 | 未删未改 |
| `corporate_action_versions` | 704 | 全部保留，无删除 |
| `dividend_receivables` | 785 | 全部保留 |

历史回测记录读取时显示 `accounting_basis=unknown_legacy` + `formal_valuation=False`，
因为这两个字段在它们写入时尚不存在。**不做事后回填**——回填等于给旧记录
补造一个当时的会计口径证据。

## 6. 备份

| 文件 | 大小（字节） | 用途 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_2_2_20261113.db` | 272,003,072 | 3A.3.2.2.2 前 |
| `data/backups/fund_agent_pre_3a3_2_2_3_20261114.db` | 272,039,936 | 本轮前 |

本轮备份已生成，`integrity_check` 通过。

## 7. 迁移幂等

在副本上连续执行 `init_db()` 两次，九张表行数前后完全一致（见测试报告 §4.4）。

## 8. 交付包

`python scripts/package_project.py --mode source-only`

| 项 | 值 |
| --- | --- |
| ZIP | `dist/jj-agent-phase3A3_2_2_3-src.zip` |
| 文件数 | 275 |
| 大小（字节） | 1,505,899 |
| SHA256 | `97872662a9ad87530b92af7a9e5270f6d67915c30001c7b4300bd0eb950d61c8` |
| manifest | `dist/Ashare-Fund-Agent_source-only_20261114_110904.zip.manifest.json` |
| SHA 清单 | `dist/SHA256SUMS_3a3_2_2_3.txt` |

**数据库不入包、不入 Git。**
