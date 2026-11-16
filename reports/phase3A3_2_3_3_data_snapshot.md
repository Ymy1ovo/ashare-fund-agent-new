# 阶段3A.3.2.3.3 数据快照报告

- 首次执行：2026-11-14 / 复核补充：2026-11-16
- 数据库：`data/fund_agent.db`（本地，**不上传**）

## 1. 结构变化

**无 schema 变更。** 本轮只新增数据行，未新增表、未新增列、未新增索引。

## 2. 行数核对

| 表 | 首次执行前 | 现在 | 变化 |
| --- | ---: | ---: | --- |
| `etf_pool` | 46 | 46 | 0 |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |
| `trade_calendar` | 8,797 | 8,797 | 0 |
| `backtest_runs` | 12 | 12 | 0 |
| `validation_runs` | 44 | **47** | **+3** |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `corporate_action_applications` | 3,787 | 3,787 | 0 |
| `dividend_receivables` | 785 | 785 | 0 |
| `replay_attempts` | 1 | **4** | **+3** |

新增的 3 条 `validation_runs`：

| validation_id | status | accounting_version | legacy_flag | 说明 |
| --- | --- | --- | --- | --- |
| `03410886d1f64fa7` | success | `ca-v2-receivable` | NULL | 第一条 P0 重放 |
| `397118a140c44f47` | **failed** | NULL | NULL | 首次执行失败留痕（已降级） |
| `321caeb581e54d3b` | success | `ca-v2-receivable` | NULL | 第二条 P0 重放 |

## 3. 历史记录保全

| 类别 | 数量 | 状态 |
| --- | ---: | --- |
| 源 `32aead3291734f91` | 1 | 全字段与执行前快照逐字段相等 |
| 源 `c46fa37b932944c2` | 1 | 全字段与执行前快照逐字段相等 |
| 其余 42 条历史 validation | 42 | 未删未改 |
| 历史 `backtest_runs` | 12 | 未删未改 |
| `corporate_action_versions` | 704 | 全部保留 |
| `dividend_receivables` | 785 | 全部保留 |

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

重放前、两次重放后、dry-run 后、幂等复跑后，五次测量均为该值。

## 6. 公司行为事件指纹

| 项 | 值 |
| --- | --- |
| 全库区间内事件 | 81 条（全部可应用） |
| **41 只回测池内事件** | **80 条**（全部可应用） |
| 池内事件 digest | `668090ae7ed7e81b931c2ba45463911f…` |
| 全库事件 digest | `8aeafc0a2d17fd2ce2a65983eb81129d…` |
| `corporate_actions` 行数 | 166（不变） |
| `corporate_action_versions` 行数 | 704（不变） |

差值是 `588200`（在 46 只全库池中，不在 41 只回测池中）。

## 7. 备份与快照

| 文件 | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `data/backups/fund_agent_pre_3a3_2_3_3_20261114.db` | 272,859,136 | `b323147ae9d6747a7004ccdac89c68a6a465f2259ba2468d1745ca0be07ae2eb` |
| `data/fund_agent.db`（当前） | 272,965,632 | `a1a95c668e4e6caa31692492a67f92fa782fe501b6ad3bbf4c861f308df4833d` |

`pre_3a3_2_3_3` 是首次执行**之前**的完整备份，可用
SQLite 备份 API 或直接复制还原到重放前状态。

## 8. 交付包

| 项 | 值 |
| --- | --- |
| ZIP | `dist/jj-agent-phase3A3_2_3_3-src.zip` |
| 文件数 | 295 |
| 大小（字节） | 1,590,902 |
| SHA256 | `bd2da1e5a25f72af82aa79f8935314e7a7fb44711e8ac876775b34ad3d0efdb4` |
| manifest | `dist/Ashare-Fund-Agent_source-only_20261116_111033.zip.manifest.json` |
| SHA 清单 | `dist/SHA256SUMS_3a3_2_3_3.txt` |

**数据库不入包、不入 Git。**
