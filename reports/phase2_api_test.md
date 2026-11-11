# 阶段2 API 与看板测试报告

- 测试时间：2026-11-09
- 命令：`python scripts\smoke_test_servers.py`
- 结果：**全部通过**
- 结果文件：`logs/server_smoke_test.json`
- 测试方式：真实启动 FastAPI + Streamlit，HTTP 请求完成后关闭；另外用 Streamlit AppTest 执行两个页面脚本

## 1. HTTP 实测

| 接口 | 结果 |
| --- | --- |
| `/health` | 200；46 只 ETF、116,609 条行情、139 条历史快照、4 次复权刷新、94 次指标运行、116,764 条指标行 |
| `/api/etf-pool` | 200；46 只 |
| `/api/market-data/summary` | 200；46 个当前快照、0 混合快照、149 条复权缺失 |
| `/api/market-data/510300?...` | 200；返回行情明细 |
| `/api/sync/runs` | 200；1 条 |
| `/api/adjustment/runs` | 200；1 条 |
| `/api/indicators/overview` | 200；46 只 ETF 有指标数据，stale=0 |
| `/api/indicators/510300?...indicators=return_1d,ma20,rsi6` | 200；6 行，快照未过期 |

## 2. 指标 API 错误处理

离线测试已验证：

- 非六位代码 → 400。
- 非法日期 → 400。
- 不支持的指标名 → 400。
- 不存在的 ETF → 404。
- 指标尚未计算 → 404。
- 不存在的版本 → 404。
- 复权快照变化后，接口返回 `stale=true`、`snapshot_is_current=false`。

`/api/indicators/ranking` 返回排序结果和“仅按历史指标排序，不构成投资建议”声明。

## 3. Streamlit

- 主看板 `dashboard/app.py`：AppTest 0 异常，15 个指标卡、5 个数据表。
- 指标页 `dashboard/pages/2_量化指标.py`：AppTest 0 异常，12 个指标卡、3 个数据表、6 个标签页。
- 指标页实际读取 510300 的 3,511 行指标，显示快照、版本、质量和图表；未使用模拟行情。
- 指标页支持 ETF、日期区间、版本选择，并分概览/收益/趋势/动量/波动回撤/质量六个标签页。

## 4. 结论

- 指标 API 读取的是数据库实际计算结果，不在接口中临时计算或编造数值。
- 缺少指标数据时返回明确错误，不返回空壳成功。
- 快照/版本可追踪，过期指标有明确标记。
- 看板能够读取真实计算结果；没有足够历史时显示空值，不填充。
