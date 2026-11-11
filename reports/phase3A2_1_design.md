# 阶段3A.2.1 设计说明：策略验证体系缺陷整改

- 编写时间：2026-11-11
- 范围：只修复验证体系缺陷，不开发新策略、不进入 3A.3 / 3B

## 1. 本阶段要解决的四个问题

| # | 问题 | 影响 | 整改方式 |
| ---: | --- | --- | --- |
| 1 | 市场环境分类缺少 OOS 前预热数据 | 2025-01 起 246 个交易日被判 `unclassified`，跨环境结论失真 | 额外加载 OOS 前历史交易日做 MA250 预热 |
| 2 | 行情指纹过弱（行数 + close 和 + volume 和） | 单行字段变化可能不被识别，无法证明数据未被污染 | 全字段确定性序列化 + SHA256，算法版本化 |
| 3 | `sparse_data` / `insufficient` 标记 `skipped` | 不能声称数据压力场景已实测 | 在独立 SQLite 副本上真实执行 |
| 4 | `regime_stats()` 按环境统计可能压缩缺失日 | 跨缺口收益可能被当成单日收益 | 保留原始交易日索引，NaN 显式计数 |

## 2. 任务1：市场环境预热

### 现状（实测）

原 `_build_regime_payload()` 只加载 `split.oos_start ~ split.oos_end` 的 510300 数据。
MA250 需要 250 个交易日，因此 OOS 前 249 天无法分类，报告中出现 246 个 `unclassified`。

### 整改设计

```text
加载：etf_daily_prices 中 code=510300 且 trade_date < oos_start 的全部历史（实测 3,064 行）
拼接：预热段 + OOS 段，统一为 DatetimeIndex，去重后按日期排序
计算：rolling(250).mean()，min_periods=250
输出：output_start=oos_start，预热段只参与 MA 计算，不进入 labels
```

关键约束：

- 预热数据**不计入** OOS 收益、CAGR、Sharpe、最大回撤、交易次数 —— 它只用于 `rolling` 的历史窗口。
- 分类结果**只在 OOS 日期范围内输出**，`RegimeSeries.labels` 的键全部 ≥ `oos_start`。
- 不按自然日偏移，预热按 `trade_date` 实际交易日取。
- 预热不足 250 个交易日时 `warmup.status = "partial"`，前段保持 `unclassified`，不强行分类。
- 输出区间、预热天数、代理 ETF 代码全部写入报告，可追溯。

### 整改后实测

| 项目 | 整改前 | 整改后 |
| --- | ---: | ---: |
| 预热交易日 | 0 | 3,064 |
| 输出区间 | 2025-01-02 ~ 2026-11-09 | 2025-01-02 ~ 2026-11-09（不变） |
| OOS 输出天数 | 447 | 447 |
| `unclassified` 天数 | **246** | **0** |
| bull / bear / range | 112 / 26 / 60 | 324 / 26 / 97 |

## 3. 任务2：全字段数据指纹

### 算法

- 版本号：`market-fingerprint-v2`（v1 为行数+求和，已废弃）
- 字段清单（固定顺序）：`code, trade_date, open, high, low, close, volume, amount, adjusted_close, adjustment_snapshot_id`
- 规范化：
  - `None` / `NaN` → `"null"`（统一编码）
  - 日期 → `YYYY-MM-DD`
  - 价格类 → 6 位定点小数
  - 成交量 → 3 位定点小数
- 排序：按 `(code, trade_date)` 稳定排序，行顺序变化不影响结果
- 摘要：每行序列化为 `字段1|字段2|...`，逐行更新 SHA256，末尾 `\n` 分隔
- 纳入 `input_hash`：`payload["fingerprint_version"]` 显式参与哈希

### 整改后实测

```
algorithm: market-fingerprint-v2
rows: 116,609
sha256: 394024221c09d310f520e3e39cdd83faca944b7f5f89e3eec0a2c0835b92084a
耗时: 2.6s
```

## 4. 任务3：数据压力测试

### sparse_data

- 用 SQLite `backup()` 生成独立副本到 `tempfile.mkdtemp()`，**源库零写入**
- 删除规则（确定性，不用随机数）：
  - 每 5 个交易日删除 1 天全池行情（零散缺失）
  - 前 2 只 ETF 在区间中部连续缺失 20 天（模拟停牌）
  - 跳过区间首尾各 3 个交易日，避免把起始估值日整段删空（那不是「稀疏」）
- 实测：删除零散 4,047 行 + 连续缺失 32 行，副本剩余 112,438 行
- 判定：`daily_rows=447`、`valid_return_days=270`、`gap_days_excluded=176`、`nan_days=1` → `success`

### insufficient

- 人为截取 OOS 起点后约 40 个交易日（远低于 `min_validation_days=120`）
- 引擎内部仍会算出 Sharpe 4.0184 / CAGR 78.44%，**这些指标被隐藏**，`metrics = {}`
- 判定：`status=insufficient`、`trading_days=41`、`min_required=120`，原因明确写出

### 数据隔离验证

每个数据场景执行前后各算一次全字段指纹（v2），不一致立即抛 `StressError`。
实测两次指纹一致：`394024221c09d310...`，`rows=116,609`。

## 5. 任务4：缺失日收益处理检查

### 检查结果

`regime_stats()` 原实现：

```python
for day, value in daily_returns.items():
    if value is None or pd.isna(value):
        continue
```

**没有 dropna 压缩序列**（输入已是按日收益 dict/Series），但存在三个缺陷：

1. 未记录各环境的**区间交易日数**与**缺失日数**，无法判断样本完整性；
2. 输入若被调用方提前 dropna，函数无法察觉；
3. 无「Engine 算出的缺口日」与「自然缺失」的区分。

### 整改

- 输入改为**保留 NaN 的原始交易日序列**（`pd.Series`，index 为 OOS 全部交易日）
- `regime_stats()` 同时接受 Series 与 dict，统一统计：
  - `total_days`：该环境下的交易日总数
  - `valid_days`：有有效单日收益的天数
  - `missing_days`：缺失日数
  - `samples` 与 `valid_days` 保持一致
- 有效日收益不足 `min_samples` 时返回 `insufficient_sample` 并写明原因，不硬算指标
- 累计收益只按有效日复利，报告注明「不代表连续交易日收益」
- 无分类日进入 `unclassified`，不并入 bull/bear/range

`runner.py` 侧：

```python
return_series = pd.Series([...], index=DatetimeIndex(OOS 全部交易日))
# 持仓缺价日置 NaN，不做 dropna
stats = regime_stats(return_series, label_map)
```

## 6. 修改文件清单

| 文件 | 修改内容 |
| --- | --- |
| `app/validation/fingerprint.py` | **新增**：v2 全字段指纹算法 |
| `app/validation/regime.py` | 增加 `output_start` 预热输出控制、`warmup_days`、`first_day/last_day`；重写 `regime_stats()` 记录缺失日 |
| `app/validation/stress.py` | 新增 `build_sparse_copy()`、`evaluate_sparse_result()`、`evaluate_insufficient_result()` |
| `app/validation/runner.py` | 环境预热加载、全字段指纹、数据类压力场景真实执行、结论判定排除预期不足 |
| `app/validation/config.py` | 新增 `regime_ma_window`、`min_validation_days` |
| `app/validation/report.py` | 报告增加预热、输出区间、OOS 日收益诊断、数据类场景章节 |
| `tests/test_validation_fix.py` | **新增** 40 项专项测试 |

## 7. 不修改的部分

- `app/backtest/`（engine/broker/portfolio/metrics/costs/execution/data/storage）一行未动
- `app/quant/*`、`app/data/*` 未动
- 行情、指标、复权快照、历史回测表一行未动
- 历史 validation 记录（`c99a2a75b7e646c5` 等 7 条）全部保留

## 8. 数据迁移

**无需迁移**。本阶段不新增表、不改表结构，只复用阶段3A.2 的四张 `validation_*` 表。
新验证生成新 `validation_id`，旧记录不覆盖。
