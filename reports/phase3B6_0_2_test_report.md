# 阶段3B-6.0.2 测试报告

- 基线 HEAD：`4f5d3add205dfc5370d04cda19e3f42dd0e1ece7`
- 执行日期：2026-11-23

> 以下区分三类：**真实执行测试** / **静态检查** / **数据源实际调用**。

---

## 1. 真实执行测试

### 1.1 本轮新增专项

```bash
$ pytest tests/test_3b6_0_2_index_layer.py -q
46 passed in 16.06s
```

| 任务书第八节要求 | 用例 | 实现 |
| --- | ---: | --- |
| 1. 指数代码唯一性 | 2 | 主键 + 首批 10 代码不重复 |
| 2. 同指数同日期无重复 | 3 | 主键 + 批次去重 + DB 层拒绝 |
| 3. 重复采集幂等 | 1 | 二次采集 inserted=0, unchanged=30 |
| 4. 增量更新正确 | 1 | 只新增 5 条，30 条不变 |
| 5. 单指数失败不影响其他 | 2 | 3 指数中 1 失败，另 2 正常 |
| 6. 收盘值空值被拒绝 | 1 | quality_hard_passed=False，0 行入库 |
| 7. 日期重复被拒绝 | 1 | 质量层硬性失败 |
| 8. 日期倒序被发现 | 1 | date_ascending=False |
| 9. 非数值/负值被拒绝 | 2 | 负值 + 字符串均拒绝 |
| 10. OHLC 部分缺失只警告 | 1 | 入库成功，ohlc_complete=0 |
| 11. 疑似缺口保留不确定性 | 1 | gap_is_real_missing is None |
| 12. 缺失日期不被填充 | 1 | 行数=真实返回行数 |
| 13. 价格/全收益严格区分 | 2 | basis_kind 不同 + price 拒绝 |
| 14. unknown 不能作全收益 | 2 | 抛 ReturnBasisError |
| 15. 数据来源可追溯 | 1 | run 表 + 行 level source |
| 16. 指纹识别内容变化 | 2 | 行级 + 整段 |
| 17. 缺成分不标完整 | 3 | 空/缺债券/缺现金 |
| 18. 缺权重不伪造 | 1 | weight 仍为 None |
| 19. 事务失败回滚 | 1 | 外键违规后主表仍为 0 |
| 20. SQLite 外键有效 | 3 | PRAGMA=1 + 违规拒绝 + check 干净 |
| 21. 正式基金库不受影响 | 2 | 指纹一致 + 表隔离 |
| 22. 不同口径不混拼 | 2 | 单一 source + 逐指数口径 |
| 附加：基线行标 suspect | 1 | 有效区间排除 |
| 附加：门禁不变 | 1 | — |

### 1.2 3B-6.0.1 系列回归

```bash
$ pytest tests/test_3b6_0_2_index_layer.py \
        tests/test_3b6_0_1_benchmark_audit.py \
        tests/test_3b6_0_1_1_index_verify.py -q
107 passed in 54.55s
```

| 文件 | 用例数 |
| --- | ---: |
| `test_3b6_0_2_index_layer.py`（本轮新增） | 46 |
| `test_3b6_0_1_benchmark_audit.py` | 33 |
| `test_3b6_0_1_1_index_verify.py` | 28 |

### 1.3 3B-5.5 系列回归

```bash
$ pytest tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
112 passed in 115.14s (0:01:55)
```

### 1.4 全量

```bash
$ pytest -q
1736 passed, 1 warning in 549.17s (0:09:09)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1736** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 549.17 秒 |

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-6.0.1.1 | 1690 |
| **3B-6.0.2** | **1736** |

1690 + 46 = 1736。

---

## 2. 数据源实际调用

本轮**真实调用**中证指数官网接口 10 次（每指数 1 次，含重试）。

| 项 | 结果 |
| --- | --- |
| 接口 | `akshare.stock_zh_index_hist_csindex` |
| 成功 | **10 / 10** |
| 失败 | 0 |
| 重试机制 | 6 次 × 45 秒 |
| 实测反爬 | 密集请求后 403，冷却约 6 分钟后恢复 |

---

## 3. 静态检查（不计入 1736）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | 静态 |
| 迁移 SQL 建表语句计数 | 静态 |
| 报告数据与库查询比对 | 静态 |

---

## 4. 数据库迁移与守恒

| 项 | 值 |
| --- | --- |
| 迁移文件 | `migrations/phase3b6_0_2_index_data_layer.sql` |
| 新增表 | 6 |
| 新增索引 | 12 |
| 修改既有表 | **0** |
| 建表前备份 | 已执行（`data/fund_agent.backup_3b6_0_2_*.db`） |

### 4.1 基金表行数（迁移前后一致）

| 表 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| `fund_master` | 60 | **60** |
| `fund_share_classes` | 89 | **89** |
| `fund_nav_daily` | 80,083 | **80,083** |
| `fund_lifecycle_events` | 49 | **49** |
| `etf_daily_prices` | 116,609 | **116,609** |

### 4.2 指纹

| 指纹 | 迁移前 | 迁移后 |
| --- | --- | --- |
| 内容指纹 | `11c56eba…c05116` | `11c56eba…c05116` |
| ETF 行情指纹 | `d54727c0…bbcac49` | `d54727c0…bbcac49` |

**完全一致，基金数据零改动。**

---

## 5. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `migrations/phase3b6_0_2_index_data_layer.sql` | 新增 | 6 表 12 索引 |
| `app/fund/index_layer.py` | 新增 | 数据层 CRUD + 专用连接 |
| `app/fund/index_ingest.py` | 新增 | 受控采集 |
| `app/fund/index_returns.py` | 新增 | 收益口径校验 |
| `app/fund/composite_benchmark.py` | 新增 | 复合基准结构 |
| `app/fund/benchmark_component_spec.py` | 新增 | 15 条成分规格 |
| `scripts/build_3b6_0_2_index_layer.py` | 新增 | 迁移+采集脚本 |
| `scripts/build_3b6_0_2_composite.py` | 新增 | 复合基准入库 |
| `tests/test_3b6_0_2_index_layer.py` | 新增 | 46 项 |
| `app/fund/research/index_verify.py` | **修改** | 支持传入连接读日历 |
| `app/database/db.py` | **未改** | 全局外键行为不变 |
| `engine.py` / `indicators.py` / `quality.py` | **未改** | — |

**关于 `index_verify.py` 的修改**：

新增可选参数 `calendar_conn`。原因：采集时外层持有写事务，
`check_history_quality` 另开连接读 `trade_calendar` 会锁等待失败，
静默降级为工作日代理，导致缺口口径不一致（实测 930930 从 56 处变 115 处）。
改动向后兼容，原调用方式行为不变。

---

## 6. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
