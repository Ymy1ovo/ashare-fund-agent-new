# 阶段1B.1 API 与看板测试报告

- 测试时间：2026-11-09
- 测试方式：`scripts/smoke_test_servers.py` 真实启动 FastAPI 与 Streamlit，完成后自动关闭
- 结果文件：`logs/server_smoke_test.json`
- 结果：**全部通过**

## 1. HTTP 实测

| 检查 | 结果 |
| --- | --- |
| `GET /health` | 200；46 只 ETF、116,609 条行情、5 次原始同步、4 次复权刷新、139 条历史快照记录 |
| `GET /api/etf-pool` | 200；46 只 |
| `GET /api/market-data/summary` | 200；`current_snapshot_etfs=46`，`mixed_snapshot_etfs=0`，`adjusted_missing_records=149` |
| `GET /api/market-data/510300?...&limit=5` | 200；`total=6`，返回 5 条；包含 `adjustment_snapshot_id` 等快照字段 |
| `GET /api/sync/runs?limit=1` | 200；返回 1 条 |
| `GET /api/adjustment/runs?limit=1` | 200；返回 1 条 |
| Streamlit `/_stcore/health` | 200；ok |
| Streamlit 页面脚本（AppTest） | 0 异常；5 个数据表；指标显示 46 只、116,609 条、46 个当前快照、0 个混合快照 |

summary 中的调整快照信息：

```json
{
  "current_snapshot_etfs": 46,
  "partial_snapshot_etfs": 2,
  "failed_current_snapshots": 0,
  "mixed_snapshot_etfs": 0,
  "adjusted_missing_records": 149,
  "last_adjustment_refresh_at": "2026-11-09T15:45:11",
  "last_adjustment_refresh_status": "partial",
  "last_adjustment_run_id": 4
}
```

## 2. 看板实测指标

- 观察池 ETF：46
- 已入库 ETF：46
- 历史行情记录：116,609
- 异常记录：193
- 有当前快照 ETF：46
- 部分覆盖 ETF：2
- 混合快照 ETF：0
- 复权价缺失记录：149
- 最近复权刷新：2026-11-09T15:45:11，partial

## 3. 离线 API 测试

- `test_api_summary_and_detail`：summary、日期范围、limit/offset、快照字段、adjustment runs 空列表。
- `test_api_rejects_bad_query`：非法代码 400、非法日期 400、日期逆序 400、未知代码 404、limit=0 422。

结果：2/2 通过。

## 4. 结论

- API 可读取实际入库的 116,609 条行情。
- summary 返回快照完整性信息，能直接看出混合快照为 0。
- 明细接口返回行级快照 ID 与采集时间。
- 看板能显示当前快照、部分覆盖、混合快照和复权缺失指标。
- FastAPI 与 Streamlit 均正常启动，测试后无残留监听。
