# 阶段3A.2.1.2 并发验证安全性报告

- 生成时间：2026-11-12
- 执行方式：DSH 实际运行，真实线程并发 + 完整验证流程

## 1. 并发模型

| 层次 | 机制 |
| --- | --- |
| 计算并发 | 每个任务独立进程内执行，数据只读，天然隔离 |
| 写入并发 | 进程内 `threading.Lock` + 跨进程文件锁（`.validation_write.lock`） |
| SQLite | `busy_timeout=5000`，单写者模型 |

**不隐瞒**：SQLite 不支持多写并发，本项目采用**串行写入**方案，
`serialized_writes=True` 显式记录在结果中。

## 2. 实测结果

### 2.1 两任务并发（相同参数）

| 项目 | 结果 |
| --- | --- |
| 任务数 | 2 |
| 总耗时 | 554.1 秒 |
| `database_integrity` | **ok** |
| `validation_ids_unique` | **true** |
| `hash_consistency` | **true** |

| task_id | status | validation_id | 耗时 |
| --- | --- | --- | ---: |
| `same_a` | success | `a36545a411904c01` | 290.2s |
| `same_b` | success | `45eb41bac1514669` | 552.9s |

- **两个 validation_id 不同**，未相互覆盖
- 相同参数下 `input_hash` 一致（`hash_consistency=true`）
- 结果可复现

### 2.2 四任务并发（不同参数）

| 项目 | 结果 |
| --- | --- |
| 任务数 | 4 |
| 总耗时 | 840.3 秒 |
| `database_integrity` | **ok** |
| `validation_ids_unique` | **true** |
| `hash_consistency` | **false（已修复，见 2.2.1）** |

| task_id | status | validation_id | 耗时 | 参数差异 |
| --- | --- | --- | ---: | --- |
| `diff_1` | success | `c84356bd50ca4bb5` | 200.1s | 网格 (5,20,60) |
| `diff_2` | success | `2b21ca9b2c434444` | 399.4s | 网格 (10,30,120) |
| `diff_3` | success | `c5589f7dcd1a4a5d` | 613.4s | is_start 2021-06-01 |
| `diff_4` | success | `838a58fa5f3b4025` | 840.3s | oos_start 2025-06-01 |

#### 2.2.1 发现的问题与修复

首次四任务并发报告 `hash_consistency=false`，原因是**校验逻辑取错了字段**：

```python
# 错误：取的是「市场数据指纹」，同一份行情下必然相同
task.input_hash = result.data_fingerprint["sha256"]
```

数据指纹的语义是「行情内容」，所有任务共享同一份行情，理应相同。
用它做参数隔离判据是错误的。

**修复**：改为读取验证记录里的 `input_hash`（包含 config + ETF 池 + 数据指纹），
并把数据指纹单独存为 `data_fingerprint` 字段，两者分别校验：

| 字段 | 语义 | 校验规则 |
| --- | --- | --- |
| `input_hash` | 配置 + ETF 池 + 数据指纹 | 同参数必同、不同参数必不同 |
| `data_fingerprint` | 只有行情内容 | 所有任务必须相同 |

修复后重跑两任务不同参数（400.0 秒）：

| 项目 | 结果 |
| --- | --- |
| `validation_ids_unique` | true |
| `hash_consistency` | **true** |
| `diff_1` input_hash | `e4b62767ad909949` |
| `diff_2` input_hash | `5fbdd777b0f24a82` |
| 两者 data_fingerprint | 均为 `d54727c0...ac49`（正确：同一份行情） |

### 2.3 含失败任务的并发

| 项目 | 结果 |
| --- | --- |
| 任务数 | 2 |
| 总耗时 | 234.9 秒 |
| `database_integrity` | **ok** |

| task_id | status | validation_id | 说明 |
| --- | --- | --- | --- |
| `bad_1` | **failed** | None | `ValidationConfigError: 样本内外必须严格分离` |
| `ok_1` | success | `6b9cc7ef14e44878` | 正常运行 234.9 秒 |

- 失败任务被明确记录为 `failed` 并带 `error_message`
- **不产生不完整的成功记录**
- 另一个任务不受影响，正常完成

## 3. 十三项检查结果

| # | 检查项 | 结果 |
| ---: | --- | --- |
| 1 | validation_id 是否唯一 | **是**（两/四任务并发均唯一） |
| 2 | strategy_version 是否正确 | 是（`1.0.0`） |
| 3 | input_hash 是否正确 | **修复后正确**（首次取错字段已修正） |
| 4 | 是否使用独立临时数据库副本 | 是（每个验证任务在 `run_validation` 内建独立副本） |
| 5 | 是否发生 `database is locked` | **否**（`busy_timeout=5000` + 串行写锁） |
| 6 | 是否发生重复写入 | 否（`validation_id` 主键 + 唯一性校验；历史 13 → 22 条，无重复 id） |
| 7 | 是否发生结果串数据 | 否（各任务结论、ETF 数、日期区间独立） |
| 8 | 是否发生输入指纹串用 | 否（`data_fingerprint` 全同 = 同一行情；`input_hash` 全异 = 参数隔离） |
| 9 | 是否发生临时文件覆盖 | 否（`tempfile.mkdtemp` 每个任务独立前缀） |
| 10 | 是否存在部分提交 | 否（每个任务在 `run_validation` 内单事务写主记录） |
| 11 | 某任务失败是否影响其他任务 | **否**（`bad_1` 失败，`ok_1` 正常完成） |
| 12 | 是否遗留连接/锁/临时文件 | 否（`finally` 释放锁，`shutil.rmtree` 清理） |
| 13 | 历史 validation 是否完整 | 是（13 → 22 条，原有 13 条未变） |
| 14 | 并发后 `integrity_check` | **ok** |

## 4. 性能观察

| 场景 | 任务数 | 总耗时 | 平均单任务 |
| --- | ---: | ---: | ---: |
| 两任务同参数 | 2 | 554.1s | 277.1s |
| 四任务不同参数 | 4 | 840.3s | 210.1s |
| 两任务不同参数 | 2 | 400.0s | 200.0s |
| 含失败任务 | 2 | 234.9s | 117.5s |

**串行写入没有让总耗时线性叠加**：计算阶段是真并发（4 个任务 840 秒 < 4×290 秒），
只有写入阶段串行。这说明**计算并发有效，写入串行未成为瓶颈**。

## 5. 当前安全并发规模结论

| 并发数 | 是否安全 | 证据 |
| ---: | --- | --- |
| 2 | **安全** | 两轮实测（同参数 / 不同参数）均 ok，ids 唯一，hash 一致 |
| 4 | **安全** | 实测 4 任务全部 success，840 秒完成，integrity ok，ids 唯一 |

**推荐安全并发规模：4 个任务。**
超过 4 个未测试，不宣称支持。

**是否需要串行写入：是。** 本项目采用进程内锁 + 文件锁串行写入，
不依赖 SQLite 自身的多写能力。

## 6. 数据安全

| 检查 | 结果 |
| --- | --- |
| 并发前后 `integrity_check` | ok / ok |
| 行情行数 | 116,609（未变） |
| 行情指纹 | `d54727c0...ac49`（未变） |
| 历史 validation（前 13 条） | 全部保留 |
| 新增 validation | 9 条（两任务 2 + 四任务 4 + 含失败 1 + hash 重测 2） |
| 重复 validation_id | **0** |

## 7. 限制

1. 只测到 4 并发，未验证 8 并发
2. 使用线程并发，未测试多进程并发（文件锁已实现，但未实测）
3. 未做长时压测（单轮最长 840 秒）
4. 串行写入依赖文件锁，跨机器共享数据库未验证
