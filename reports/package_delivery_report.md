# 交付打包测试报告

- 测试文件：`tests/test_package_project.py`
- 结果：**3 passed，0 failed**
- 本次全量测试：**96 passed，0 failed**（阶段2.2 93项 + 打包3项）
- 日志：`logs/pytest_package_delivery.log`

## 1. 测试内容

| 测试 | 验证 |
| --- | --- |
| `test_source_only_excludes_db_and_logs` | 源码包含 app/dashboard/scripts/tests/migrations/README/data 白名单；不含数据库、logs、缓存；含 manifest/SHA256 |
| `test_data_snapshot_is_consistent_and_does_not_touch_source` | SQLite backup、integrity_check=ok、源库字节不变、含迁移文件、manifest |
| `test_full_release_contains_both_packages_and_reports` | full-release 含 source-only、data-snapshot、测试报告、变更/发布说明 |

## 2. 三种模式

- `source-only`：默认轻量源码包，不含 `data/fund_agent.db`、`logs/`、`.venv/`、缓存、真实 `.env`。
- `data-snapshot`：独立数据库快照，SQLite 一致性备份，执行 `PRAGMA integrity_check`，记录行情/指标/快照数量、版本、时间、SHA256。
- `full-release`：嵌套源码包和数据快照包，附测试报告、数据质量报告、CHANGELOG、RELEASE_NOTES。

## 3. 安全断言

- 打包使用 SQLite backup API，不直接复制写入中的数据库。
- 快照前后源库 SHA256 一致，未修改原始数据库。
- ZIP 写入后执行完整性检查，缺少必要条目即失败。
- 失败时删除未完成 ZIP；CLI 返回非零。
- 每个包输出 `manifest.json`、SHA256 和侧车 manifest。
