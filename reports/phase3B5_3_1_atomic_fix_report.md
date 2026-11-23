# 阶段3B-5.3.1 受控接入事务原子性与数据指纹修复

- 基线 HEAD：`9e2a1176f090b7aae57b2475b46da0678dcd43a0`
- 执行日期：2026-11-23
- 修改模块：`app/fund/ingest_user_funds/_impl.py`
- 新增测试：`tests/test_3b5_3_1_atomic.py`

> **本轮只修数据安全，不重写接入模块，不扩大项目范围。**

---

## 0. 结论先行

| 问题 | 修复前 | 修复后 |
| --- | --- | --- |
| P0-1 单基金原子事务 | 5 个仓储各自独立连接，无整体回滚 | **同一 conn + BEGIN IMMEDIATE，任一异常整体 ROLLBACK** |
| P0-2 内容指纹 | 行数 + 字段长度摘要，同长度改动漏检 | **逐行逐列稳定序列化 SHA256** |
| P1-1 A/C 归组 | 公司缺失时仅凭名称合并 | **双方公司均非空且一致才合并** |
| P1-2 dry-run 测试 | 只算两次指纹，没跑流程 | **真跑 CLI，校验不调外部接口、不写库** |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

---

## 1. P0-1：真正的单基金原子事务

### 1.1 问题

原来的接入流程依次调用 5 个仓储方法，每个方法内部 `with get_conn(...)`
各自开连接、各自 commit —— 任意一步失败，前面已提交的写入留在库里。

### 1.2 修复方式（最小改动）

**第一步**：给仓储层加一个连接选择器 `use_conn()`（`app/fund/repo_base.py`）：

```python
@contextmanager
def use_conn(db_path=None, conn=None):
    if conn is not None:
        yield conn          # 复用外部连接，不 commit/rollback
        return
    with get_connection(db_path) as own:
        yield own
```

**第二步**：5 个写入方法增加可选 `conn` 参数，走 `use_conn`：

| 模块 | 方法 |
| --- | --- |
| `repository.py` | `upsert_master` / `upsert_share_class` |
| `repo_nav.py` | `upsert_nav_batch` / `upsert_dividend_batch` |
| `repo_quality.py` | `record` |

未传 `conn` 时行为**完全不变**，其他既有模块的事务语义没有任何改变。

**第三步**：接入器自己掌控事务边界：

```python
conn = sqlite3.connect(path, isolation_level=None)   # 关闭自动提交
conn.execute("BEGIN IMMEDIATE")
# … 所有写入都传 conn=conn …
conn.execute("COMMIT")        # 全部成功才提交
conn.execute("ROLLBACK")      # 任一异常整体回滚
```

`ingest_one()` 现在是薄包装：

```python
def ingest_one(self, code, *, allow_update=True):
    self._tx = None
    try:
        return self._ingest_impl(code, allow_update=allow_update)
    except Exception as exc:
        self._rollback_tx()          # 整体回滚
        return IngestResult(..., status=ST_FAILED, reason='写入失败，事务已回滚…')
    finally:
        if self._tx is not None:     # 不允许悬挂未提交事务
            self._rollback_tx()
```

**关键点**：不是「外层套一个事务上下文但仍然各自开连接」——
所有写入**确实共享同一个 conn**，因此回滚是真实的。

### 1.3 失败不掩盖

写入失败返回 `status=failed` + `fund_id=None` + `回滚` 字样，
**不会**返回 `ingested`。

---

## 2. P0-2：真实内容指纹

### 2.1 问题

旧实现只算「行数 + `LENGTH(unit_nav)` + `LENGTH(nav_date)` 之和」，
把 `1.005` 改成 `1.006` 这种同长度修改**完全无法识别**。

### 2.2 修复后算法

```python
for 每张 fund_* 表:
    cols = PRAGMA table_info(table)  # 排除 ingested_at/fetched_at/checked_at/source_updated_at
    for row in SELECT <cols> FROM table ORDER BY <稳定主键>:
        h.update('@row:' + '|'.join(_stable_value(v) for v in row))
sha256 = sha256(每表 <表名:行数:表摘要>)
```

`_stable_value()` 的类型前缀保证可区分：

| 值 | 序列化 |
| --- | --- |
| `None` | `@NULL` |
| `True` / `False` | `bool:1` / `bool:0` |
| `1` | `int:1` |
| `1.0` | `float:1.0` |
| `"1"` | `str:1` |
| `b"1"` | `bytes:31` |

**覆盖全部 10 张基金表**：`fund_master` / `fund_share_classes` /
`fund_nav_daily` / `fund_dividends` / `fund_manager_history` /
`fund_aum_history` / `fund_fee_rules` / `fund_subscription_status` /
`fund_lifecycle_events` / `fund_data_quality`。

为什么排除采集时间列：`ingested_at` 每次写入都会变，
若计入则「内容没变但重跑一次」会误判为数据变化，反而让指纹失去诊断价值。
它们的变化已由行数与业务字段体现。

---

## 3. P1-1：A/C/E 归组收紧

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 同名 + 同公司 | 合并 | **合并** |
| 同名 + 不同公司 | 不合并 | **不合并** |
| 同名 + 一方公司为空 | **可能合并**（缺陷） | **不合并**，标「需人工核验」 |
| 同名 + 双方公司都空 | **可能合并**（缺陷） | **不合并** |
| 不同基础名 | 不合并 | **不合并** |

`_find_same_entity()` 改为返回 `(fund_id | None, 判定说明)`，
判定说明会写进 `warnings`，供人工核验。

无模糊匹配、无名称相似度、无拼音/别名映射。

---

## 4. P1-2：dry-run 测试修复

旧测试只是连续算两次指纹，没有调用 dry-run 入口。

新测试真正调用 `_make_ingestor(dry_run=True)` 与 CLI `main([...])`，验证：

| 验证项 | 断言 |
| --- | --- |
| 不调用外部接口 | `calls == []`（打桩 `_fetch_basic_default` / `_fetch_nav_default`） |
| 不写库 | 全部 `fund_*` 表内容指纹前后一致 |
| 不建本体/份额/净值/分红/质量 | 各表行数为 0 |
| 单只 dry-run | `test_dry_run_truly_no_write` |
| 批量 dry-run | `test_dry_run_batch_no_write`（含非法行跳过） |
| 已存在基金 dry-run | `test_dry_run_reports_existing_without_touching` |

---

## 5. 故障注入测试（真实运行）

全部使用临时 SQLite + 注入式假抓取器，**不碰正式库**。

| # | 注入点 | 测试 | 结果 |
| ---: | --- | --- | --- |
| 1 | 本体写入抛异常 | `test_master_write_failure_rolls_back` | 指纹与接入前**完全一致** |
| 2 | 净值写入抛异常 | `test_nav_write_failure_rolls_back` | 指纹与接入前**完全一致** |
| 3 | 分红写入抛异常 | `test_dividend_write_failure_rolls_back` | 指纹与接入前**完全一致** |
| 4 | 质量记录写入抛异常 | `test_quality_write_failure_rolls_back` | 指纹与接入前**完全一致** |
| 5 | 失败后重新接入 | `test_retry_after_failure_succeeds` | **完整成功**（40 行净值） |
| 6 | 不掩盖失败 | `test_no_false_success_on_write_failure` | 返回 `failed`，非 `ingested` |
| 7 | A/C 公司缺失 | `test_same_name_missing_company_not_grouped` | 不合并 + 「人工核验」 |
| 8 | 同长度值修改 | `test_fingerprint_changes_on_same_length_edit` | 指纹**变化** |
| 9 | 行数不变只改一条 | `test_fingerprint_changes_on_row_count_unchanged_value_edit` | 指纹**变化** |

每项失败后都额外校验：`fund_share_classes` 中不残留被接入的份额代码。

---

## 6. 正式数据库安全验证

**先备份**：`data/backups/fund_agent_before_3b5_3_1_before_20261123_110917.db`

**不重新接入已存在的 5 个份额、不删除、不重建、不覆盖**——本轮只改代码。

| 检查 | 结果 |
| --- | --- |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0 违规** |
| 清盘本体（terminated） | **41**（不变） |
| 生命周期事件 | **49**（不变） |
| 原 12 份额 | **12/12 全部存在** |
| 原 9 本体 | **9** |
| 本轮 5 份额 | **5/5 全部存在** |
| 本轮 3 本体 | **3** |
| ETF 行情指纹 | `d54727c0…`（不变） |

### 修复前后真实内容指纹

| 时点 | 内容指纹 SHA256 |
| --- | --- |
| 修复前（备份时） | `0c867be4960f4f29ebfe03725c292fac82aad40bcfd7781a2cf476c0eb8b9658` |
| 修复后（当前库） | `0c867be4960f4f29ebfe03725c292fac82aad40bcfd7781a2cf476c0eb8b9658` |
| 备份库（独立文件） | `0c867be4960f4f29ebfe03725c292fac82aad40bcfd7781a2cf476c0eb8b9658` |

**三者完全一致** → 本轮代码改动**没有触碰任何正式数据**。

| 表 | 行数 |
| --- | ---: |
| `fund_master` | 53 |
| `fund_share_classes` | 80 |
| `fund_nav_daily` | 47718 |
| `fund_dividends` | 44 |
| `fund_manager_history` | 21 |
| `fund_aum_history` | 683 |
| `fund_fee_rules` | 90 |
| `fund_subscription_status` | 12 |
| `fund_lifecycle_events` | 49 |
| `fund_data_quality` | 31 |

---

## 7. 测试结果（实际执行）

### 7.1 新增专项

```
$ pytest tests/test_3b5_3_1_atomic.py -q
20 passed
```

| 分组 | 数量 |
| --- | ---: |
| 内容指纹 | 6 |
| 原子事务回滚 | 6 |
| A/C 归组收紧 | 5 |
| dry-run | 3 |

### 7.2 3B-5.3 专项回归

```
$ pytest tests/test_3b5_3_user_ingest.py -q
27 passed
```

### 7.3 3B-5.1 / 3B-5.2 回归

```
$ pytest tests/test_3b5_1_fund_research.py tests/test_3b5_2_code_lookup.py -q
135 passed
```

### 7.4 全量

```
$ pytest -q
1465 passed, 1 warning in 391.04s (0:06:31)
```

1465 = 3B-5.3 的 1445 + 本轮 20。

---

## 8. 静态检查 vs 实际执行

| 项 | 性质 |
| --- | --- |
| `ast.parse` 语法检查 | **静态** |
| `use_conn()` 分支逻辑审阅 | **静态** |
| 20 项新增测试 | **实际执行** |
| 27 + 135 项回归 | **实际执行** |
| 1465 项全量 | **实际执行** |
| 正式库指纹比对 | **实际执行** |
| `integrity_check` / `foreign_key_check` | **实际执行** |

---

## 9. 边界遵守

| 禁止项 | 状态 |
| --- | --- |
| 修改数据库 Schema | ❌ 未做 |
| 修改迁移文件 | ❌ 未做 |
| 改变其他模块事务语义 | ❌ 未做（`conn` 为可选参数，不传即旧行为） |
| 重采集数据 | ❌ 未做 |
| 重新接入已存在 5 份额 | ❌ 未做 |
| 修改 41 清盘 / 49 事件 | ❌ 未做（指纹一致） |
| 重写整个接入模块 | ❌ 未做（只加事务边界与指纹算法） |
| 开放回测/排名 | ❌ 未做 |

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
