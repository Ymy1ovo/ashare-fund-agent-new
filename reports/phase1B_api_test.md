# 阶段1B API 与看板测试报告

- 测试时间：2026-11-09
- 测试对象：实际项目数据库 `data/fund_agent.db`
- 启动方式：`python scripts/smoke_test_servers.py` 真实启动 uvicorn 与 Streamlit，测试完成后自动关闭
- 结果文件：`logs/server_smoke_test.json`
- 结果：**全部通过**

## 1. 实际 HTTP 结果

| 检查 | 结果 |
| --- | --- |
| `GET /health` | 200；`etf_pool_count=46`，`price_record_count=116609`，`sync_run_count=4`，`data_source_test_count=18` |
| `GET /api/etf-pool` | 200；返回 46 只 ETF |
| `GET /api/market-data/summary` | 200；`etf_total=46`，`etf_ingested=46`，`total_records=116609`，`missing_etf_count=0`，`anomaly_record_count=193` |
| `GET /api/market-data/510300?start_date=2026-11-01&end_date=2026-11-09&limit=5` | 200；`total=6`，返回 5 条，日期范围参数生效，`limit` 生效 |
| `GET /api/sync/runs?limit=1` | 200；返回 1 条同步运行记录 |
| Streamlit `/_stcore/health` | 200；`ok` |
| Streamlit 页面脚本实际执行（AppTest） | 0 异常；4 个数据表；显示 46 只/116,609 条/193 条异常 |

`/api/market-data/summary` 实际返回的最近同步信息：

```json
{
  "last_sync_at": "2026-11-09T15:04:38",
  "last_sync_status": "success",
  "last_sync_run_id": 4,
  "last_price_collected_at": "2026-11-09T15:04:33"
}
```

质量计数：

```json
{
  "valid": 116416,
  "warning": 193
}
```

## 2. 离线 API 测试

`pytest` 中的 API 测试使用临时 SQLite 数据库，不接触正式库、不访问网络：

- `test_api_summary_and_detail`：验证 summary 数量、覆盖区间、日期范围、limit/offset、复权字段返回。
- `test_api_rejects_bad_query`：验证非法代码 400、非法日期格式 400、开始日期晚于结束日期 400、未知代码 404、limit=0 返回 422。

结果：2/2 通过。

## 3. 启动与关闭

- FastAPI 与 Streamlit 均由脚本真实启动后检查 HTTP 健康状态。
- 测试结束后脚本调用 terminate，必要时 kill，并等待进程退出。
- 端口 8765/8766 未发现残留监听。

## 4. 结论

- 行情 API 可以读取实际入库的 116,609 条数据。
- 日期范围与条数限制已验证。
- 摘要接口返回每只 ETF 的起止日期、记录数和异常数。
- Streamlit 看板可以启动并读取同一数据库。
- 未发现 API 层面的失败项。
