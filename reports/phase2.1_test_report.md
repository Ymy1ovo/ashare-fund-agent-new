# 阶段2.1 测试报告

- 测试命令：`.\.venv\Scripts\python.exe -m pytest -q`
- 测试结果：**88 passed，0 failed**
- 耗时：约 10.33 秒
- 警告：1 条 Starlette `httpx` TestClient 弃用提示，非业务失败
- 日志：`logs/pytest_phase21.log`
- 环境：Windows / Python 3.11.2 / pytest 9.2.0

## 1. 回归结果

- 阶段2原有 82 项测试全部通过。
- 新增 6 项阶段2.1测试全部通过。
- 合计 88 项。

## 2. 新增测试

| 测试 | 验证内容 |
| --- | --- |
| `test_cagr_uses_elapsed_trading_days_not_valid_count` | 100、缺失、110、120 使用 252/3，而非 252/2 |
| `test_cagr_without_missing_keeps_old_definition` | 连续序列保持旧 CAGR 定义 |
| `test_ema_resets_after_missing_and_does_not_use_old_state` | 缺失前不变、缺失日 NaN、缺失后重新积累 |
| `test_ema_prefix_does_not_change_when_future_changes` | 修改断点后行情不改变断点前 EMA |
| `test_macd_resets_after_missing_and_requires_reaccumulation` | EMA12/26/DEA 重置换算、重新积累期 NaN、未来修改不影响前缀 |
| `test_daily_cagr_matches_range_summary_with_missing_day` | 日表 CAGR 与区间摘要一致，缺失天数计入 |

## 3. 测试文件分布

| 文件 | 数量 |
| --- | ---: |
| `tests/test_indicator_formulas.py` | 15 |
| `tests/test_indicator_engine.py` | 9 |
| `tests/test_task_status.py` | 9 |
| `tests/test_price_adjustment.py` | 9 |
| `tests/test_api_indicators.py` | 2 |
| 原有阶段1/1B/1B.1测试 | 44 |
| **合计** | **88** |

## 4. 未验证/限制

- 外部 AKShare 网络稳定性不属于离线测试。
- 指标公式未与商业终端逐项对拍。
- 46 只实际计算仍为 26 success / 20 partial；partial 来自真实数据缺口，不是测试失败。
- 没有通过填充缺失价格提高覆盖率。
