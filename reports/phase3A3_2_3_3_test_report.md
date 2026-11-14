# 阶段3A.3.2.3.3 测试报告

- 生成时间：2026-11-14
- 环境：Python 3.11.2 / pytest / Windows
- 基线：538 项（3A.3.2.3.1）

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.3.1） | 538 | 538 | 0 | 0 | 0 |
| **3A.3.2.3.2** 新增（闸门修复） | 26 | 26 | 0 | 0 | 0 |
| **3A.3.2.3.3** 新增（执行缺陷） | 2 | 2 | 0 | 0 | 0 |
| **合计** | **566** | **566** | **0** | **0** | **0** |

执行耗时约 128 秒。

## 2. 3A.3.2.3.2 的 26 项

见 `reports/phase3A3_2_3_2_replay_gate_fix.md` §5。
覆盖任务书 §8 的 14 条异常场景，每条核实数据库最终状态。

## 3. 3A.3.2.3.3 新增的 2 项

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 1 | `test_replay_stamps_accounting_version_on_new_record` | 重放成功后新记录必须带 `ca-v2-receivable` |
| 2 | `test_failed_gate_downgrades_orphan_record` | 闸门失败时把孤立记录降级为 `failed` |

这两项来自**本轮真实执行暴露的缺陷**：`save_validation_run()` 不写
`accounting_version` 列，第一次重放因此被闸门判失败。

## 4. 旧测试保留情况

- 538 项基线测试**全部保留**，未删除、未跳过、未弱化断言。
- 未修改任何旧测试的预期结果。

## 5. 其他验证

### 5.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/<最新>` | 200（windows=8 grid=8 stress=7） |
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

重放前、两次重放后、幂等复跑后均为该值。

### 5.5 历史记录核对

| 项 | 结果 |
| --- | --- |
| 源记录 `32aead3291734f91` 全字段 | 与执行前快照逐字段相等 |
| 源记录 `c46fa37b932944c2` 全字段 | 与执行前快照逐字段相等 |
| `validation_runs` 总数 | 44 → 47（+2 成功 +1 失败降级） |
| `replay_attempts` 总数 | 1 → 4 |
| `backtest_runs` | 12（不变） |

### 5.6 重放记录与 attempt 关联核对

| source | replay | attempt 状态 | 关联 |
| --- | --- | --- | --- |
| `32aead3291734f91` | `03410886d1f64fa7` | success | 正确 |
| `32aead3291734f91` | `397118a140c44f47` | failed | 正确（首次失败留痕） |
| `c46fa37b932944c2` | `321caeb581e54d3b` | success | 正确 |

每个 source 恰好 1 条 `success`。

## 6. 结论

- 基线 538 项全部保留且通过
- 本轮新增 28 项（26 + 2）全部通过
- 最终 **566 passed / 0 failed / 0 skipped / 0 xfail**
- 未执行的任务：无（任务书要求的回归项全部执行）
- 测试结果是本会话本地执行结果，**不是外部独立测试**
