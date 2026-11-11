# 阶段3A.1.1 数据库快照交付报告

- 生成时间：2026-11-11T13:06:28
- 生成方式：`scripts/package_project.py --mode data-snapshot`（SQLite backup API，不是直接复制运行中的文件）

## 一、快照文件

| 项目 | 内容 |
| --- | --- |
| ZIP 路径 | `D:\ymy\jj-agent\dist\Ashare-Fund-Agent_data-snapshot_20261111_130622.zip` |
| ZIP 大小 | 103,748,327 字节（98.94 MiB） |
| ZIP SHA256 | `1c60cf6becd5246bb85e13a49b4f3144f3afcff5a3a343ae577cfb0e0c9b65e4` |
| manifest | `D:\ymy\jj-agent\dist\Ashare-Fund-Agent_data-snapshot_20261111_130622.zip.manifest.json` |
| 校验文件 | `D:\ymy\jj-agent\dist\Ashare-Fund-Agent_data-snapshot_20261111_130622.zip.sha256` |
| 包内数据库 | `data/fund_agent.db`，268,386,304 字节 |
| 包内数据库 SHA256 | `cadc65c336a5e30ad56031d2f042331d37cab260c8d4b413605c5d9078050343` |
| ZIP 内容 | `data/fund_agent.db` + 3 个迁移文件 + `manifest.json` |

## 二、导出前检查（源库）

| 检查项 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 验证 run `cabbfe77035d40f3` 存在 | **是（1 条）** |
| 源库 SHA256 | `ab99d341b066235cae5a6c852f12e03a7bfc3238cf093aaa7334f2261daaaac6` |

## 三、导出后检查（快照库）

| 检查项 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| ZIP `testzip()` | **None（无损坏）** |
| 源库与快照库逐表记录数 | **14 张表全部一致，0 差异** |
| 源库与快照库逐表内容哈希 | **全部一致，0 表不一致** |
| schema 一致性 | **完全一致** |

## 四、关键表记录数（快照库实测）

| 表 | 记录数 |
| --- | ---: |
| `etf_pool` | 46 |
| `etf_daily_prices` | 116,609 |
| `trade_calendar` | 8,797 |
| `etf_adjustment_snapshots` | 139 |
| `adjustment_runs` | 4 |
| `indicator_runs` | 186 |
| `etf_indicator_daily` | 350,292 |
| `backtest_runs` | 11 |
| `backtest_daily_nav` | 7,579 |
| `backtest_orders` | 29,248 |
| `backtest_trades` | 26,093 |
| `backtest_positions_daily` | 58,559 |
| 当前复权快照（`is_current=1`） | 46 |

## 五、本次验证回测记录

| 项目 | 内容 |
| --- | --- |
| run_id | `cabbfe77035d40f3` |
| 策略 | `ma_trend` |
| 区间 | 2024-01-02 ~ 2026-11-09 |
| 创建时间 | 2026-11-11T11:16:57 |
| input_hash | `1972a83fc569e5c6` |
| `backtest_orders` 行数 | 941 |
| `backtest_trades` 行数 | 831 |
| `backtest_daily_nav` 行数 | 689 |
| `backtest_positions_daily` 行数 | 2,014 |

### 订单状态分布

| 状态 | 数量 |
| --- | ---: |
| `filled` | 603 |
| `rejected` | 185 |
| `partial` | 151 |
| `unfilled` | 2 |

### 状态一致性（该 run）

| 检查项 | 结果 |
| --- | ---: |
| 有成交却标 rejected/unfilled/expired | 0 |
| 有剩余却标 filled | 0 |
| 超额成交订单 | 0 |

## 六、历史数据完整性

| 项目 | 数值 |
| --- | ---: |
| 回测 run 总数 | 11 |
| 指标版本数 | 3 |
| 最新指标版本 | `v1.0.2-30b821a1af15` |
| 复权快照总数 | 139 |
| 混合快照 ETF | 0 |
| 无快照引用行情行 | 0 |
| 复权价缺失行 | 149 |

11 个历史回测 run 全部保留在快照中，未删除、未覆盖任何记录。

### 指标版本分布

| 版本 | 行数 |
| --- | ---: |
| `v1.0.0-30b821a1af15` | 116,764 |
| `v1.0.1-30b821a1af15` | 116,764 |
| `v1.0.2-30b821a1af15` | 116,764 |

## 七、Git 提交说明

数据库、日志、虚拟环境、缓存均未提交到 GitHub / Gitee。
`.gitignore` 已排除 `dist/`、`*.zip`、`data/*.db`，快照包不进入版本库。
快照通过文件路径单独交付。
