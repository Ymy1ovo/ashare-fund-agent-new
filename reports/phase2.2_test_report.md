# 阶段2.2 测试报告

- 命令：`.\.venv\Scripts\python.exe -m pytest -q`
- 结果：**93 passed，0 failed**
- 耗时：约 10.40 秒
- 警告：1 条 Starlette `httpx` TestClient 弃用提示，非业务失败
- 日志：`logs/pytest_phase22.log`

## 1. 回归构成

| 项目 | 数量 | 结果 |
| --- | ---: | --- |
| 阶段2.1原有测试 | 88 | 全部通过 |
| 阶段2.2新增测试 | 5 | 全部通过 |
| 合计 | **93** | **全部通过** |

## 2. 新增测试

| 测试 | 验证内容 |
| --- | --- |
| `test_risk_summary_continuous_series_keeps_old_result` | 连续行情 100/101/102/103 保持原结果 |
| `test_risk_summary_does_not_treat_gap_return_as_single_day` | 100/缺失/110/120，100→110 不作为单日收益；样本不足返回 None |
| `test_risk_summary_consecutive_missing_keeps_sample_count` | 100/缺失/缺失/120/121，仅 120→121 是有效单日收益 |
| `test_risk_future_data_does_not_change_past_values` | 修改未来行情不改变过去风险指标 |
| `test_summary_and_compute_risk_share_missing_return_dates` | 摘要与滚动风险共用缺失日收益口径 |

## 3. 关键断言

- 缺口后的第一笔跨日收益为 NaN，不进入波动率/夏普/索提诺。
- 有效单日收益少于 2 个时，年化波动率、夏普、索提诺为 None。
- 连续缺失不填充，不把缺失日当价格不变。
- CAGR 仍使用阶段2.1的交易日跨度，不回退。
- 最大回撤使用有效价格序列，不填充缺失价格。
- 修改测试日期之后行情，不改变之前风险指标。

## 4. 未验证/限制

- 外部 AKShare 网络稳定性不属于离线测试。
- 46 只 ETF 中 20 只仍是 partial，原因是实际数据缺口；没有通过填充提高覆盖率。
- 指标公式未与商业终端逐项对拍。
