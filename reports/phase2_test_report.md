# 阶段2 测试报告

> 阶段2历史测试报告（82项）；阶段2.1修复后的实际测试见 `phase2.1_test_report.md`（88项）。

- 测试命令：`.\.venv\Scripts\python.exe -m pytest -v`
- 测试结果：**82 passed**
- 失败：0
- 耗时：约 10.10 秒
- 警告：1 条 Starlette `httpx` TestClient 弃用提示，非业务失败
- 测试日志：`logs/pytest_phase2.log`
- 环境：Windows / Python 3.11.2 / pytest 9.2.0

## 1. 测试分布

| 测试文件 | 数量 | 覆盖内容 |
| --- | ---: | --- |
| `tests/test_task_status.py` | 9 | success/partial/failed 状态与退出码；原始+复权组合状态 |
| `tests/test_price_adjustment.py` | 9 | 正常/除权转换、缺失复权、零价、无穷因子、OHLC 异常、快照混用、日历缺口、重复日期 |
| `tests/test_indicator_formulas.py` | 10 | 收益、MA/EMA、RSI、MACD、波动率、回撤、ATR、夏普/索提诺/Calmar |
| `tests/test_indicator_engine.py` | 8 | 引擎成功、缺失复权、零成交量、快照混用拒绝、未来函数、增量保存、参数版本、部分失败、过期快照 |
| `tests/test_api_indicators.py` | 2 | 指标详情、参数错误、无数据、overview、ranking、过期快照 |
| 原有阶段1/1B/1B.1测试 | 44 | 行情、快照、同步、超时、迁移、原 API 回归 |
| **合计** | **82** | |

## 2. 关键验收测试

### 退出码与状态

- 全部 success → 0。
- 部分 success + failed/empty → 2。
- 全部 failed/empty → 1。
- 原始行情 success、复权 partial → 整体 partial，不再报告 success。
- 复权 failed 不会因原始行情成功而被忽略。

### 价格口径

- 正常与除权除息后统一因子转换。
- 缺失 `adjusted_close`、`raw_close<=0`、负/无穷因子、OHLC 关系异常均标记 invalid。
- 原始 OHLC 在转换前后逐行一致。
- 多快照拒绝计算。
- 交易日历缺口只标记缺口，不把非交易日当缺失。

### 公式

- 人工小序列核对收益、MA、EMA、RSI、MACD、波动率、回撤、ATR、风险比率。
- RSI 使用 Wilder 平滑并核对初始窗口/极端值。
- MACD 柱按 `2 × (DIF - DEA)`。
- 波动率 ddof=1，年化 `sqrt(252)`。
- 零波动/零回撤时风险比率为空，不返回无穷大。

### 未来函数

- 先计算 T 日指标，再人为把 T 日之后的价格、成交量放大。
- 重新计算相同截止日，T 日及之前所有指标逐行完全一致。

### 数据库

- 重复计算 UPSERT 不产生重复行。
- 参数变化生成新版本，旧版本保留。
- 复权快照变化后旧指标能被识别为 `stale`。
- 旧库迁移保留行情并新增指标表。
- 空数据/单只失败/多只部分失败均被处理。

## 3. 未验证或限制

- 外部 AKShare 网络稳定性不属于离线测试范围。
- 指标公式是项目定义口径，未与商业终端逐项对拍。
- 46 只实际计算结果中 20 只为 `partial`，原因是真实数据缺口，不是测试失败。
- 复权价仍来自单一 AKShare 来源，未做跨源复核。
