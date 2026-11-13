# 阶段3A.3.2.2 测试报告（含 3A.3.2.2.1 收尾）

- 生成时间：2026-11-13
- 涵盖阶段：3A.3.2.2 + 3A.3.2.2.1
- 环境：Python 3.11.2 / pytest / Windows

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.1，含 3A.3.2.2 前的 387 + 公司行为 38） | **425** | 425 | 0 | 0 | 0 |
| **3A.3.2.2 新增** | **29** | 29 | 0 | 0 | 0 |
| **3A.3.2.2.1 新增** | **15** | 15 | 0 | 0 | 0 |
| **合计** | **469** | **469** | **0** | **0** | **0** |

`--collect-only`：**469 tests collected**
`tests/test_corporate_actions.py`：**82 passed**
其他测试：**387 passed**

## 2. 3A.3.2.2.1 新增的 15 项

### 2.1 零碎规则（4 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 1 | `test_unknown_policy_without_fraction_applies` | unknown 但无零碎 → 可应用 |
| 2 | `test_unknown_policy_with_fraction_is_blocked` | unknown 且有零碎 → 阻断 |
| 3 | `test_unknown_policy_blocked_via_compute_impact` | 直接调函数阻断 + 无零碎可过 |
| 4 | `test_explicit_truncate_still_applies` | 明确 truncate 正常执行 |
| 5 | `test_explicit_round_up_still_applies` | 明确 round_up 正常执行 |

### 2.2 现金补偿（3 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 6 | `test_cash_compensation_without_official_price_fails_closed` | 缺依据 → 构造即抛错 |
| 7 | `test_cash_compensation_with_official_price_uses_that_price` | 用官方价不用收盘价 |
| 8 | `test_compensation_price_changes_fingerprint` | 补偿价进指纹 |

### 2.3 登记日资格（6 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 9 | `test_dividend_requires_record_date_in_range` | 登记日早于区间 → 阻断 |
| 10 | `test_dividend_after_record_date_buy_gets_nothing` | 登记日后买入 → 无分红 |
| 11 | `test_dividend_held_from_record_date_is_entitled` | 登记日持有 → 有分红 |
| 12 | `test_dividend_uses_close_after_record_date_trades` | 登记日当天成交 → 用收盘持仓 |
| 13 | `test_dividend_sell_after_record_date_keeps_receivable` | 登记日后卖出 → 应收不变 |
| 14 | `test_secondary_dividend_with_unverified_record_date_not_applied` | secondary 无登记日 → 不应用 |

### 2.4 版本与证据（1 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 15 | `test_event_version_history_complete` | 三次变更产生三个版本 |

## 3. 修改但未新增的测试

| 测试 | 改动 | 说明 |
| --- | --- | --- |
| `test_fractional_shares_converted_to_cash` | 补 `fractional_policy="truncate"` | 语义是「按规定处置」，必须显式声明规则 |
| `test_multi_lot_split_keeps_lot_sum` | 补 `fractional_policy="truncate"` | 同上 |
| `test_dividend_held_from_record_date_is_entitled` | 重排时序（8 个交易日） | T+1 语义：信号日下单、次日成交 |
| `test_dividend_after_record_date_buy_gets_nothing` | 重排时序 | 同上 |
| `test_dividend_uses_close_after_record_date_trades` | 重排时序 | 同上 |
| `test_dividend_sell_after_record_date_keeps_receivable` | 重排时序 | 同上 |
| `test_load_actions_filters_by_window_date` | 3A.3.2.2 重写 | 按类型分别验证 |

**没有任何一项被删除或跳过，断言强度没有降低。**

## 4. 其他验证

### 4.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/e8b052dd2db542f9` | 200（8 窗口、8 参数、7 压力、有条件通过） |
| `GET /api/validations/not_exist` | 404 |

`SMOKE_FAILED: 无`

### 4.2 Streamlit AppTest

| 页面 | 异常 | 错误 |
| --- | --- | :---: |
| `dashboard/pages/3_回测.py` | 0 | 0 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 |

### 4.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 4.4 数据迁移幂等性

在备份副本上连续执行 `init_db()` 两次：

| 表 | 前 | 后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_versions` | 704 | 704 |
| `validation_runs` | 43 | 43 |
| `integtest_check` | — | ok |

新增列：`compensation_price` / `compensation_price_source`（两表各一组）。

### 4.5 事件对账脚本

`python scripts/reconcile_events.py`：

**校验项 14，失败 0**

新增「零碎处置口径」统计块：

| 口径 | 样本内 | 样本外 | 区间外 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| `truncate` | 0 | 0 | 9 | 9 |
| `round_up` | 2 | 3 | 0 | 5 |
| `unknown` | 13 | 6 | 12 | 31 |

### 4.6 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本阶段是否改变 | **否**（连续第五阶段不变） |

### 4.7 事件指纹

| 区间 | 事件数 | 指纹 |
| --- | ---: | --- |
| 样本内 | 29（应用集） | `855dc11a43a889…` |
| 样本外 | 30（应用集） | `d87fb1e3c9261b…` |

字段集已再扩展（加 `compensation_price` / `compensation_price_source`）。

### 4.8 完整验证重放

| 项 | 值 |
| --- | --- |
| validation_id | **`e8b052dd2db542f9`** |
| input_hash | `6da51a1c462b7c65` |
| 耗时 | 1,436.3 秒 |
| 池 | 41 只 |
| 样本内选出参数 | MA250 |
| 结论 | 有条件通过 |
| 行情是否变化 | 否 |

## 5. 失败与跳过

| 项 | 数量 |
| --- | ---: |
| 失败 | **0** |
| 错误 | **0** |
| 跳过 | **0** |
| xfail | **0** |
| 警告 | 1（Starlette `httpx` 弃用，与改动无关） |

## 6. 复现命令

```bash
cd D:\ymy\jj-agent

PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_corporate_actions.py -q
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/reconcile_events.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/set_fractional_policy.py --dry-run
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/fix_secondary_dividend_dates.py --dry-run
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/smoke_validation_api.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/replay_3a3_2.py --out data/replay_3a3_2_2_1.json
```

## 7. 测试局限

1. 行情用构造数据（`pd.bdate_range` + 人工收盘），不覆盖真实停牌/跳空
2. 分红发放日用构造日期，不验证真实 T+3~T+7 分布
3. `cash_compensation` 路径只有单元测试，本库无真实案例
4. 登记日 fail closed 只有构造测试，本库 0 条触发
5. 未做性能与并发测试
6. 本报告的测试结果是 DSH 会话内本地执行结果，**不是外部独立测试**
