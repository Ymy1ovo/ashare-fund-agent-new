# 阶段1B.1 单元/集成测试报告

- 测试命令：`.\.venv\Scripts\python.exe -m pytest -v`
- 测试结果：**44 passed**
- 耗时：约 6.85 秒
- 测试性质：全部离线，使用临时 SQLite 数据库；不访问外部网络
- 日志：`logs/pytest_phase1b1.log`
- 唯一警告：Starlette 提示 `httpx` TestClient 未来改用 httpx2，不是测试失败

## 1. 新增测试与验收项

| 要求 | 测试用例 | 结果 |
| --- | --- | --- |
| 前复权历史数据完整刷新 | `test_full_refresh_updates_adjusted_and_keeps_raw_ohlc` | 通过 |
| 新旧调整基准更新 | `test_refresh_uses_new_basis_and_retires_old_snapshot` | 通过 |
| 原始 OHLC 不被修改 | `test_full_refresh_updates_adjusted_and_keeps_raw_ohlc` | 通过 |
| 接口失败时旧数据不丢失 | `test_refresh_failure_and_empty_preserve_old_snapshot` | 通过 |
| 空数据不覆盖旧数据 | `test_refresh_failure_and_empty_preserve_old_snapshot` | 通过 |
| 部分基金失败不影响其他基金 | `test_partial_refresh_is_isolated_and_marks_missing` | 通过 |
| 不同调整快照能够识别 | `test_refresh_uses_new_basis_and_retires_old_snapshot` | 通过 |
| 重复刷新不产生重复行情 | `test_refresh_is_repeatable_without_duplicate_prices` | 通过 |
| 原始同步不触碰复权字段 | `test_raw_sync_does_not_touch_adjusted_fields` | 通过 |
| 旧库迁移 | `test_migrate_old_schema_preserves_data` | 通过 |
| API 行情查询 | `test_api_summary_and_detail`、`test_api_rejects_bad_query` | 通过 |

## 2. 测试文件统计

| 文件 | 用例数 |
| --- | ---: |
| `tests/test_adjustment.py` | 6 |
| `tests/test_api_market_data.py` | 2 |
| `tests/test_database.py` | 1 |
| `tests/test_database_migration.py` | 3 |
| `tests/test_etf_pool_file.py` | 3 |
| `tests/test_ingest.py` | 4 |
| `tests/test_market_data.py` | 4 |
| `tests/test_normalize.py` | 8 |
| `tests/test_profile_parser.py` | 2 |
| `tests/test_source_quality.py` | 5 |
| `tests/test_timeout.py` | 2 |
| `tests/test_validator.py` | 4 |
| 合计 | **44** |

## 3. 关键断言

- 完整刷新后所有行 `adjustment_snapshot_id` 相同，`adjusted_close` 使用新快照值。
- 第二次刷新产生新快照，旧快照 `is_current=0`，所有行切换到新快照。
- 刷新前后原始 OHLC 字段逐行一致。
- 请求抛异常或 qfq 为空时，当前快照 ID、`adjusted_close` 和行情行数均不变。
- 部分日期缺少 qfq 时，状态为 `partial`；所有行引用同一新快照，缺失行的 `adjusted_close` 为空。
- 重复刷新不增加 `etf_daily_prices` 行数。
- 原始行情增量 UPSERT 不会覆盖已有 `adjusted_close` 或快照引用。
- 迁移旧库保留原有行，并新增快照字段/表。
- 测试数据库均为临时库，未清空或修改正式数据库。
- `tests/conftest.py` 增加 session 级正式库守卫：测试前后比较正式数据库的 mtime/size，若测试修改正式库会直接失败；本次 44 项测试通过且守卫通过。

## 4. 复跑方式

```powershell
cd D:\ymy\jj-agent
.\.venv\Scripts\Activate.ps1
python -m pytest -v
```
