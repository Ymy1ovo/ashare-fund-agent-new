# 阶段3A.3.2.3.3 测试报告

- 首次执行：2026-11-14 / 复核补充：2026-11-16
- 环境：Python 3.11.2 / pytest 9.2.0 / Windows

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.3.1） | 538 | 538 | 0 | 0 | 0 |
| **3A.3.2.3.2** 新增（闸门修复） | 26 | 26 | 0 | 0 | 0 |
| **3A.3.2.3.3** 新增（执行缺陷 + 链路） | 4 | 4 | 0 | 0 | 0 |
| **合计** | **568** | **568** | **0** | **0** | **0** |

- 执行耗时：**123.66 ~ 132.91 秒**（两次连续执行，pytest 报告为
  `568 passed, 1 warning in 123.66s` / `132.91s`）
- 跳过 0，xfail 0，failed 0
- 唯一 warning 是 `StarletteDeprecationWarning`（httpx 弃用），与业务无关

## 2. 3A.3.2.3.2 的 26 项

覆盖任务书 §8 的 14 条异常场景，详见
`reports/phase3A3_2_3_2_replay_gate_fix.md` §5。

## 3. 3A.3.2.3.3 新增的 4 项

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 1 | `test_replay_stamps_accounting_version_on_new_record` | 重放成功后新记录必须带 `ca-v2-receivable` |
| 2 | `test_failed_gate_downgrades_orphan_record` | 闸门失败时把孤立记录降级为 `failed` |
| 3 | `test_validation_replay_event_load_failure_fails` | validation 链路事件表读取失败 → `failed` + 原因 |
| 4 | `test_validation_replay_internal_failure_records_reason` | `run_validation` 内部抛错 → `failed` + 原因可查 |

前 2 项来自**本轮真实执行暴露的缺陷**：`save_validation_run()` 不写
`accounting_version` 列，第一次重放因此被闸门判失败。
后 2 项补齐 §8-4 的 validation 一侧（原先只测了 backtest 一侧）。

## 4. 旧测试保留情况

- 538 项基线测试**全部保留**，未删除、未跳过、未弱化断言。
- 未修改任何旧测试的预期结果。
- 本轮修正了 1 处**本轮自己新写**的断言
  （`test_validation_replay_event_load_failure_fails` 里「库内 success 记录数
  为 0」改成「除源记录外为 0」——空库场景下源记录本身就是 success，
  原断言写错了对象，不是弱化）。

## 5. 其他验证

### 5.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/<最新>` | 200（windows=8 grid=8 stress=7 conclusion=有条件通过） |
| `GET /api/validations/not_exist` | 404 |

`SMOKE_FAILED: 无`

### 5.2 Streamlit AppTest

| 页面 | 异常 | 错误元素 | 数据表 | 指标 |
| --- | ---: | ---: | ---: | ---: |
| `dashboard/pages/3_回测.py` | 0 | 0 | 5 | 5 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 | 5 | 4 |

### 5.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 5.4 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |

重放前、两次重放后、dry-run 后、幂等复跑后，**五次测量均为该值**。

### 5.5 历史记录核对

| 项 | 结果 |
| --- | --- |
| 源 `32aead3291734f91` 全字段 | 与执行前快照逐字段相等 |
| 源 `c46fa37b932944c2` 全字段 | 与执行前快照逐字段相等 |
| 源记录 `finished_at` | `2026-11-11T17:47:44` / `2026-11-12T20:25:06`，未变 |
| `validation_runs` 总数 | 44 → 47（+2 成功 +1 失败留痕） |
| `replay_attempts` 总数 | 1 → 4 |
| `backtest_runs` | 12（不变） |
| `corporate_actions` | 166（不变） |
| `corporate_action_versions` | 704（不变） |
| `corporate_action_applications` | 3,787（不变） |
| `dividend_receivables` | 785（不变） |

### 5.6 重放记录与 attempt 关联核对

| source | replay | attempt 状态 | 关联 |
| --- | --- | --- | --- |
| `32aead3291734f91` | `397118a140c44f47` | failed | 正确（首次失败留痕） |
| `32aead3291734f91` | `03410886d1f64fa7` | success | 正确 |
| `c46fa37b932944c2` | `321caeb581e54d3b` | success | 正确 |

每个 source 恰好 1 条 `success`。

### 5.7 input_hash 独立复现

用「当前行情指纹 + 池内 80 条事件 digest + resolved_params」重算：

| 记录 | 库内 | 重算 | 一致 |
| --- | --- | --- | --- |
| `03410886d1f64fa7` | `1263f78d8a63e309` | 同 | 是 |
| `321caeb581e54d3b` | `6da51a1c462b7c65` | 同 | 是 |
| `32aead3291734f91` | `dbfac114e6900c87` | 不等 | 预期（旧算法无事件指纹） |
| `c46fa37b932944c2` | `2ac80bcdfb5459c5` | 不等 | 预期（同上） |

## 6. 未执行项

**无。** 任务书要求的回归项全部执行。

## 7. 结论

- 基线 538 项全部保留且通过
- 本轮新增 30 项（26 + 4）全部通过
- 最终 **568 passed / 0 failed / 0 skipped / 0 xfail**
- 耗时 123.66 ~ 132.91 秒
- 测试结果是本会话本地执行结果，**不是外部独立测试**
