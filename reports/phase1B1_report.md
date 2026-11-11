# 阶段1B.1 交付报告

- 项目：A股基金量化分析 Agent V1.0
- 阶段：1B.1（前复权历史数据一致性修复）
- 生成时间：2026-11-09T15:50:58
- 项目目录：`D:\ymy\jj-agent`
- 数据源：AKShare `fund_etf_hist_em(adjust='qfq')`

## 1. 验收结论

| 验收条件 | 实际结果 |
| --- | --- |
| 同一 ETF 全部 adjusted_close 来自同一快照 | 通过；混合快照 0 只 |
| 每只 ETF 有当前快照 | 46/46 |
| 快照状态 | success 44；partial 2；failed 当前快照 0 |
| 无快照引用记录 | 0 |
| 原始 OHLC 未被复权刷新修改 | 通过；刷新前/后 SHA256 完全一致 |
| 行情记录未因重复刷新增加 | 通过；仍为 116,609 条 |
| 失败/空数据不覆盖旧值 | 通过；离线测试覆盖，实际刷新 0 失败 |
| 离线测试 | 44 passed |
| API 与看板 | 通过；summary 显示 46 个当前快照、0 个混合快照 |

## 2. 问题根因与修复

### 原逻辑问题

- 阶段1B 的日常 `sync_data.py` 从数据库最后日期开始获取增量 qfq。
- qfq 会因后续分红/拆分重新调整全部历史价格；把新 qfq 的末端拼到旧 qfq 历史后面，会产生不同调整基准混用。
- `etf_daily_prices` 原先没有快照 ID、采集时间、覆盖区间，无法审计每行来自哪一轮调整。

### 修复方案

- 原始行情与复权行情解耦：日常同步只 UPSERT 原始 OHLC，不再写增量 qfq。
- 新增完整历史 qfq 刷新任务：每次拉取完整历史，按交易日与原始行情对应。
- 新增 `adjustment_runs` 和 `etf_adjustment_snapshots`；每轮刷新生成快照，当前快照 `is_current=1`。
- `etf_daily_prices` 增加 `adjustment_snapshot_id`、`adjustment_collected_at`、`adjustment_source`、`adjustment_coverage_start/end`。
- 刷新在单只基金事务中激活新快照并更新全部行；失败/空数据只记录失败快照，旧当前快照和旧复权值保持。
- `sync_data.py` 改为：原始增量 → 同一批基金完整复权刷新 → 导出观察池快照。

## 3. 实际快照结果

| 指标 | 数值 |
| --- | ---: |
| 当前快照基金 | 46 / 46 |
| success 快照 | 44 |
| partial 快照 | 2 |
| 当前 failed 快照 | 0 |
| 混合快照基金 | 0 |
| 无快照引用行情 | 0 |
| adjusted_close 缺失 | 149 |
| 历史快照记录总数（含历史轮次） | 139 |
| 行情总记录 | 116,609 |
| 数据库大小 | 36.44 MiB |
| 最近复权刷新 | 2026-11-09T15:45:11（partial） |

### 部分覆盖基金

| 代码 | 快照ID | 原始行 | 匹配行 | 缺失行 | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| 510050 | 108 | 5276 | 5168 | 108 | partial |
| 510880 | 112 | 4812 | 4771 | 41 | partial |

- 510050：108 个交易日没有有效前复权收盘价，原始行情保留，复权价为空。
- 510880：41 个交易日没有有效前复权收盘价，原始行情保留，复权价为空。
- 这两只没有标记 success，也没有用旧基准值填补缺失日期。

## 4. 原始 OHLC 保护

最终一致性报告：`reports/phase1B1_consistency.md`

- 最终刷新前备份：`data/backups/fund_agent_before_final_adjustment_refresh.db`
- 刷新前原始行数：116609
- 刷新后原始行数：116609
- 刷新前原始 OHLC SHA256：`b701ec7ce31bb52e360f3f1f31c7fdfaf781af2ce6389ec9317548fce4020488`
- 刷新后原始 OHLC SHA256：`b701ec7ce31bb52e360f3f1f31c7fdfaf781af2ce6389ec9317548fce4020488`
- 哈希是否一致：是

更早的 1B 库（116609 行）原始哈希为 `3399afe2b3b03c657cbeca29933a805905badaa3cccb9cc1d0dc8cd95afe6c1a`。该哈希在 1B.1 的原始行情日常同步中被合法更新为当日收盘值，因此最终刷新使用“同步后的库”作为基线，证明复权刷新本身未修改任何原始 OHLC。

## 5. 调整刷新运行记录

| run_id | 类型 | 状态 | 基金数 | 成功 | 部分 | 失败 | 空 | 更新行数 | 时间 |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | qfq_full | success | 1 | 1 | 0 | 0 | 0 | 3,511 | 2026-11-09T15:35:27 ~ 2026-11-09T15:35:29 |
| 2 | qfq_full | partial | 46 | 44 | 2 | 0 | 0 | 116,609 | 2026-11-09T15:35:40 ~ 2026-11-09T15:37:30 |
| 3 | qfq_full | partial | 46 | 44 | 2 | 0 | 0 | 116,609 | 2026-11-09T15:41:16 ~ 2026-11-09T15:42:53 |
| 4 | qfq_full | partial | 46 | 44 | 2 | 0 | 0 | 116,609 | 2026-11-09T15:43:22 ~ 2026-11-09T15:45:11 |

### 日常同步验证

最新原始增量同步 run_id=5：46/46 成功，抓取 46 行，UPSERT 46 行；随后 adjustment run_id=3 完整刷新 46 只，证明同步策略不再拼接增量 qfq。

## 6. 测试结果

- pytest：**44 passed**，耗时 6.85s。
- 新增 `tests/test_adjustment.py` 6 项，覆盖完整刷新、基准切换、原始 OHLC 不变、失败/空数据保留、部分覆盖隔离、重复刷新去重、原始同步不碰复权字段。
- 测试使用临时 SQLite，不访问网络，不修改正式数据库。
- 详细见 `reports/phase1B1_test_report.md`。

## 7. API 与看板

| 检查 | 结果 |
| --- | --- |
| `/health` | ok，116,609 条行情，139 条历史快照记录，4 次复权刷新 |
| `/api/market-data/summary` | 46 个当前快照，0 个混合快照，149 条复权缺失 |
| `/api/market-data/510300?...` | 返回行级 `adjustment_snapshot_id` / 采集时间 |
| `/api/adjustment/runs` | 200，返回复权刷新记录 |
| Streamlit AppTest | 0 异常，5 个数据表，指标显示 46/2/0/149 |

详细见 `reports/phase1B1_api_test.md`。

## 8. 性能与成本

- 46 只完整 qfq 刷新约 109 秒（run_id=4：15:43:22 ~ 15:45:11）。
- 日常同步 = 原始增量约 95 秒 + 完整复权刷新约 109 秒，约 3.5 分钟。
- 每次刷新 46 个独立子进程，受并发限制为 1，优先保证旧请求真正结束且不触发限流。
- 当前规模下成本可接受；未来可评估调整因子版本化，减少全量 qfq 请求。

## 9. 失败基金

- 实际完整刷新 failed=0，empty=0。
- partial=2：510050、510880，原因是 AKShare qfq 历史中部分交易日没有有效复权收盘价。
- partial 不被标记为 success；缺失复权价保留 NULL，不填补旧基准。

## 10. 交付物

- 数据库迁移：`app/database/db.py`（新增调整运行表、快照表、行级快照字段）
- 复权刷新：`app/data/processors/adjustment.py`、`scripts/refresh_adjusted_prices.py`
- 同步策略：`scripts/sync_data.py`（原始增量 + 完整 qfq 刷新）
- 一致性检查：`scripts/check_adjustment_consistency.py`
- 一致性报告：`reports/phase1B1_consistency.md`
- 数据质量报告：`reports/phase1B_data_quality.md`
- 测试报告：`reports/phase1B1_test_report.md`
- API 报告：`reports/phase1B1_api_test.md`
- 阶段报告：`reports/phase1B1_report.md`
- 交付 ZIP：`dist/Ashare-Fund-Agent_phase1B1_20261109.zip`

## 11. 限制与后续

- 前复权价仍来自 AKShare，未用分红公告逐笔重算；qfq 是数据源口径。
- 510050/510880 的 149 个缺失复权值是数据源限制，已标记 partial，不猜测。
- 后复权只做了口径实测，没有落地主表；若以后需要 hfq，可增加独立快照表。
- 当前只支持单一 qfq 来源，跨源复核尚未接入。
- 本轮不进入策略、回测或自动交易，等待项目负责人验收。
