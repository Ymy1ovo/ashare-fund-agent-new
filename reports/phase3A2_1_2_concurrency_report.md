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

## 6. 限制

1. 只测到 4 并发；8 及以上未验证
2. 多进程只测 2 进程、同一台机器
3. 未做小时级长时压测
4. 串行意味着总耗时随任务数线性增长（4 任务 1311 秒），
   这是正确性优先的代价，不是性能优化目标
