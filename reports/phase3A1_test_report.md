# 阶段3A.1 测试报告

- 命令：`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -v`
- 结果：**144 passed，0 failed**
- 耗时：约 18.08 秒
- 日志：`logs/pytest_phase3a1.log`
- 构成：阶段3A 原有 127 项全部保留通过 + 阶段3A.1 新增 17 项

## 1. 新增测试

### 风险口径（`tests/test_backtest_risk_fix.py`，9 项）

| 测试 | 断言 |
| --- | --- |
| `test_sharpe_uses_mean_daily_excess_not_cagr` | 新 Sharpe 与手算 `mean(r)×sqrt(252)/std(r)` 一致，且与旧 CAGR 口径不同 |
| `test_sortino_uses_downside_deviation_of_excess` | 下行波动率 = `sqrt(mean(min(excess,0)^2))×sqrt(252)`，Sortino 精确匹配 |
| `test_risk_free_rate_is_converted_to_daily` | 年化 rf 按 `(1+rf)^(1/252)-1` 转换 |
| `test_zero_volatility_returns_none_not_infinity` | 零波动返回 None，不返回 inf |
| `test_held_gap_day_excludes_return_from_risk_stats` | 缺口当日与次日都被排除 |
| `test_unheld_gap_does_not_affect_portfolio_risk` | 未持仓 ETF 缺行情不影响组合 |
| `test_no_position_day_uses_cash_return` | 无持仓日按净值变化正常计入 |
| `test_gap_is_not_compressed_into_single_day_return` | 跨缺口收益不压缩成单日收益 |
| `test_max_drawdown_uses_valuation_nav_and_warns` | 回撤用估值净值，同时记录缺口天数与提示 |

### 部分成交（`tests/test_backtest_partial_fill.py`，8 项）

| 测试 | 断言 |
| --- | --- |
| `test_buy_reduced_by_cash_is_partial_not_filled` | 缩量成交标记 partial；剩余 900 股 |
| `test_partial_buy_remaining_is_not_double_counted` | 重复撮合累计不超过原始订单量 |
| `test_partial_sell_keeps_partial_status` | 卖出可全成交时正确标记 filled |
| `test_sell_rejected_when_partial_not_allowed` | 不允许部分成交时整单拒绝 |
| `test_remaining_quantity_property_never_negative` | 剩余数量恒 ≥ 0 |
| `test_fee_only_on_filled_quantity` | 费用只按实际成交额计算 |
| `test_engine_keeps_partial_and_defers_remainder` | 引擎层保留 partial 并续挂剩余 |
| `test_partial_order_not_downgraded_to_rejected` | 部分成交后状态不被覆盖；无超额成交 |

## 2. 回归

- 阶段3A 原有 127 项：全部通过。
- 阶段2.2 及更早的 96 项：全部通过，无回退。
- 合计 144 项。

## 3. 未覆盖/限制

- 分红/拆分事件仍未建模。
- 部分成交只支持"现金不足缩量"与"可卖量不足缩量"，无盘口级撮合。
- 债券/商品 ETF 规则未逐一确认。
