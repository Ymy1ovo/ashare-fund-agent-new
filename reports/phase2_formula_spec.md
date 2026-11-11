# 阶段2 指标公式与数据口径说明

## 1. 价格口径

统一使用前复权收盘价 `adjusted_close`。每日调整因子：

```text
factor_t = adjusted_close_t / raw_close_t
adjusted_open_t  = raw_open_t  × factor_t
adjusted_high_t  = raw_high_t  × factor_t
adjusted_low_t   = raw_low_t   × factor_t
adjusted_close_t = 数据库已有 adjusted_close_t
```

有效条件：

- `raw_close_t > 0` 且原始 OHLC 完整、为正；
- `adjusted_close_t` 存在且大于 0；
- `factor_t` 为有限正数；
- 原始 OHLC 与复权 OHLC 满足 `low <= open/close <= high`；
- 同一 ETF 一次计算只允许一个 `adjustment_snapshot_id`，混合快照直接拒绝。

不合法行保留在结果中，标记 `price_status=invalid` 与 `quality_reasons`，相关指标为空；不删除、不填 0、不用前值补齐。原始 OHLC 永不写回修改。

## 2. 收益率

- 单日：`r_t = P_t / P_{t-1} - 1`
- n 日：`R_t(n) = P_t / P_{t-n} - 1`
- n 日窗口要求 n+1 个交易日的复权价全部有效；有缺失则该日为空。
- 区间累计：请求区间首个有效复权价到最后一个有效复权价。
- CAGR 的时间分母使用**交易日历索引的实际跨度**，不是有效价格数量：
```

CAGR = (P_end / P_start) ^ (252 / 实际经过的交易日间隔数) - 1
实际经过的交易日间隔数 = 最后有效价格的日历位置 - 首个有效价格的日历位置
```
- 缺失交易日不会被从时间跨度中删除。例如 `100、缺失、110、120` 的跨度是 3 个交易日间隔，指数用 `252/3`，不能用 `252/2`。
- 日表 `cagr` 是从该 ETF 首个有效复权价到当日的扩展 CAGR，不使用未来数据；同样使用日历位置差。
- 区间摘要与日表使用同一交易日跨度口径；摘要额外记录 `span_trading_days`、`valid_price_days`、`missing_trading_days`。
- 没有缺失行的历史序列，日历位置差等于有效价格数量减 1，结果与旧定义一致。
- 年化计算不使用自然日数；缺失数量会记录在质量报告中，不通过填充价格消除。

## 3. 趋势

- `MA_n = close.rolling(n, min_periods=n).mean()`
- EMA 在连续有效行情段内与 `ewm(span=n, adjust=False, min_periods=n)` 等价。
- 实现窗口：MA5/10/20/30/60/120/250，EMA12/26。
- 历史不足或窗口内含缺失值时不输出，不提前填充。
- 遇到无效价格或交易日历缺口：缺失日输出 NaN，EMA 状态重置；之后重新积累满 n 个连续有效观察才输出。
- 不把缺失日当作价格不变，不沿用断点前状态。

## 4. RSI（Wilder）

1. `delta_t = close_t - close_{t-1}`
2. 上涨幅度 `gain_t = max(delta_t, 0)`，下跌幅度 `loss_t = max(-delta_t, 0)`
3. 每段连续有效序列，前 n 个涨/跌幅取简单平均作为初始值。
4. 之后：

```text
avg_gain_t = (avg_gain_{t-1} × (n-1) + gain_t) / n
avg_loss_t = (avg_loss_{t-1} × (n-1) + loss_t) / n
RSI_t = 100 - 100 / (1 + avg_gain_t / avg_loss_t)
```

5. 遇到缺失值/日期缺口时重置，重新积累 n 个有效涨跌幅。
6. `avg_loss=0` 且 `avg_gain>0` 时 RSI=100；两者都为 0 时 RSI=50。
7. 周期：RSI6/12/24。

## 5. MACD

```text
DIF = EMA12(close) - EMA26(close)
DEA = EMA9(DIF)
MACD柱 = 2 × (DIF - DEA)
```

EMA 使用 `adjust=False`、`min_periods=span`。本项目的 MACD 柱是 2 倍差值，不采用其他平台的单倍柱定义。

断点规则：EMA12/EMA26 遇到缺失/无效价格时重置；DIF 在 EMA26 满足最小样本前为 NaN；DEA 只在 DIF 连续有效后重新积累 9 个样本，之前返回 NaN。缺失日不输出 MACD 值。

## 6. 波动率与回撤

- 日收益：在原始交易日索引上计算 `pct_change(fill_method=None)`；缺失日保留 NaN，不压缩缺失日期。
- 单日收益只存在于相邻两个有效交易日之间；跨缺口的收益不会被当成单日收益。
- 年化历史波动率：

```text
vol_n = std(真实相邻日收益, window=n, ddof=1) × sqrt(252)
```

- `ddof=1` 全文统一；真实相邻日收益样本不足 2 个时返回空值。
- 区间摘要和滚动风险指标使用同一个 `daily_return_series()`，不各写一套压缩逻辑。
- 区间摘要记录 `daily_return_observations`，与有效价格天数、缺失交易日数一起展示。
- 滚动最大回撤：在 n 个交易日窗口内计算 `P_t / cummax(P) - 1` 的最小值。
- 扩展最大回撤 `max_drawdown_all`：截至当日，只用当日及之前数据。
- 区间最大回撤：请求区间内首个有效价格至最后有效价格。

## 7. ATR14

使用统一复权 OHLC：

```text
TR_t = max(high_t - low_t,
           abs(high_t - close_{t-1}),
           abs(low_t - close_{t-1}))
```

TR 使用 Wilder 平滑：前 14 个有效 TR 的简单平均为初始 ATR，之后：

```text
ATR_t = (ATR_{t-1} × 13 + TR_t) / 14
```

缺失/缺口处重置，不用前值填充。

## 8. 风险收益指标

- 年化收益：与 CAGR 相同的年化口径。
- 夏普：

```text
Sharpe = (年化收益 - risk_free_rate) / 年化波动率
```

- 索提诺：

```text
下行波动率 = sqrt(mean(min(日收益 - 日无风险收益, 0)^2)) × sqrt(252)
Sortino = (年化收益 - risk_free_rate) / 下行波动率
```

- Calmar：

```text
Calmar = 年化收益 / abs(最大回撤)
```

- 日表风险指标使用滚动 `risk_window=252` 个交易日；区间摘要使用请求区间的全部真实相邻日收益。
- 区间摘要的年化收益使用阶段2.1实际交易日跨度 CAGR；波动率/夏普/索提诺只使用真实相邻日收益。
- 波动率、下行波动率、最大回撤为 0，或结果非有限时，返回空值/NULL，不输出无穷大。
- 最大回撤使用有效价格观察序列的峰值/谷值，不填充缺失价格，不把缺失价格当 0。
- `risk_free_rate` 默认 0，可通过 CLI/API 参数配置并写入运行记录。

## 9. 缺失与状态

- `adjusted_close` 缺失：该行价格无效，相关指标为空。
- 原始 OHLC 缺失/非法：价格无效。
- 成交量为 0：`trade_status=zero_volume`，价格仍可计算，但标记警告。
- 成交量缺失：`trade_status=missing_volume`。
- 交易日历缺口：生成缺失行的指标为空，并记录 `missing_trading_dates`。
- 非交易日不进入行情索引，不当作缺失。
- 快照混用：拒绝计算。
- 历史不足：对应指标为空，覆盖率报告中体现。

## 10. 版本与防未来函数

- 计算版本 = 引擎版本 + 完整参数 JSON 的 SHA256 前 12 位。
- 同一版本/快照重复计算使用主键 UPSERT，不重复插入。
- 参数变化生成新版本，旧版本行保留。
- 复权快照变化后，旧指标行保留但 API 标记 `stale=true`。
- 所有日指标仅使用当日及之前数据；测试会修改 T 日之后行情并比较 T 日结果。
