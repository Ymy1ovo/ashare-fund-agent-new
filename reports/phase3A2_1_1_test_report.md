# 阶段3A.2.1.1 测试报告

- 执行时间：2026-11-11
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 基线提交：`0cdb80af75633146a23ad36dfbdab7df79db36db`
- 执行方式：DSH 在当前工作区实际运行

## 一、全量测试结果（DSH 实际执行）

```powershell
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

| 项目 | 数值 |
| --- | ---: |
| 测试总数 | **276** |
| 通过 | **276** |
| 失败 | **0** |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 26.63s |

### 数量构成

| 来源 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段3A.1.1 及之前 | 154 | 全部通过，无回退 |
| 阶段3A.2 | 55 | 全部通过，无删减 |
| 阶段3A.2.1 | 40 | 全部通过，无删减 |
| 阶段3A.2.1.1 新增 | **27** | 全部通过 |
| **合计** | **276** | **全部通过** |

未删除任何原有测试，未跳过任何测试，未降低任何断言标准。

## 二、新增测试清单（27 项）

### 任务1：碎股卖出（14 项）

| 测试 | 覆盖点 | 结果 |
| --- | --- | --- |
| `test_sell_quantity_uses_whole_lots_when_enough` | 足够一手时按整手申报 | 通过 |
| `test_sell_quantity_allows_odd_only_when_below_one_lot` | 不足一手才允许零股 | 通过 |
| `test_sell_quantity_never_exceeds_available` | 不超过可卖量 | 通过 |
| `test_sell_quantity_zero_inputs` | 零/负输入返回 0 | 通过 |
| `test_odd_lot_never_produced_from_full_lots` | **根因回归**：整手持仓不留 1 股 | 通过 |
| `test_normal_whole_lot_sell_full_fill` | A. 正常整手卖出 | 通过 |
| `test_odd_lot_holding_sold_in_one_shot` | B. 零股一次性卖出 | 通过 |
| `test_sell_proceeds_below_min_commission_rejected_when_cash_short` | C. 收入<佣金且现金不足→拒单 | 通过 |
| `test_sell_proceeds_below_fee_allowed_when_cash_covers` | D. 收入<佣金但现金够→成交 | 通过 |
| `test_min_commission_per_fill_not_per_share` | F. 最低佣金按笔不按股 | 通过 |
| `test_multiple_sell_orders_each_pay_commission` | F. 多笔订单各收一次 | 通过 |
| `test_cash_and_position_consistency_after_sell` | H/I. 现金与持仓一致 | 通过 |
| `test_no_negative_cash_across_many_odd_sells` | J. 现金不得为负 | 通过 |
| `test_partial_fill_keeps_remaining_and_fee_aligned` | E/G. 部分成交费用一致 | 通过 |

### 任务3：指纹 v3（8 项）

| 测试 | 覆盖点 | 结果 |
| --- | --- | --- |
| `test_fingerprint_v3_version_and_fields` | 版本与字段清单 | 通过 |
| `test_fingerprint_v3_detects_adjustment_type_change` | adjustment_type 变化可检测 | 通过 |
| `test_fingerprint_v3_detects_coverage_change` | 覆盖起止变化可检测 | 通过 |
| `test_fingerprint_v3_missing_field_encoding_stable` | 缺失字段编码稳定 | 通过 |
| `test_fingerprint_v3_row_order_independent` | 行顺序不影响 | 通过 |
| `test_fingerprint_v3_reproducible` | 重复计算一致 | 通过 |
| `test_fingerprint_v2_not_misread_as_v3` | v2 不被误读为 v3 | 通过 |
| `test_input_hash_includes_fingerprint_version` | 版本参与 input_hash | 通过 |

### 任务4：预热有效计数（5 项）

| 测试 | 覆盖点 | 结果 |
| --- | --- | --- |
| `test_warmup_counts_valid_prices_only` | 300 条记录含空价格时排除 | 通过 |
| `test_warmup_excludes_non_positive_prices` | 0 与负数不算有效 | 通过 |
| `test_warmup_excludes_oos_data` | OOS 之后数据不参与 | 通过 |
| `test_warmup_250_valid_days_ok` | 250 个有效日满足需求 | 通过 |
| `test_warmup_249_valid_days_partial` | 249 个不满足需求 | 通过 |

### 既有测试适配（`tests/test_validation_fix.py`）

v3 字段增加后，`_sample_rows()`、`row_none/row_nan`、浮点精度测试的元组补 3 个字段；
版本断言从 `startswith("market-fingerprint-v")` 改为 `== "market-fingerprint-v3"`。
**这不是弱化断言，是字段扩展后的必要同步。**

## 三、全池 sparse_data 实跑结果（DSH 实际执行）

### 3.1 代表性池（6 只）

| 项目 | 实测值 |
| --- | ---: |
| 状态 | **success** |
| 删除零散行 | 4,047 |
| 删除连续缺失行 | 32 |
| 副本剩余行 | 112,530 |
| 回测快照数 | 447 |
| 有效收益观测 | 270 |
| 缺失收益观测 | 176 |
| NaN 日 | 1 |
| stale_price 天数 | 544 |
| 订单数 | 807 |
| 成交数 | 700 |
| 部分成交订单 | 115 |
| 负现金天数 | **0** |
| 最终现金 | 5,498.24 |
| 指纹前后一致 | **是** |

### 3.2 全池（41 只）

| 项目 | 实测值 |
| --- | ---: |
| 状态 | **success**（整改前的 failed 已消失） |
| 删除零散行 | 4,047 |
| 删除连续缺失行 | 32 |
| 副本剩余行 | 112,530 |
| 回测快照数 | 447 |
| 有效收益观测 | 269 |
| 缺失收益观测 | 177 |
| NaN 日 | 1 |
| stale_price 天数 | 3,625 |
| 订单数 | 2,004 |
| 成交数 | 1,235 |
| 部分成交订单 | 222 |
| 负现金天数 | **0** |
| 最终现金 | 90,732.11 |
| 最终持仓 | 19 只（明细见 `data/sparse_stress_result.json`） |
| 指纹前后一致 | **是** |

### 3.3 关键验证

- 全池 2,004 笔订单、1,235 笔成交，**负现金天数 0**；
- 副本删除 4,079 行后仍能完成完整回测，无异常中断；
- 源库指纹 `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` 前后一致；
- 缺失日保留在原始交易日索引上，447 天快照对应 269 有效 + 177 缺口 + 1 NaN。

## 四、API 与 Streamlit 冒烟（DSH 实际执行）

| 检查 | 结果 |
| --- | --- |
| `GET /api/validations?limit=5` | 200 |
| `GET /api/validations/{id}` | 200 |
| `GET /api/validations/not_exist` | 404（期望） |
| `GET /health` | 200 |
| Streamlit `4_策略验证.py` AppTest | **0 异常** |

## 五、数据库检查（DSH 实际执行）

| 项目 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| `etf_pool` | 46（未变） |
| `etf_daily_prices` | 116,609（未变） |
| `etf_indicator_daily` | 350,292（未变） |
| `etf_adjustment_snapshots` | 139（未变） |
| `backtest_runs` | 11（未变） |
| 全库指纹 v3 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 历史 validation 记录 | 全部保留，无覆盖 |

压力测试前后行情指纹一致，源库零写入。

## 六、静态代码检查（非运行测试）

以下通过阅读代码确认，未单独构造运行用例：

- `_load_regime_warmup()` 的 SQL 条件 `trade_date < oos_start` 保证不读 OOS 之后数据。
- `build_sparse_copy()` 使用 `sqlite3.backup()`，不执行任何写源库的 SQL。
- `sell_quantity()` 在所有分支都返回 `<= available`。
- 指纹序列化的版本前缀保证 v2 与 v3 结果必然不同。

## 七、尚未验证的事项

1. **未构造「真实数据下预热不足 250 天」的场景**：单测用临时库覆盖，正式库 510300 有 3,064 个有效价格。
2. **未测试并发执行多个验证任务**。
3. **未对 `sparse_data` 的删除比例做敏感性扫描**（固定每 5 日删 1 日 + 2 只连续缺 20 日）。
4. **未验证 data-snapshot 在另一台机器的可恢复性**。
5. **未模拟真实券商的分笔成交逐笔佣金**，仍按单笔订单一次收费。
6. **`sell_proceeds_below_fee` 防护分支在修复后未在真实数据中触发**，仅由单测覆盖。

## 八、结论

| 项目 | 要求 | 实际 | 结论 |
| --- | --- | --- | --- |
| 原有 249 项 | 全部通过 | 249 项全部通过 | 满足 |
| 新增专项 | 全部通过 | 27 项全部通过 | 满足 |
| 全量 | 全部通过 | 276 passed | 满足 |
| 全池 sparse_data | 真实运行并通过 | success，负现金 0 天 | 满足 |
| 代表性池 sparse_data | 通过 | success | 满足 |
| 指纹 v3 | 覆盖复权类型 | 3 个复权字段 | 满足 |
| 预热有效计数 | 按有效价格 | 三量分离 | 满足 |
| 行情未被污染 | 指纹一致 | 一致 | 满足 |
| 历史记录 | 完整保留 | 完整 | 满足 |
