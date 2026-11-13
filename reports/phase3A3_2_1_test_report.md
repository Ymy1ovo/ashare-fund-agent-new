# 阶段3A.3.2.1 测试报告

- 生成时间：2026-11-13
- 环境：Python 3.11.2 / pytest / Windows
- 命令：`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q`

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| **原有测试**（1A ~ 3A.3.2，385 项 + 上一阶段公司行为测试） | **387** | **387** | 0 | 0 |
| **本阶段新增** | **38** | **38** | 0 | 0 |
| **合计** | **425** | **425** | **0** | **0** |

说明：
- 387 = 阶段 3A.3.1 结束时的 387 项（含 14 项研究测试）
- 38 = `tests/test_corporate_actions.py` 当前全部用例
  （上一阶段 25 项 + 本阶段新增 13 项）

`--collect-only`：**425 tests collected**
`tests/test_corporate_actions.py` 单独运行：**38 passed**
`tests/ --ignore=tests/test_corporate_actions.py`：**387 passed**

## 2. 本阶段新增的 13 项

| # | 场景 | 测试函数 | 结果 |
| ---: | --- | --- | :---: |
| 1 | 除息日价格下跌，经济价值正确连续 | `test_cash_distribution_increases_cash` | ✅ |
| 2 | 除息日应收分红正确 | `test_dividend_receivable_not_available_cash` | ✅ |
| 3 | 发放日前分红不得作为可用现金 | `test_dividend_receivable_not_available_cash` | ✅ |
| 4 | 发放日现金正确转入可用现金 | `test_cash_distribution_increases_cash` | ✅ |
| 5 | 除息日收盘后订单不得使用未到账分红 | `test_order_after_ex_date_cannot_use_unsettled_dividend` | ✅ |
| 6 | 除息日与发放日跨越周末 | `test_dividend_across_weekend_pay_date` | ✅ |
| 7 | 除息日与发放日之间发生其他交易 | `test_trades_between_ex_and_pay_do_not_change_receivable` | ✅ |
| 8 | 无持仓时不得产生分红 | `test_no_position_no_dividend` | ✅ |
| 9 | 同一事件不得重复确认 | `test_same_action_applied_twice_raises` | ✅ |
| 10 | 应收分红、现金余额、总资产三者核对一致 | `test_receivable_cash_total_identity` | ✅ |
| 11 | 缺发放日的分红必须被拒 | `test_dividend_requires_pay_date` | ✅ |
| 12 | 证据等级控制是否应用 | `test_evidence_status_controls_application` | ✅ |
| 13 | 事件内容指纹确定性 | `test_event_fingerprint_deterministic` | ✅ |
| 14 | 事件集合指纹只覆盖给定事件 | `test_events_digest_only_covers_given_events` | ✅ |
| 15 | 事件版本历史保留 | `test_event_version_history_preserved` | ✅ |
| 16 | 内容变化必须改变 input_hash | `test_input_hash_changes_with_event_content` | ✅ |
| 17 | 多批次份额调整批次之和守恒 | `test_multi_lot_split_keeps_lot_sum` | ✅ |

> 部分测试承载多个断言场景（如第 1/4、2/3 分别由同一函数覆盖）；
> 新增测试函数 **13 个**，覆盖 **17 个**要求场景。

## 3. 上一阶段 25 项全部保留

`tests/test_corporate_actions.py` 原有 25 项在本阶段**全部保留并适配**：

| 变更 | 说明 |
| --- | --- |
| 分红测试增加 `pay_date` | 新模型要求分红必须有发放日 |
| 分红断言改为「应收 + 到账」两段 | 不再断言「除息日现金立即增加」 |
| 总资产恒等式改为 `cash + mv + receivable` | 纳入应收 |
| 未确认测试补 `evidence_status` | 证据等级参与判定 |

**没有删除任何断言，只是按新会计模型更新期望值。**

## 4. 其他验证

### 4.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/6e310be0193643c1` | 200（windows=8 grid=8 stress=7，有条件通过） |
| `GET /api/validations/not_exist` | 404 |

`SMOKE_FAILED: 无`

### 4.2 Streamlit AppTest

| 页面 | 异常 | 错误 |
| --- | --- | :---: |
| `3_回测.py` | 无 | 无 |
| `4_策略验证.py` | 无 | 无 |

### 4.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 4.4 事件数量对账

`python scripts/reconcile_events.py` 输出 **14 项校验，失败 0**：

| 校验项 | 结果 |
| --- | :---: |
| 原始抓取 == 去重后（166） | OK |
| 样本内+样本外==区间内（81） | OK |
| 区间内+区间外==总数（166） | OK |
| split 分区间之和==合计（23） | OK |
| reverse_split 分区间之和==合计（22） | OK |
| cash_distribution 分区间之和==合计（121） | OK |
| 类型合计==去重总数（166） | OK |
| official_confirmed 分区间之和==合计（144） | OK |
| secondary_confirmed 分区间之和==合计（12） | OK |
| unverified 分区间之和==合计（10） | OK |
| rejected 分区间之和==合计（0） | OK |
| 证据等级合计==去重总数（166） | OK |
| 应用事件数<=可应用事件数（79 ≤ 81） | OK |

### 4.5 行情指纹

| 项 | 值 |
| --- | --- |
| 算法 | `market-fingerprint-v3` |
| 行数 | 116,609 |
| SHA256 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 本阶段是否改变 | **否** |

### 4.6 事件数据指纹

| 区间 | 事件数 | 指纹 |
| --- | ---: | --- |
| 样本内 | 49 | `3622b154eef724d664d96df548bfa6473f88ee1a4ffbf422eed34ebb519ea4bf` |
| 样本外 | 31 | `60f9ae2cd3b43adb7d2f6943d1ab1691c3d4b2da8fd90ea68c6ed2815d3880f0` |

### 4.7 人工账本抽查

`510300` 2021-01-18 除息（每份 0.072 元），初始资金 100 万，满仓 180,200 份：

| 检查 | 值 | 判断 |
| --- | ---: | --- |
| 登记日锁定份额 | 180,200 | ✅ |
| 应收金额 | 180,200 × 0.072 = 12,974.40 | ✅ |
| 除息日现金 | 402.14（未变） | ✅ |
| 除息日应收 | 12,974.40 | ✅ |
| 除息日总资产 | 1,006,819.14 | ✅ 无虚假亏损 |
| 发放日（01-21）现金 | 13,376.54（+12,974.40） | ✅ |
| 发放日应收 | 0 | ✅ |

## 5. 未验证项

| # | 项 | 原因 | 风险 |
| ---: | --- | --- | --- |
| 1 | 剩余 39 条历史验证记录的重放 | 单次约 28 分钟，全量约 17 小时 | 数值仍为旧口径，已标记 legacy |
| 2 | 真实券商对账单核对 | 无对账单数据 | 无法验证绝对正确性 |
| 3 | 发放日实际到账的银行延迟 | 回测不模拟 | 影响可忽略 |
| 4 | 公告正文的人工复核 | 144 条靠程序核对 4 项要素 | 解析可能有误，已设 secondary 中间档 |
| 5 | 极端场景（停牌 + 拆分 + 分红叠加） | 未构造 | 理论上有风险 |
| 6 | 同一 ETF 同日多个同类型事件 | 现实不存在，唯一约束也禁止 | 无 |

## 6. 失败与跳过

| 项 | 数量 |
| --- | ---: |
| 失败 | **0** |
| 错误 | **0** |
| 跳过（skip） | **0** |
| xfail | **0** |
| 警告 | 1（Starlette `httpx` 弃用警告，与本次改动无关） |

## 7. 复现命令

```bash
cd D:\ymy\jj-agent

# 全量测试
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q

# 公司行为专项
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_corporate_actions.py -q

# 事件数量对账
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/reconcile_events.py

# 事件指纹
PYTHONUTF8=1 .venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'.');\
from app.backtest.corporate_actions import load_actions,compute_events_digest;\
print(compute_events_digest([a for a in load_actions(start='2025-01-02',end='2026-11-09') if a.is_confirmed]))"

# API 冒烟
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/smoke_validation_api.py

# 回测重放
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/replay_3a3_2.py --out data/replay_3a3_2_1.json
```

## 8. 测试局限

1. 测试用构造行情（`pd.bdate_range` + 人工收盘价），不覆盖真实跳空、停牌
2. 分红测试的「发放日」用构造日期，不验证真实 T+3~T+7 分布
3. 未做性能测试
4. 未做并发测试
