# 阶段3A.2.1.2.1 并发验证安全性报告（修订版）

- 生成时间：2026-11-12
- 执行方式：DSH 实际运行，多线程 + 多进程真实验证

## 1. 执行模型（明确修订）

**本项目采用「全流程串行排队」，不是「计算并行 + 写入串行」。**

| 项 | 说明 |
| --- | --- |
| 执行模型 | `full-pipeline-serial` |
| 计算并行 | **否**（`compute_parallel=False`） |
| 排队范围 | **整个验证任务**（从取数到落库），不是仅写入阶段 |
| 进程内锁 | `threading.Lock`（同进程多线程互相排队） |
| 跨进程锁 | 文件锁 `data/.validation_write.lock`（正式库同目录，路径稳定） |
| 锁获取时机 | 验证开始前 |
| 锁释放时机 | 任务全部完成或异常抛出后（`finally`） |
| 超时行为 | 抛 `ConcurrencyError`，记录为 failed，不跳过、不伪装成功 |

**为什么不做计算并行**：验证流程全程读同一份行情、写同一个 SQLite，
串行最安全；且实测 4 任务串行 1311 秒可完成，没有证据表明并行能带来
可观测收益。本轮以正确性优先。

**不宣称**：8 个或更多任务已验证；也不宣称任何计算阶段并行。

## 2. 实测结果

### 2.1 两线程同时提交

| 项 | 结果 |
| --- | --- |
| 任务数 | 2 |
| 总耗时 | 434.3 秒 |
| `database_integrity` | **ok** |
| `validation_ids_unique` | **true** |
| `hash_consistency` | **true** |
| `execution_model` | `full-pipeline-serial` |
| `lock_path` | `D:\ymy\jj-agent\data\.validation_write.lock` |

| task_id | status | 耗时 | validation_id |
| --- | --- | ---: | --- |
| `two_0` | success | 194.4s | `a6d35304e92e4fca` |
| `two_1` | success | 433.1s | `03ff00a306bf4141` |

第二个任务的耗时几乎等于两个任务之和，**证明是全流程串行排队**。

### 2.2 四线程同时提交

| 项 | 结果 |
| --- | --- |
| 任务数 | 4 |
| 总耗时 | **1311.6 秒** |
| `database_integrity` | **ok** |
| `validation_ids_unique` | **true** |
| `hash_consistency` | **true** |

| task_id | status | 耗时 | validation_id |
| --- | --- | ---: | --- |
| `four_0` | success | 630.2s | `aa51841d096f4ada` |
| `four_1` | success | 850.8s | `02edb3dd966042b3` |
| `four_2` | success | 1059.8s | `4a03b4cfc2c142f0` |
| `four_3` | success | 1311.6s | `bdfe34dbfe91424a` |

**完成时间严格递增、间隔略大于单任务耗时**，进一步确认串行排队生效。

### 2.3 两个独立 Python 进程共享锁

`multiprocessing spawn` 启动两个独立进程，同时调用 `run_validation`：

| 事件序列 | 说明 |
| --- | --- |
| `P1-enter` | P1 拿到锁 |
| `P1-ok:9bfe82141e2c41c4:275.0` | P1 完成，275.0 秒 |
| `P1-exit` | P1 释放锁 |
| `P2-enter` | P2 才拿到锁 |
| `P2-ok:c7e86fb64c914cb2:280.1` | P2 完成，280.1 秒 |
| `P2-exit` | P2 释放锁 |

| 项 | 结果 |
| --- | --- |
| 总耗时 | 556.7 秒 |
| 进程退出码 | `[0, 0]` |
| 是否交错 | **否**（P1 完整结束后 P2 才进入） |
| validation_id | 两个不同 |

**两个独立进程通过 `data/.validation_write.lock` 安全排队。**

#### 2.3.1 过程中发现并修复的锁实现缺陷

首次多进程测试两个进程都 `lockfail:PermissionError`。根因：

1. 锁文件大小 0 字节时，Windows `msvcrt.locking` 的区域锁行为不可靠；
2. 多进程同时首建锁文件时，写首字节会撞 `PermissionError`。

修复：

- 确保锁文件至少有 1 字节（`_ensure_lock_file_byte()`，带重试）
- 加锁句柄改用 `"r+b"` 而非 `"a+b"`，避免追加模式下的定位混乱

修复后多进程测试通过（见 2.3 事件序列）。

### 2.4 一个任务失败，另一个正常执行

| task_id | status | validation_id | 说明 |
| --- | --- | --- | --- |
| `bad` | **failed** | None | `ValidationConfigError: 样本内外必须严格分离` |
| `ok` | success | `d1f811a567f24252` | 正常运行完成 |

- 失败任务被正确记录为 `failed` 并带 `error_message`
- **不产生不完整的成功记录**
- 另一个任务不受影响
- `database_integrity=ok`，`ids_unique=true`

### 2.5 中途异常后锁能否释放

```python
try:
    run_with_write_lock(boom)   # boom 抛 RuntimeError
except RuntimeError:
    pass
run_with_write_lock(lambda: "reacquired")   # → "reacquired"
```

**异常后锁被正确释放，后续任务能立即获得锁。**

单测 `test_run_with_write_lock_releases_on_exception` 与
`test_run_with_write_lock_serializes` 进一步覆盖。

### 2.6 锁超时行为

外部持锁时调用，`timeout=0.5`：

```
timeout ok: ConcurrencyError
after release: ok
```

**超时抛 `ConcurrencyError`，不静默跳过、不伪装成功。**

## 3. 十四项检查结果

| # | 检查项 | 结果 |
| ---: | --- | --- |
| 1 | validation_id 是否唯一 | **是**（2/4 线程 + 多进程均唯一） |
| 2 | strategy_version 是否正确 | 是 |
| 3 | input_hash 是否正确 | 是（同参数同、异参数异） |
| 4 | 是否使用独立临时数据库副本 | 是（验证内部按任务复制） |
| 5 | 是否发生 `database is locked` | **否** |
| 6 | 是否发生重复写入 | 否 |
| 7 | 是否发生结果串数据 | 否 |
| 8 | 是否发生输入指纹串用 | 否 |
| 9 | 是否发生临时文件覆盖 | 否 |
| 10 | 是否存在部分提交 | 否 |
| 11 | 某任务失败是否影响其他任务 | **否** |
| 12 | 是否遗留连接/锁/临时文件 | 否（`finally` 释放） |
| 13 | 历史 validation 是否完整 | 是（13 条原有记录未变） |
| 14 | 并发后 `integrity_check` | **ok** |

## 4. 安全并发规模结论

| 并发数 | 是否安全 | 证据 |
| ---: | --- | --- |
| 2 线程 | **安全排队** | 434.3s，ids 唯一，hash 一致 |
| 4 线程 | **安全排队** | 1311.6s，ids 唯一，hash 一致 |
| 2 独立进程 | **安全排队** | 556.7s，事件严格串行，exitcode 均 0 |
| 2 临时库任务（3A.2.1.2.3） | **安全排队** | 579.1s，273.6s + 577.7s，hash 一致 |

**当前推荐安全并发规模：4 个任务（线程或进程），全流程串行排队。**

**未验证**：8 个及以上任务、跨机器共享数据库、长时间（小时级）并发压测。
这些不宣称通过。

## 5. 数据安全

| 检查 | 结果 |
| --- | --- |
| 并发前后 `integrity_check` | ok / ok |
| 行情行数 | 116,609（未变） |
| 行情完整指纹 | `market-fingerprint-v3:d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`（未变） |
| 历史 validation（原有 13 条） | 全部保留 |
| 新增 validation | 19 条（2 线程 2 + 4 线程 4 + 多进程 2 + 失败隔离 1 + 其他） |
| 重复 validation_id | **0** |

## 5.5 阶段3A.2.1.2.3：临时库路径的嵌套加锁缺陷与修复

### 缺陷（真实存在，非推测）

`concurrency._make_single_task()` 的临时库分支写成：

```python
result = run_with_write_lock(run_validation, cfg, lock_dir=lock_dir)
```

而 `run_validation()` 自 3A.2.1.2.2 起内部也会 `_acquire_and_run()` 加锁。
于是在**同一线程**内出现两次加锁：

| 层次 | 拿到的锁 |
| --- | --- |
| 外层 `run_with_write_lock(..., lock_dir=lock_dir)` | `<临时目录>/.validation_write.lock` + `_WRITE_LOCK` |
| 内层 `run_validation()` → `_acquire_and_run()` | `<数据库目录>/.validation_write.lock` + `_WRITE_LOCK` |

`threading.Lock` 不可重入。第二次 `acquire()` 在**已持有该锁的同一线程**里
无限等待，表现为任务无声挂死——不报错、不超时、不释放。

实测复现（修复前的等价调用路径）：

```text
alive_after_20s: True    ← 20 秒后线程仍在阻塞
```

### 修复

| 项 | 修改前 | 修改后 |
| --- | --- | --- |
| 加锁点 | 外层 + 入口共 2 次 | **仅公开入口 1 次** |
| 临时库调用 | `run_with_write_lock(run_validation, cfg, lock_dir=…)` | `run_validation(cfg, db_path=…, lock_dir=…)` |
| 锁文件位置 | 外层临时目录、内层数据库目录（两把不同锁） | 统一跟随被写的数据库目录 |
| 持锁标记置位 | 进入 `_acquire_and_run` 前 | **真正拿到锁之后**（`_locked()` 闭包内） |
| 同线程重复获取 | 永久挂死 | 立刻抛 `ConcurrencyError` |
| 进程内锁等待 | `with _WRITE_LOCK`（无限等待） | `acquire(timeout=…)`，超时抛 `ConcurrencyError` |

修复后同一路径：

```text
alive_after_20s: False   elapsed: 0.0
outcome: ConcurrencyError: 重复获取验证锁：同一线程已在锁内又发起一次加锁
```

**注意**：这里没有把锁改成 `threading.RLock`。`RLock` 只会让嵌套加锁
「看起来能跑」，但两把锁（临时目录锁 vs 数据库目录锁）仍然不是同一把，
跨进程语义依旧错乱。正确做法是收敛到**唯一加锁点**。

### 修复后的真实运行验证

| 验证 | 结果 |
| --- | --- |
| 单个临时库任务（`_make_single_task` + `db_path`） | status `success`，253.2s，`validation_id=87328a95ea394e76` |
| 该任务 `input_hash` | `dc5137ab80c92d71`，与临时库 `validation_runs` 中记录**完全一致** |
| 执行期间其他线程探测拿锁 | 拿不到（`lock_held_during_execution=true`） |
| 执行结束持锁标记 | `false` |
| 锁文件位置 | 临时库同目录 `.validation_write.lock` ✅ |
| 两个临时库任务并发调度 | **579.1s**，两任务均 success，`hash_consistency=true`，ids 唯一 |
| 耗时形态 | `273.6s` + `577.7s`，**严格串行** |

### 顺带修掉的第二处缺陷

同一轮发现 `_make_single_task()` 读 `input_hash` 时写的是
`get_validation(result.validation_id)`——**不传 `db_path`**。
临时库场景下这会去读**正式库**，必然读不到记录：

- `input_hash` 变成 `None`；
- `_check_hash_consistency()` 跳过空值 → 「一致性检查」退化为永远通过。

已改为 `get_validation(result.validation_id, db_path=db_path)`。
修复前真实运行实测 `input_hash: null`，修复后同一路径得到
`dc5137ab80c92d71` 且与临时库记录一致。

## 6. 限制

1. 只测到 4 并发；8 及以上未验证
2. 多进程只测 2 进程、同一台机器
3. 未做小时级长时压测
4. 串行意味着总耗时随任务数线性增长（4 任务 1311 秒），
   这是正确性优先的代价，不是性能优化目标
5. 临时库路径的复测只跑了 2 个任务；临时库 4 并发、临时库多进程均未验证

## 7. 公开入口自动加锁（阶段3A.2.1.2.2）

### 7.1 问题

此前锁保护只在 `concurrency.run_with_write_lock()` 里，直接调用
`scripts/run_validation.py` → `runner.run_validation()` 会**绕过锁**（这是整改前的问题，现已修复）。

### 7.2 整改

`app/validation/runner.py` 拆成两层：

| 函数 | 职责 |
| --- | --- |
| `_run_validation_unlocked()` | 内部实现，**不加锁**，仅供内部使用 |
| `run_validation()` | **公开入口，自动经过全流程串行锁** |

递归保护用 `contextvars.ContextVar` 记录「当前执行上下文持锁深度」，
不使用全局布尔变量（那样会误判其他线程）：

```python
if validation_lock_held():
    return _run_validation_unlocked(...)   # 已持锁，直接执行
return _acquire_and_run(...)               # 未持锁，先加锁
```

`run_concurrent_tasks()` 在正式库路径上改为直接调用公开入口，
不再自己套锁，避免重复加锁。

### 7.3 全部正式调用入口检查

| 入口 | 是否经过锁 | 说明 |
| --- | --- | --- |
| `scripts/run_validation.py` | **是** | 调用 `runner.run_validation()`，自动加锁 |
| `concurrency.run_concurrent_tasks()` | **是** | 内部调用公开入口 |
| `sensitivity_scan.run_sensitivity_matrix()` | 不适用 | 只跑回测，不写 validation 记录 |
| 测试代码 `temp_db` 路径 | 是（可配置） | 锁文件跟随临时库目录 |

### 7.4 入口级实测：两线程直接调用公开入口

未加任何外层锁，两个线程**直接调用 `run_validation()`**：

| 事件 | 说明 |
| --- | --- |
| `T1-start` | T1 进入入口 |
| `T2-start` | T2 进入入口（被锁阻塞） |
| `T1-end` | T1 完成，242.7 秒 |
| `T2-end` | T2 完成，累计 484.5 秒 |

| task | status | validation_id | 耗时 |
| --- | --- | --- | ---: |
| T1 | success | `05b9af375c4e4ee5` | 242.7s |
| T2 | success | `4b37c111e6ab4403` | 484.5s |

**总耗时 484.5 秒 ≈ 单任务的 2 倍**，证明入口锁生效、两任务串行排队。

### 7.5 入口级实测：两独立进程直接调用公开入口

| 事件 | 说明 |
| --- | --- |
| `P1-start` / `P2-start` | 两进程同时进入入口 |
| `P1-ok:e18525b7d5244d9f:248.4` | P1 完成 |
| `P1-held_after:False` | P1 结束后持锁标记已复位 |
| `P1-end` | |
| `P2-ok:e3507c7defa34229:494.8` | P2 累计 494.8 秒完成 |
| `P2-end` | |

| 项 | 结果 |
| --- | --- |
| 总耗时 | 496.7 秒 |
| 进程退出码 | `[0, 0]` |
| validation_id | 两个不同 |
| 结束后持锁标记 | 两进程均为 `False`（无残留） |

**两个独立进程通过公开入口的共享文件锁安全排队，未实测到跨进程失败。**

### 7.6 阶段3A.2.1.2.3 之后的入口锁形态

`run_concurrent_tasks()` 在正式库与临时库路径上**都**只调用公开入口，
加锁点唯一：

```python
# concurrency._make_single_task()
result = run_validation(cfg, db_path=db_path, lock_dir=lock_dir)
```

| 参数 | 作用 |
| --- | --- |
| `db_path` | 要写的数据库；锁文件默认跟随它所在目录 |
| `lock_dir` | 仅测试显式覆盖锁目录，正式库不传 |

原来的 `lock_dir = root / "locks" if workdir is not None else None` 分支已删除：
它让「临时工作目录」和「被写的数据库目录」分属两处，正是嵌套加锁的温床。
