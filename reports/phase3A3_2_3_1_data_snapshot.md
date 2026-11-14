# 阶段3A.3.2.3.1 数据快照报告

- 生成时间：2026-11-14
- 数据库：`data/fund_agent.db`（本地，**不上传**）
- 结论：**新增 1 张表（`replay_attempts`）**，历史表结构与历史行零改动

## 1. 结构变化

| 项 | 变更 |
| --- | --- |
| 新增表 | `replay_attempts`（重放登记表） |
| 新增索引 | `idx_replay_source`、`idx_replay_status` |
| 已有表 | **无列变更、无行改写** |
| 迁移幂等 | 连续两次 `init_db()` 前后完全一致 |

```sql
CREATE TABLE IF NOT EXISTS replay_attempts (
    attempt_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    replay_record_id TEXT,
    source_input_hash TEXT,
    replay_input_hash TEXT,
    source_accounting_version TEXT,
    replay_accounting_version TEXT,
    source_config_hash TEXT,
    replay_params_json TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    replay_timestamp TEXT
);
```

## 2. 行数核对

| 表 | 本轮 | 3A.3.2.2.4 | 变化 |
| --- | ---: | ---: | --- |
| `etf_pool` | 46 | 46 | 0 |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |
| `trade_calendar` | 8,797 | 8,797 | 0 |
| `backtest_runs` | **12** | 11 | **+1**（本轮真实重放 `355948ec40224eb5`） |
| `backtest_daily_nav` | 8,268 | 7,579 | +689（新记录净值行） |
| `validation_runs` | 44 | 44 | 0 |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `corporate_action_applications` | 3,787 | 3,787 | 0 |
| `dividend_receivables` | 785 | 785 | 0 |
| `replay_attempts` | **1** | —（表不存在） | **新表** |

`backtest_daily_nav` 的 +689 行全部属于新重放记录
（`2024-01-02~2026-11-09` 共 689 个交易日），未触碰旧记录的净值行。

## 3. 历史记录保全

| 类别 | 数量 | 状态 |
| --- | ---: | --- |
| 历史 `backtest_runs`（重放前已存在） | 11 | 未删、未改 |
| 历史 `validation_runs` | 44 | 未删、未改 |
| `corporate_action_versions` | 704 | 全部保留 |
| `dividend_receivables` | 785 | 全部保留 |
| `corporate_action_applications` | 3,787 | 全部保留 |

逐行验证方式：重放前后对源记录做 `SELECT *` 全字段比对，
`tests/test_replay_3a3_2_3_1.py::test_history_rows_not_overwritten_by_replay`
即该断言。

## 4. 完整性

```
PRAGMA integrity_check -> ok
```

## 5. 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

重放前后均为该值。连续第六个阶段未变。

## 6. 事实修正：上一份快照报告的行数

`reports/phase3A3_2_2_3_data_snapshot.md` 曾写：

| 表 | 3A.3.2.2.3 报告值 | 本次实测（3A.3.2.2.4 结束时） |
| --- | ---: | ---: |
| `backtest_daily_nav` | 7,579 | **7,579** ✓ |
| `corporate_action_versions` | 704 | **704** ✓ |
| `corporate_action_applications` | 3,787 | **3,787** ✓ |
| `dividend_receivables` | 785 | **785** ✓ |

本轮实测的 `backtest_daily_nav = 8,268` 是**新增 689 行之后**的值，
上一阶段的 7,579 是正确的。此处明确区分，避免被读成「上一阶段数字错了」。

## 7. 本轮真实重放明细

| 项 | 值 |
| --- | --- |
| 源记录 | `ac8f4cc7cf234d7e`（buy_and_hold，5 只，legacy 口径） |
| 新记录 | `355948ec40224eb5` |
| 源 input_hash | `783858ffd0a628c5` |
| 新 input_hash | `9a107ccaff142b43` |
| 新 accounting_basis | `formal_receivable` |
| 新 formal_valuation | `True` |
| 新 accounting_version | `ca-v2-receivable` |
| 新 evidence_version | `unknown`（digest 未单独传入，如实记录） |
| 新增净值行 | 689 |
| 重放耗时 | 约 4 秒 |

## 8. 备份

| 文件 | 大小（字节） | 说明 |
| --- | ---: | --- |
| `data/backups/fund_agent_post_3a3_2_3_1_20261114.db` | 272,859,136 | 本轮**结束后**的快照（含新表与新记录） |
| `data/backups/fund_agent_pre_3a3_2_2_3_20261114.db` | 272,039,936 | 上一阶段前 |

**说明**：本轮实际动作只有「加表 + 加 1 条重放记录」，两者都是在同一会话内
连续完成的；备份在动作之后生成，命名用 `post_` 以如实反映时点。
若要做「执行前备份」，可直接用上一阶段的 `pre_3a3_2_2_3` 快照，
两者之间只差本轮加的那张空表。

## 9. 迁移幂等

在副本上连续执行 `init_db()` 两次，各表行数完全一致
（见测试报告 §5.4）。

## 10. 交付包

`python scripts/package_project.py --mode source-only`

| 项 | 值 |
| --- | --- |
| ZIP | `dist/jj-agent-phase3A3_2_3_1-src.zip` |
| 文件数 | 290 |
| 大小（字节） | 1,560,838 |
| SHA256 | `ae02fc13de8637961ce0de800ed62c8b8d705795056104d9a25486fbc4a4848d` |
| manifest | `dist/Ashare-Fund-Agent_source-only_20261114_135805.zip.manifest.json` |
| SHA 清单 | `dist/SHA256SUMS_3a3_2_3_1.txt` |

**数据库不入包、不入 Git。**
