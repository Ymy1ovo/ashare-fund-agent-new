# 阶段3A.3.2.2 测试报告（含 3A.3.2.2.1 / 3A.3.2.2.2）

- 生成时间：2026-11-13
- 涵盖阶段：3A.3.2.2 + 3A.3.2.2.1 + 3A.3.2.2.2
- 环境：Python 3.11.2 / pytest / Windows

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.1） | **425** | 425 | 0 | 0 | 0 |
| **3A.3.2.2** 新增 | **29** | 29 | 0 | 0 | 0 |
| **3A.3.2.2.1** 新增 | **15** | 15 | 0 | 0 | 0 |
| **3A.3.2.2.2** 新增 | **15** | 15 | 0 | 0 | 0 |
| **合计** | **484** | **484** | **0** | **0** | **0** |

`--collect-only`：**484 tests collected**
`tests/test_corporate_actions.py`：**97 passed**（基线 82 + 本轮 15）
其他测试：**387 passed**

## 2. 3A.3.2.2.2 新增的 15 项

### 2.1 问题1：加载失败 fail closed（5 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 1 | `test_missing_action_table_raises` | 事件表被 DROP → 抛 `CorporateActionLoadError` |
| 2 | `test_broken_action_row_raises` | 表结构缺列 → 抛错 |
| 3 | `test_invalid_action_structure_raises` | 脏数据（比例 NULL）→ 抛错，不静默过滤 |
| 4 | `test_disable_flag_marks_non_formal` | `apply_corporate_actions=False` → 标记非正式 |
| 5 | `test_formal_run_keeps_formal_basis` | 正常运行 → `formal_valuation=True` |

### 2.2 问题2：分红强制登记日（5 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 6 | `test_cash_distribution_requires_pay_date` | 缺 `pay_date` → 构造即抛 |
| 7 | `test_cash_distribution_requires_cash_per_share` | 缺金额 → 构造即抛 |
| 8 | `test_record_date_after_ex_date_rejected` | 登记日晚于除息日 → 抛 |
| 9 | `test_pay_date_before_ex_date_rejected` | 发放日早于除息日 → 抛 |
| 10 | `test_blocked_reason_missing_record_date_holding` | 登记日非交易日 → `invalid_record_date` |

### 2.3 问题3：同日时序（5 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 11 | `test_same_day_record_and_ex_date_buying_today_gets_dividend` | 当日买入 → 享有分红 |
| 12 | `test_same_day_record_and_ex_date_selling_today_reduces_dividend` | 当日卖出 → 不享有 |
| 13 | `test_same_day_dividend_not_locked_before_fills` | 锁定值 == 收盘持仓，非开盘前持仓 |
| 14 | `test_same_day_dividend_settles_on_pay_date` | 应收在发放日转现金 |
| 15 | `test_same_day_dividend_not_double_confirmed` | 应收峰值 == 单次金额，到账 1 笔 |

## 3. 本轮升级但未新增的测试（2 项）

| 测试 | 3A.3.2.2.1 | 3A.3.2.2.2 |
| --- | --- | --- |
| `test_dividend_requires_record_date_in_range` | 引擎阻断 | **构造阶段拒绝**（更强） |
| `test_secondary_dividend_with_unverified_record_date_not_applied` | 引擎阻断 | **构造阶段拒绝**（更强） |

## 4. 3A.3.2.2.1 的 15 项（保留）

| 归属 | 数量 |
| --- | ---: |
| 零碎规则（unknown / 阻断 / 明确规则） | 5 |
| 现金补偿（缺依据 / 用官方价 / 进指纹） | 3 |
| 登记日资格 | 6 |
| 版本历史 | 1 |

## 5. 其他验证

### 5.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/<最新>` | 200 |
| `GET /api/validations/not_exist` | 404 |

`SMOKE_FAILED: 无`

### 5.2 Streamlit AppTest

| 页面 | 异常 | 错误 |
| --- | --- | :---: |
| `dashboard/pages/3_回测.py` | 0 | 0 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 |

### 5.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 5.4 数据迁移幂等性

在 `fund_agent_pre_3a3_2_2_2_20261113.db` 副本上连续执行 `init_db()` 两次：

| 表 | 前 | 后 |
| --- | ---: | ---: |
| `etf_daily_prices` | 116,609 | 116,609 |
| `validation_runs` | 44 | 44 |
| `backtest_runs` | 11 | 11 |
| `corporate_actions` | 166 | 166 |
| `corporate_action_applications` | 3,787 | 3,787 |
| `corporate_action_versions` | 704 | 704 |
| `dividend_receivables` | 785 | 785 |

**数据未变、幂等。本轮无 schema 变更。**

### 5.5 事件对账脚本

`python scripts/reconcile_events.py` → **校验项 14，失败 0**

### 5.6 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本轮是否改变 | **否** |

### 5.7 事件指纹

| 区间 | 应用事件数 | 指纹 |
| --- | ---: | --- |
| 样本内 | 29 | `855dc11a43a8…` |
| 样本外 | 30 | `d87fb1e3c926…` |

与 3A.3.2.2.1 一致（本轮未改事件内容）。

### 5.8 历史记录完整性

| 表 | 数量 | 是否被删改 |
| --- | ---: | :---: |
| `backtest_runs` | 11 | **否** |
| `validation_runs` | 44 | **否** |
| `corporate_actions` | 166 | **否** |
| `corporate_action_versions` | 704 | **否** |

## 6. 失败与跳过

| 项 | 数量 |
| --- | ---: |
| 失败 | **0** |
| 错误 | **0** |
| 跳过 | **0** |
| xfail | **0** |
| 警告 | 1（Starlette `httpx` 弃用，与改动无关） |

## 7. 复现命令

```bash
cd D:\ymy\jj-agent

PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_corporate_actions.py -q
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/reconcile_events.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/smoke_validation_api.py
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/replay_3a3_2.py --out data/replay_3a3_2_2_2.json
```

## 8. 测试局限

1. 行情用构造数据（`pd.bdate_range` + 人工收盘价），不覆盖真实停牌/跳空
2. 同日时序只有构造测试，本库 4 条同日事件全在 2021 年前
3. 加载失败测试用 DROP TABLE / ALTER TABLE 模拟，未覆盖磁盘损坏等极端情形
4. 未做性能与并发测试
5. 测试结果是 DSH 会话内本地执行结果，**不是外部独立测试**
