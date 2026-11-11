# 阶段2.1 API 与看板测试报告

- 测试时间：2026-11-09
- 命令：`python scripts\smoke_test_servers.py`
- 结果：**全部通过**
- 结果文件：`logs/server_smoke_test.json`

## 1. HTTP 实测

| 接口 | 结果 |
| --- | --- |
| `/health` | 200；46 只 ETF、116,609 条行情、139 条历史快照、4 次复权刷新、140 次指标运行、233,528 条指标行（含旧版本） |
| `/api/etf-pool` | 200；46 只 |
| `/api/market-data/summary` | 200；46 个当前快照、0 混合快照、149 条复权缺失 |
| `/api/market-data/510300?...` | 200；返回行情明细 |
| `/api/sync/runs` | 200 |
| `/api/adjustment/runs` | 200 |
| `/api/indicators/overview` | 200；46 只，当前版本 1.0.1，stale=0 |
| `/api/indicators/510300?...indicators=return_1d,ma20,rsi6` | 200；返回新版本指标，snapshot=110，stale=false |

## 2. 版本验证

- 默认 API 返回 `v1.0.1-30b821a1af15`。
- 显式查询 `version=v1.0.0-30b821a1af15` 仍返回 200，旧版本未删除。
- 当前周期指标快照未过期；旧版本行也可读取，并由 API 判断快照是否当前。

## 3. Streamlit

- 主看板 AppTest：0 异常，15 个指标卡、5 个数据表。
- 指标页 AppTest：0 异常，12 个指标卡、3 个数据表、6 个标签页。
- 页面默认读取当前版本，显示 CAGR、EMA、MACD、RSI、波动率、回撤、ATR、质量和快照。
- 实际数据来自 SQLite；没有模拟行情。

## 4. 错误处理

离线 API 测试已验证：

- 非法代码/日期/指标 → 400。
- 未计算 ETF / 不存在版本 → 404。
- 日期区间无数据 → 404。
- 复权快照变化后 → `stale=true`。
- ranking 带“不构成投资建议”声明。

## 5. 结论

- 指标 API 与看板可正常读取阶段2.1新版本。
- 旧版本历史指标仍可访问。
- 快照、版本、数据质量字段正常返回。
