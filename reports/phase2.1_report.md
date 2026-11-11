# 阶段2.1 交付报告：CAGR时间口径与EMA/MACD断点修复

> 本文件是阶段2.1历史报告；区间风险摘要的后续修复见 `phase2.2_report.md`。

- 项目：A股基金量化分析 Agent V1.0
- 阶段：2.1
- 完成时间：2026-11-09
- 指标引擎版本：`v1.0.1-30b821a1af15`
- 旧版本：`v1.0.0-30b821a1af15`（完整保留）
- 结论：**CAGR已改为实际交易日跨度；EMA/MACD已按缺失断点重置；46只ETF全部重算；88项测试全部通过。**

## 1. CAGR修复

### 原问题

旧实现使用“有效前复权价格数量 - 1”作为年化时间分母，中间的缺失交易日被从时间跨度中删除，导致年化收益可能被高估。

### 新口径

```text
实际经过的交易日间隔 = 最后有效价格的交易日索引 - 首个有效价格的交易日索引
CAGR = (P_end / P_start) ^ (252 / 实际经过的交易日间隔) - 1
```

- 使用交易日历索引位置，不使用自然日。
- 缺失交易日计入跨度，不填充价格。
- 扩展日表CAGR和区间摘要使用同一口径。
- 区间摘要新增 `span_trading_days`、`elapsed_trading_intervals`、`valid_price_days`、`missing_trading_days`。
- 有缺失时质量报告记录 `cagr_missing_trading_days`，相关行仍标记 invalid/partial。

### 人工验收

序列：

```text
第1交易日 100
第2交易日 缺失
第3交易日 110
第4交易日 120
```

- 实际跨度 3 个交易日间隔。
- 年化指数 `252/3`，不是 `252/2`。
- 日表最后一日 CAGR 与区间摘要 CAGR 相等。
- 无缺失序列仍使用原定义，结果不变。

## 2. EMA/MACD断点修复

### EMA

- 连续有效区间内仍等价于 `ewm(span=n, adjust=False, min_periods=n)`。
- 遇到无效价格或交易日历缺口：缺失日输出 NaN，EMA 状态重置。
- 断点后重新积累满 n 个连续有效观察才输出。
- 不把缺失日当作价格不变，不沿用断点前状态。

### MACD

- EMA12、EMA26 使用同一断点重置规则。
- DIF 在 EMA26 重新满足最小样本前为 NaN。
- DEA 只在 DIF 连续有效后重新积累 9 个有效样本。
- MACD柱 = `2 × (DIF - DEA)`，断点期间不输出。
- 修改缺失点之后行情，不改变缺失点之前指标。

## 3. 实际重算结果

- 命令：`python scripts/calculate_indicators.py --all --full-rebuild`
- ETF：46/46 全部重算
- 状态：26 success、20 partial、0 failed
- 新版本行数：116,764
- 旧版本行数：116,764
- 合计指标行：233,528
- 旧版本是否保留：是
- 新旧快照 ID 不一致行：0
- 计算耗时：约 50 秒

20 只 partial 仍来自真实数据缺口，没有通过填充缺失价格或删除样本提高覆盖率。

## 4. CAGR修复前后对比

完整表见 `reports/phase2.1_cagr_comparison.md`。

| 项目 | 数值 |
| --- | ---: |
| 旧版本行 | 116,764 |
| 新版本行 | 116,764 |
| 可比 CAGR 行 | 116,414 |
| CAGR 变化行 | 42,448 |
| 单行最大绝对变化 | 3.770016 |
| 最新日期变化 ETF | 20 / 46 |
| 最新日期最大绝对变化 | 0.004286 |

最新日期示例：

| 代码 | 旧 CAGR | 新 CAGR | 变化 |
| --- | ---: | ---: | ---: |
| 510050 | 19.2288% | 18.8002% | -0.4286 pp |
| 510880 | 11.6711% | 11.5661% | -1.0500 pp |
| 511030 | 3.0012% | 2.9272% | -0.0741 pp |
| 159936 | 5.4654% | 5.3404% | -0.1250 pp |
| 510300 | 6.4731% | 6.4731% | 0 |

> 早期行的 CAGR 绝对变化可能很大，是因为早期价格基数小、年化指数对时间跨度敏感；这来自时间分母修正，不是收益率数据被篡改。

## 5. EMA/MACD修复前后对比

完整统计见 `reports/phase2.1_ema_macd.md`。

| 指标 | 可比行 | 变化行 | 最大绝对变化 |
| --- | ---: | ---: | ---: |
| ema12 | 114,923 | 4,077 | 0.135558 |
| ema26 | 113,634 | 7,911 | 0.126617 |
| macd_dif | 113,634 | 7,911 | 0.113543 |
| macd_dea | 112,963 | 7,725 | 0.087347 |
| macd_hist | 112,963 | 7,582 | 0.055702 |

变化集中在有缺失或日历缺口的 ETF/日期；连续正常行情内仍保持原公式定义。

## 6. 原始行情与快照保护

- 原始行情：116,609 条，未修改。
- 复权快照：46 只当前快照未变。
- 原始 OHLC 一致性检查：`raw_unchanged=True`。
- 旧指标版本、旧指标行、旧运行记录均保留。
- 未删除旧版本，未修改原行情表。

## 7. 测试

- 旧阶段测试：82 项全部通过。
- 新增阶段2.1测试：6 项全部通过。
- 总计：**88 passed，0 failed**，约 10.33 秒。
- 新增覆盖：CAGR缺失交易日、CAGR无缺失定义、EMA断点、EMA未来修改、MACD断点、日表与摘要CAGR一致性。
- 详细见 `reports/phase2.1_test_report.md`。

## 8. API与看板

- `/api/indicators/overview`：200，46 只。
- `/api/indicators/510300`：返回 `v1.0.1`，snapshot=110，stale=false。
- 显式查询旧版本 `v1.0.0` 仍返回 200。
- Streamlit 主看板与指标页 AppTest 均 0 异常。
- 实际 API 健康：140 次指标运行、233,528 条指标行（含两个版本）。

详细见 `reports/phase2.1_api_test.md`。

## 9. 修改文件

- `app/quant/config.py`：引擎版本 1.0.0 → 1.0.1
- `app/quant/returns.py`：CAGR 改用交易日索引位置差
- `app/quant/risk.py`：区间摘要改用交易日跨度并记录缺失数量
- `app/quant/trend.py`：新增 `ema_with_reset`，EMA 断点重置
- `app/quant/momentum.py`：MACD 使用断点重置 EMA
- `app/quant/engine.py`：质量字段增加 CAGR 缺失天数
- `tests/test_indicator_formulas.py`：新增 CAGR/EMA/MACD 测试
- `tests/test_indicator_engine.py`：版本更新、日表/摘要一致性测试
- `scripts/compare_phase21.py`：前后对比报告生成器
- `scripts/indicator_quality_report.py`：只统计当前指标版本
- `reports/phase2_formula_spec.md`、`README.md`
- 新增 `reports/phase2.1_*` 报告
- `README.md`、`scripts/package_release.py` 更新
- 交付 ZIP：`dist/Ashare-Fund-Agent_phase2.1_20261109.zip`

## 10. 未完成事项

- 未开发阶段3策略、回测和自动交易。
- 仍为单一 AKShare qfq 来源，未做分红公告独立重算或跨源复核。
- 20 只 ETF 仍为 partial，原因是真实交易日缺口/复权缺失/零成交量。
- 指标未与商业终端逐项对拍。
- 后复权未落地主表。

## 11. 最终明确回答

1. **CAGR是否按实际交易日跨度计算？** 是。日表和区间摘要都用交易日索引位置差，缺失交易日计入跨度。
2. **EMA/MACD是否已正确处理缺失断点？** 是。缺失日 NaN，EMA12/26/DEA 重置并重新积累，不沿用旧状态。
3. **82项旧测试和新增测试是否全部实际通过？** 是。旧82项 + 新增6项 = **88 passed，0 failed**。
4. **46只ETF是否全部重新计算？** 是。46/46 已用 v1.0.1 重算，26 success、20 partial、0 failed，旧版本保留。
5. **是否建议正式进入阶段3？** 建议进入阶段3，但先确认20只 partial 数据缺口的处理策略和回测快照固定规则；本轮未开始阶段3。
