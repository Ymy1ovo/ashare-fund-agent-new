# 阶段1B 单元/集成测试报告

- 测试命令：`.\.venv\Scripts\python.exe -m pytest -v`
- 测试结果：**38 passed**
- 耗时：约 5.71 秒
- 测试性质：全部离线，使用临时 SQLite 数据库；不访问 AKShare/东方财富网络
- 日志：`logs/pytest_phase1b.log`
- 唯一警告：Starlette 提示 `httpx` TestClient 已弃用（建议 httpx2），不是测试失败

## 1. 覆盖矩阵

| 验收项 | 对应用例 | 结果 |
| --- | --- | --- |
| 历史行情标准化 | `test_market_data.py`、`test_normalize.py` | 通过 |
| 行情日期排序 | `test_latest_valid_bar_*`、`test_prepare_history_sorts_and_merges_adjusted` | 通过 |
| 最新价格提取 | `test_latest_valid_bar_*`、`test_latest_record_uses_same_valid_row` | 通过 |
| 数据库批量写入 | `test_upsert_is_idempotent_and_preserves_existing_adjusted` | 通过 |
| 重复写入不重复 | `test_upsert_is_idempotent_and_preserves_existing_adjusted` | 通过 |
| 增量同步 | `test_incremental_sync_appends_without_duplicates` | 通过 |
| 空数据保护 | `test_empty_upsert_does_not_delete`、`test_empty_sync_does_not_overwrite_existing` | 通过 |
| 异常数据识别 | `test_ohlc_anomaly_is_marked_but_not_fixed`、`test_anomaly_rows_are_stored_with_suspect_status` | 通过 |
| 数据源失败隔离 | `test_failure_isolation_and_empty_protection` | 通过 |
| API 行情查询 | `test_api_summary_and_detail`、`test_api_rejects_bad_query` | 通过 |
| 超时真正终止子进程 | `test_timeout_reports_terminated_child` | 通过 |
| 旧库平滑迁移 | `test_migrate_old_schema_preserves_data` | 通过 |

## 2. 测试文件统计

| 文件 | 用例数 | 结果 |
| --- | ---: | --- |
| `tests/test_api_market_data.py` | 2 | 通过 |
| `tests/test_database.py` | 1 | 通过 |
| `tests/test_database_migration.py` | 3 | 通过 |
| `tests/test_etf_pool_file.py` | 3 | 通过 |
| `tests/test_ingest.py` | 4 | 通过 |
| `tests/test_market_data.py` | 4 | 通过 |
| `tests/test_normalize.py` | 8 | 通过 |
| `tests/test_profile_parser.py` | 2 | 通过 |
| `tests/test_source_quality.py` | 5 | 通过 |
| `tests/test_timeout.py` | 2 | 通过 |
| `tests/test_validator.py` | 4 | 通过 |
| 合计 | 38 | 通过 |

## 3. 关键断言

### 超时

- 超时调用抛出 `FetchTimeoutError`。
- 错误文本包含“已终止子进程”和 `pid=...`。
- 返回时间受控，没有无限等待。
- 子进程结束确认发生在抛错之前。

### 行情

- 乱序日期的最后有效记录取最大日期，且收盘价与日期来自同一行。
- 无效日期、无效收盘价、未来日期被过滤并计数。
- 同一天重复记录保留排序后的最后一条，冲突被记录。
- OHLC 矛盾行标记 `suspect`，原始 high/low 不被改写。
- 前复权 close 合并为 `adjusted_close`，原始 OHLC 保留。

### 入库

- UPSERT 重复执行后记录数不变。
- 已存在的 adjusted_close 不被空值覆盖。
- 空输入返回 0，不删除已有数据。
- 单只基金失败不阻止其他基金写入。
- 增量同步只追加/刷新目标日期，最终记录数正确。
- 空同步不覆盖旧数据。

### API

- summary、日期范围、limit/offset、404/400/422 均验证。
- 测试库与正式库完全隔离。

## 4. 复跑方式

```powershell
cd D:\ymy\jj-agent
.\.venv\Scripts\Activate.ps1
python -m pytest -v
```

外部真实接口测试不属于本离线测试集，单独运行：

```powershell
python scripts\check_data_sources.py
```
