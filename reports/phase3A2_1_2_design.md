# 阶段3A.2.1.2 设计说明：验证体系工程收尾

- 编写时间：2026-11-12
- 基线提交：`9806f2e0061f0bb8a33b1925a59dc9faebceaa76`
- 范围：只做工程可靠性验证，不进入 3B，不开发新策略
- **当前状态（阶段3A.2.1.2.3 之后的统一口径）**：
  - 全量测试 **373 项**通过（原有 337 项全部保留 + 新增 36 项），0 failed / 0 skipped / 0 未执行；
  - 已实测并发：2 线程、4 线程、2 独立进程、公开入口 2 线程、公开入口 2 独立进程、临时库 2 线程任务；
  - 执行模型：**全流程串行排队**（`full-pipeline-serial`，`compute_parallel=False`）；
  - **未验证**：8 任务及以上、跨机器共享数据库、小时级长压测；
  - 真实券商交割单核验仍为 `deferred_external_evidence`；
  - 策略结论：`ma_trend` **没有通过稳健性验证**。
- 本文出现的 351 / 365 / 369 等数字均为**历史阶段**中间状态，不是当前数字。

## 1. 三项任务的设计

| # | 任务 | 新增模块 | 设计要点 |
| ---: | --- | --- | --- |
| 1 | sparse 删除比例敏感性扫描 | `app/validation/sensitivity_scan.py` | 6 比例 × 5 模式，独立副本，固定种子 |
| 2 | 并发验证安全性 | `app/validation/concurrency.py` | 进程内锁 + 文件锁串行写入，明确声明 |
| 3 | `sell_proceeds_below_fee` 链路 | `app/validation/sell_probe.py` | 受控副本跑完整 Engine 流程 |

## 2. 任务一：敏感性扫描

### 2.1 删除模式实现

| 模式 | 实现 | 保护措施 |
| --- | --- | --- |
| A 随机零散 | 每只 ETF 用 `random.Random(seed)` 独立抽样删除 ratio 比例 | 保护首尾各 3 个交易日 |
| B 连续区间 | 中部删除连续 `len × ratio` 个交易日 | 随机起点，保证连续 |
| C 持仓期间 | 用基准回测提取的真实持仓日 | 无持仓则跳过该 ETF |
| D 信号附近 | 用基准回测提取的信号日及其次日 | 保护首尾各 3 个交易日 |
| E 缺失后恢复 | 复用 B 的中部连续删除，前后行情完整 | 用于检验恢复日行为 |

**0% 基线**：任何模式下 `ratio == 0` 都不删除任何行，作为完整数据基准组。

**为什么保护首尾 3 日**：如果起始估值日被删空，Engine 会因
`缺少估值价格` 直接报错——那是「区间缺失」而不是「稀疏缺失」，
会掩盖本场景要考察的问题。这是明确的设计选择，不是绕过测试。

### 2.2 执行范围

| 池 | 比例 | 模式 | 场景数 | 实际执行 |
| --- | --- | --- | ---: | --- |
| 代表性池（6 只） | 6 | 5 | 30 | **全部执行** |
| 全池（41 只） | 6 | 2（随机+连续） | 12 | **全部执行** |
| 合计 | — | — | **42** | **全部执行** |

全池未跑持仓/信号/恢复三种模式，原因是全池单场景约 70 秒，
30 场景需 35 分钟。这三种模式已在代表性池完整覆盖。
报告明确标注未执行组合，**不标记为成功**。

### 2.3 状态判定

| 状态 | 条件 |
| --- | --- |
| `failed` | 负现金天数 > 0，或引擎异常 |
| `insufficient` | 有效日收益 < 2 天，或该比例下未删除任何行情 |
| `partial` | 存在收益观测缺失（`missing_return_days > 0`） |
| `success` | 无缺失、无异常 |

**注意**：状态只反映「数据完整性影响」，与策略自身产生多少部分成交无关。
早期版本把 `partial_orders > 0` 也算 partial，导致 0% 基线也被判 partial，
已修正。

### 2.4 时间序列处理

- 回测仍走 `BacktestEngine` → `risk_return_series()` → `return_sample_stats()`
- 缺失日保留在原始交易日索引上，`pct_change(fill_method=None)`
- `stale_price` 只影响估值，不进入有效收益样本
- 统计口径版本 `return-sample-stats-v1`，与前几轮一致

## 3. 任务二：并发安全

### 3.1 执行模型（以最终实现为准）

> **本节标题早期写作「两层并发模型」，结论已修正。**
> 最终实现是**单一层的全流程串行排队**，不存在「计算并行 + 写入串行」的两层结构。

```text
排队范围：整个验证任务（从取数到落库）
进程内锁：threading.Lock（同进程多线程互相排队，带超时）
跨进程锁：<数据库目录>/.validation_write.lock（文件锁，路径稳定）
SQLite  ：busy_timeout=5000，单写者
```

**明确声明**：

- SQLite 不支持多写并发，本项目**不做多写并发**；
- 也**不做计算并行**——验证全程读同一份行情、写同一个库，
  串行最安全且未见并行收益；
- 结果中 `execution_model="full-pipeline-serial"`、`compute_parallel=False`、
  `serialized_writes=True` 显式标注，不宣称任何并行计算能力。

### 3.2 input_hash 与 data_fingerprint 的区分

首次四任务并发发现 `hash_consistency=false`，根因是校验逻辑取错字段：

- `data_fingerprint`：**只有行情内容**，同一份行情下所有任务必然相同
- `input_hash`：**配置 + ETF 池 + 数据指纹**，不同参数必然不同

修复后两者分别校验：

| 字段 | 校验规则 |
| --- | --- |
| `input_hash` | 同参数必同，不同参数必异 |
| `data_fingerprint` | 所有任务必须相同 |

### 3.3 失败隔离

`run_validation` 内部用 `try/except` 包裹，失败任务写入 `status=failed` +
`error_message`，不抛出到并发调度层，因此不影响其他任务。

## 4. 任务三：卖出费用不足

### 4.1 受控场景构造

从真实库 `backup()` 副本 → 写入受控行情 → 跑完整 Engine：

```text
第 1 天收盘：策略要求满仓 → 第 2 天开盘买入 1 份
第 3 天收盘：策略要求清仓 → 第 4 天开盘撮合卖出
```

严格 T+1：第 2 天买入的仓位在第 3 天才可卖，因此清仓信号必须落在第 3 天。

### 4.2 1 份持仓的构造

真实 ETF 最小 100 份，无法用低价 ETF 构造「成交额 < 5 元」的场景。
使用系统正式配置项 `instrument_overrides={code: {"lot_size": 1}}`
把最小交易单位覆盖为 1，这是配置能力而非绕过测试。

### 4.3 两个对照场景

| 场景 | 买入后现金 | 卖出净额 | 是否拒单 |
| --- | ---: | ---: | --- |
| 现金不足 | 2.02 元 | -4.63 元 | **是** |
| 现金足够 | 6.02 元 | -4.63 元 | **否** |

## 5. 修改文件清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/validation/sensitivity_scan.py` | **新增** | 删除模式、场景执行、汇总 |
| `app/validation/concurrency.py` | **新增** | 并发调度、写锁、哈希校验 |
| `app/validation/sell_probe.py` | **新增** | 受控库构造与完整链路执行 |
| `scripts/run_sensitivity_scan.py` | **新增** | 敏感性扫描 CLI |
| `tests/test_reliability.py` | **新增** | 14 项专项测试（阶段3A.2.1.2） |
| `tests/test_final_acceptance.py` | **新增** | 22 项专项测试（3A.2.1.2.1 的 14 + 3A.2.1.2.2 的 4 + 3A.2.1.2.3 的 4） |
| `reports/phase3A2_1_2_*.md` | **新增** | 6 份报告 |

**阶段3A.2.1.2.3 修改的文件**：

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/validation/runner.py` | **修改** | `lock_dir` / `lock_timeout` 参数；持锁标记下沉到真正拿锁之后 |
| `app/validation/concurrency.py` | **修改** | 去掉外层重复加锁；进程内锁加超时；同线程重入立刻报错；`input_hash` 读对库 |
| `tests/test_final_acceptance.py` | **修改** | 4 项源码字符串测试改写为行为断言，净增 4 项 |
| `reports/phase3A2_1_2_*.md` | **修改** | 六份报告重新校准（删除过期结论而非追加） |

**未修改**：`app/backtest/*`、`app/quant/*`、`app/data/*`、数据库结构、历史记录、
策略逻辑、历史行情、指标、回测与验证记录。

## 6. 数据安全设计

| 措施 | 说明 |
| --- | --- |
| 副本生成 | 全部用 `sqlite3.Connection.backup()`，非文件复制 |
| 场景隔离 | 每场景独立目录 + 独立 db 文件 |
| 源库指纹 | 扫描前后各算一次，不一致直接判失败 |
| 临时目录清理 | `finally` 中 `shutil.rmtree` |
| 历史保护 | 只读操作，不写历史表 |

## 7. 本轮不做

- 不进入 3B
- 不开发自动实盘
- 不接入券商接口
- 不新增交易策略
- 不调整 MA 策略参数
- 不修改历史行情/回测/validation
- 不重新开发佣金、税费、清仓逻辑

## 8. 外部证据依赖

**真实券商交割单核验：`deferred_external_evidence`。**

没有脱敏交割单，本轮不伪造、不模拟成真实对账结果。
`per_order` 佣金模型、最低佣金规则、T+0/T+1 判定仍属模拟假设。

## 9. 阶段3A.2.1.2.1 验收缺陷整改

| # | 缺陷 | 整改 |
| ---: | --- | --- |
| 1 | `delete_signal_adjacent()` 接收 ratio 但忽略 | 按 `round(可删信号数 × ratio)` 抽样，至少 1 个；记录四类计数 |
| 2 | CLI 未传 holding_dates / signal_dates | 先跑基准回测提取两组日期，再传入矩阵 |
| 3 | 并发模型声称「计算并行 + 写入串行」 | 改为**全流程串行排队**，`compute_parallel=False` |
| 4 | 跨进程锁目录随机 | 锁文件固定在正式库同目录 `.validation_write.lock` |
| 5 | `source_fingerprint()` 只用行数求和 | 复用 `market-fingerprint-v3` 完整内容哈希 |
| 6 | 报告把「回撤被高估」当结论 | 改为「相对完整数据基准的变化」，不判定净效应 |
| 7 | 报告把 74 笔笼统归因于现金充足 | 按护栏分界：护栏前 72 笔(分支不存在) + 护栏后 2 笔(现金充足) |

新增测试：`tests/test_final_acceptance.py` 14 项（3A.2.1.2.1）
+ 4 项（3A.2.1.2.2 入口锁）；
全量 337 → 351 → 365 → **369 项**（3A.2.1.2.2 结束时的状态）。

## 10. 阶段3A.2.1.2.2 统一入口锁

> **本节描述的是 3A.2.1.2.2 结束时的形态，已被第 11 节取代。**
> 当时的 `_make_single_task()` 在临时库分支仍会自己套一层
> `run_with_write_lock()`；第 11 节把加锁点收敛为公开入口一处。

### 问题

此前锁只在 `concurrency.run_with_write_lock()`，`scripts/run_validation.py`
直接调用 `runner.run_validation()` 会绕过锁——保护依赖调用路径而非系统。

### 方案

```text
runner.py
├─ _run_validation_unlocked()   内部实现，不加锁
├─ _acquire_and_run()           加锁并执行
└─ run_validation()             公开入口：已持锁→直通；未持锁→加锁

concurrency.py
└─ _make_single_task()          正式库路径直接调公开入口，不重复加锁
                               （临时库路径此时仍会套外层锁 → 第 11 节修复）
```

### 重入保护

用 `contextvars.ContextVar` 而非全局布尔：

```python
_LOCK_DEPTH = contextvars.ContextVar("validation_lock_depth", default=0)
def validation_lock_held() -> bool:
    return _LOCK_DEPTH.get() > 0
```

全局布尔会误判：A 线程持锁时，B 线程会被误认为「已持锁」而绕过锁。
`ContextVar` 的语义是**每个执行上下文独立**，线程/协程互不干扰。

### 锁文件路径

| 场景 | 锁文件位置 |
| --- | --- |
| 正式库 | `<db_dir>/.validation_write.lock` |
| 临时库（测试） | `<tmp_db_dir>/.validation_write.lock` |
| 显式 lock_dir | 该目录下同名文件 |

### 新增测试（4 项，阶段3A.2.1.2.2）

| 测试 | 覆盖 | 3A.2.1.2.3 后续状态 |
| --- | --- | --- |
| `test_run_validation_public_entry_acquires_lock` | 公开入口走加锁路径 | **已改写为行为验证** |
| `test_locked_context_does_not_reacquire` | 已持锁不重复加锁 | **已改写为行为验证** |
| `test_run_concurrent_tasks_does_not_double_lock` | 并发调度不双重加锁 | **已改写为行为验证** |
| `test_entry_lock_path_follows_db_dir` | 锁路径跟随数据库目录 | 保留（本就是行为验证） |

## 11. 阶段3A.2.1.2.3 临时库嵌套加锁缺陷修复

### 缺陷

`concurrency._make_single_task()` 的临时库分支：

```python
result = run_with_write_lock(run_validation, cfg, lock_dir=lock_dir)
```

`run_validation()` 自身也会 `_acquire_and_run()` 加锁，于是同一线程内两次
获取 `threading.Lock`。该锁**不可重入**，第二次 `acquire()` 会永久阻塞：
任务无声挂死，既不报错也不超时。

此外两层的锁目标不同（外层临时目录、内层数据库目录），本就不是同一把锁，
排队语义错乱；跨进程也无法互斥。

### 修复设计

| 原则 | 做法 |
| --- | --- |
| 唯一加锁点 | 加锁只在 `run_validation()` 公开入口内部 |
| 参数传递 | `_make_single_task()` 只传 `db_path`（要写的库）与可选 `lock_dir`（测试覆盖） |
| 锁文件位置 | 跟随被写的数据库目录，跨进程稳定 |
| 不做的事 | 不引入 `RLock`；不把 `_run_validation_unlocked()` 变成对外入口 |

### 三个配套修正

| # | 问题 | 修正 |
| ---: | --- | --- |
| 1 | 持锁标记在**拿锁之前**置位，等待锁期间会被误判为「已持锁」而绕过排队 | 标记下沉到 `_locked()` 闭包内（真正拿到锁之后），`finally` 复位 |
| 2 | 进程内锁 `with _WRITE_LOCK` 无限等待，嵌套时无声挂死 | 改 `acquire(timeout=…)`；同线程重复获取立刻抛 `ConcurrencyError` |
| 3 | 临时库场景读 `input_hash` 未传 `db_path`，读到正式库 → `None`，hash 一致性检查退化为恒真 | `get_validation(vid, db_path=db_path)` |

### 异常与超时语义（保持）

| 场景 | 行为 |
| --- | --- |
| 锁等待超时 | 抛 `ConcurrencyError`，不执行验证流程，不伪装成功 |
| 验证流程抛异常 | `finally` 复位持锁标记并释放锁，后续调用可立即获取 |
| 已持锁上下文中重入公开入口 | 直接走内部实现，不重复加锁（`contextvars` 判定） |

### 测试（改为行为验证）

原 4 项测试依赖 `inspect.getsource()` 做字符串匹配，改实现不影响行为也能通过。
本轮全部改写为行为断言，并新增 3 项（净增 4 项）：

| 测试 | 断言的行为 |
| --- | --- |
| `test_run_validation_public_entry_acquires_lock` | 执行期间持锁标记为 True 且其他线程拿不到锁；返回后为 False |
| `test_locked_context_does_not_reacquire` | 持锁期间重入公开入口不重复加锁，不死锁，深度为 2 |
| `test_run_concurrent_tasks_does_not_double_lock` | 临时库任务真实跑通、`input_hash` 非空、锁文件落在临时库目录 |
| `test_temp_db_two_threads_no_deadlock` | 两个临时库任务并行调度均完成 |
| `test_public_entry_timeout_raises_concurrency_error` | 外部持锁 → `ConcurrencyError` 且流程未执行；释放后可重新获取 |
| `test_public_entry_releases_lock_on_exception` | 异常后标记复位、锁可被他人获取、后续调用成功 |
| `test_nested_lock_raises_instead_of_hanging` | 同线程嵌套加锁 5 秒内报错；报错后锁完全释放 |

全量测试：337 → 351 → 365 → 369 → **373 项**。

### 真实运行证据（非单测）

| 项 | 结果 |
| --- | --- |
| 单临时库任务（`_make_single_task`） | `success`，253.2s，`validation_id=87328a95ea394e76` |
| `input_hash` | `dc5137ab80c92d71`，与临时库 `validation_runs` 记录一致 |
| 执行期间探测 | 其他线程拿不到锁（`lock_held_during_execution=true`） |
| 结束后持锁标记 | `false` |
| 两临时库任务并发 | 579.1s，273.6s + 577.7s 严格串行，`hash_consistency=true` |

### 未验证

- 临时库 4 并发、临时库多进程调度
- 8 及以上并发、跨机器共享库、小时级长压测
- 以上均不宣称通过。

## 12. 外部证据

**真实券商交割单核验：`deferred_external_evidence`。** 本轮未获得任何脱敏
交割单，`per_order` 佣金模型与最低佣金规则仍属模拟假设，不做对账结论。
