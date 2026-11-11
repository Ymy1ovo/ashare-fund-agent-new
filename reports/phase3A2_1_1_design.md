# 阶段3A.2.1.1 设计说明：全池压力测试阻塞问题修复

- 编写时间：2026-11-11
- 基线提交：`0cdb80af75633146a23ad36dfbdab7df79db36db`
- 范围：只修复必要缺陷，不进入 3A.3 / 3B，不开发新策略

## 1. 问题复现与根因追踪

### 1.1 复现

```
全池 41 只 ETF + sparse_data 副本 + MA250
→ 2026-11-03 卖出 512010 仅 1 股
→ 成交额 0.3738 元 < 最低佣金 5.00 元
→ 现金 3.99 → -1.01
→ PortfolioError: 现金为负
```

复现脚本 `trace_512010.py` 确认了 512010 的完整交易链路。

### 1.2 逐条回答七个问题

**Q1：为什么会产生剩余 1 股？**

碎股来自**卖单申报数量的取整方式**，不是券商规则问题。

`app/backtest/engine.py` 原代码：

```python
quantity = min(round_lot(raw_quantity, rule.lot_size, allow_odd=True), available)
```

`allow_odd=True` 让卖单按 `floor()` 取任意整数。
实测：持仓 130,400 股，策略按权重算出 `raw_quantity = 130,399.7`，
`round_lot(..., allow_odd=True)` 得到 **130,399**，卖出后剩 **1 股**。

6 笔非整手卖单全部由此产生：

| 日期 | 持仓 | 策略算出 | 实际申报 | 剩余 |
| --- | ---: | ---: | ---: | ---: |
| 2026-08-25 | 130,400 | 130,399.7 | 130,399 | 1 |
| 2026-10-13 | 362,601 | 73,101.2 | 73,101 | 1（另有 289,500 持仓） |
| 2026-10-20 | 175,800 | 175,799.9 | 175,799 | 1 |
| 2026-10-28 | 177,601 | 1.4 | 1 | 1 |
| 2026-10-29 | 177,600 | 177,599.4 | 177,599 | 1 |
| 2026-11-03 | 176,401 | 1.2 | 1 | 176,400 |

**Q2：1 股是否属于 ETF 交易制度允许的卖出数量？**

属于。ETF 卖出规则：

- 申报单位通常为 100 份或其整数倍；
- **持仓不足 100 份时，允许一次性全部卖出**（零股处理）。

所以「卖 1 股」本身合法，但**只有在持仓本来就不足一手时才该发生**。
本次是 176,401 股持仓里只申报卖 1 股，属于错误的申报数量。

**Q3：最低佣金是否重复计算？**

不是。`costs.commission()` 是 `max(gross × rate, min_commission)`，
按**每笔实际成交**收取一次。多笔订单各收一次是正确行为。
问题不在佣金模型，在于产生了「成交额 0.37 元却收 5 元」的病态订单。

**Q4：费用与实际成交数量是否匹配？**

匹配。`gross = quantity × price`，`fee = commission(gross)`，
`quantity` 就是实际成交数量。没有算错。

**Q5：部分成交后剩余数量处理是否有误？**

无误。阶段3A.1.1 已修复，`remaining_quantity = quantity - filled_quantity`，
实测账本一致。问题不在此。

**Q6：先扣费用再检查现金，卖出收入处理是否正确？**

`portfolio.apply_sell()` 是 `cash += gross - fee`，算术正确。
问题在于该表达式结果为负时没有防护，直接让账本抛异常中断整个回测。

**Q7：模拟的交易规则是否与券商一致？**

不一致。券商不会出现「17 万股持仓申报卖 1 股」这种委托，
因为卖出申报本身就按整手来。原实现的 `allow_odd=True` 是错误放宽。

## 2. 修复方案

### 2.1 新增 `sell_quantity()`（`app/backtest/costs.py`）

```python
def sell_quantity(raw_quantity, available, lot_size):
    want = floor(min(raw_quantity, available))
    lots = (want // lot_size) * lot_size
    if lots > 0:
        return lots          # 整手申报，不留碎股
    return min(want, available)   # 可卖不足一手 → 整笔清掉零股
```

规则含义：

- 可卖数量 ≥ 一手 → 按整手申报；
- 可卖数量 < 一手（真正的零股持仓）→ 允许一次性全卖；
- 严格不超过 `available`。

### 2.2 engine 与 broker 统一调用

- `engine._orders_from_weights()`：卖单数量改用 `sell_quantity()`
- `broker.execute()`：撮合时也改用 `sell_quantity()`

两处一致，避免「下单整手、撮合又变碎股」。

### 2.3 卖出净收入不足以覆盖费用的防护

在 `broker.execute()` 完成成交前检查：

```python
if order.side == 'sell':
    net_proceeds = gross - fee
    if net_proceeds < 0 and portfolio.cash + net_proceeds < -1e-6:
        return self._terminate(order, 'sell_proceeds_below_fee', 'rejected')
```

含义：

- 卖出收入足够或现金能补差 → 正常成交；
- 收入不够且现金也不够 → 拒单，记录 `sell_proceeds_below_fee`，
  **不制造负现金、不伪造成功**。

这是防御性兜底：修复申报数量后理论上不会再触发，但保留以防未来新增标的/规则。

### 2.4 明确不做的处理

- 不删除现金非负检查
- 不把最低佣金改成 0
- 不修改历史行情
- 不把 1 股改成 100 股
- 不隐藏账本异常

## 3. 任务2：全池 sparse_data

保持原有副本构造逻辑不变（SQLite backup + 确定性删除），
修复申报数量后重跑：

- 代表性池 6 只
- 全池 41 只
- 连续缺失（2 只 ETF 中部 20 天）
- 零散缺失（每 5 交易日删 1 天全池）
- 持仓期间缺失
- 缺失后恢复

副本首尾各 3 个交易日受保护，避免起始估值日被删空（那是「区间缺失」不是「稀疏」）。

## 4. 任务3：指纹 v3

### 字段扩展

数据库实测字段（`PRAGMA table_info(etf_daily_prices)`）：

```
code, trade_date, open, high, low, close, volume, amount,
source, collected_at, adjusted_close, adjustment_type,
quality_status, quality_notes, adjustment_snapshot_id,
adjustment_collected_at, adjustment_source,
adjustment_coverage_start, adjustment_coverage_end
```

v3 追加参与价格转换/复权的字段：

```
adjustment_type            （qfq / hfq，实测全库 116,609 行均为 qfq）
adjustment_coverage_start
adjustment_coverage_end
```

`quality_status`、`source` 等元信息不参与，因为它们不影响价格数值。

### 版本与兼容

```python
FINGERPRINT_VERSION = "market-fingerprint-v3"
LEGACY_FINGERPRINT_VERSIONS = ("market-fingerprint-v2",)
```

哈希输入前缀为版本号，因此 v2 与 v3 结果必然不同，不会误读。
`_input_hash()` 已包含 `fingerprint_version` 字段。

### 空值编码统一

v3 修正：`adjustment_coverage_start/end` 的空字符串与 `None` 统一编码为 `null`。

## 5. 任务4：MA250 预热有效数据计数

### 原实现问题

```python
values = [float(row[1]) if row[1] is not None else nan for row in rows]
return {"days": len(rows), ...}
```

`days` 用**数据库记录数**，若存在空价格会被算作有效。

### 整改

```python
for trade_date, adjusted_close, close in rows:
    price = adjusted_close if adjusted_close is not None else close
    number = float(price)
    if number != number or number <= 0:   # NaN 或非正价格
        invalid += 1
        continue
    index.append(...)
    values.append(number)
```

返回三个独立计数：

| 字段 | 含义 |
| --- | --- |
| `db_rows` | 数据库记录数 |
| `valid_prices` | 有效价格观测数（非 NaN、非正价格） |
| `invalid_prices` | 无效价格数 |
| `days` | 与 `valid_prices` 一致 |

预热状态判定：

- `valid_prices >= 250` → `ok`
- `0 < valid_prices < 250` → `partial`
- `valid_prices == 0` → `unavailable`

不向前填充、不读取 OOS 之后的数据（SQL 条件 `trade_date < oos_start`）。

## 6. 修改文件清单

| 文件 | 修改内容 |
| --- | --- |
| `app/backtest/costs.py` | **新增** `sell_quantity()` |
| `app/backtest/engine.py` | 卖单数量改用 `sell_quantity()` |
| `app/backtest/broker.py` | 撮合数量改用 `sell_quantity()`；新增卖出净收入不足防护 |
| `app/validation/fingerprint.py` | 升级 v3，追加 3 个复权字段，修正空值编码 |
| `app/validation/runner.py` | `_load_regime_warmup()` 按有效价格计数；预热状态改用 valid_prices |
| `app/validation/report.py` | 报告展示有效价格 / 记录数 / 无效价格 |
| `tests/test_validation_fix_2.py` | **新增** 27 项专项测试 |
| `tests/test_validation_fix.py` | 适配 v3 字段与版本断言 |

## 7. 不修改的部分

- `portfolio.py` 账本逻辑未动（`apply_sell` 算术本身正确）
- `metrics.py`、`quant/*`、`data/*` 未动
- 行情、指标、复权快照、历史回测表一行未动
- 历史 validation 记录全部保留
- 数据库结构无变更，无需迁移

## 8. 交易规则声明与限制

本项目采用的 ETF 模拟规则：

| 项目 | 规则 | 状态 |
| --- | --- | --- |
| 买入申报 | 整手（默认 100 份）整数倍 | 已实现 |
| 卖出申报 | 整手；不足一手时整笔卖出 | 本阶段修复 |
| 最低佣金 | 每笔成交收取 `max(金额×费率, 5 元)` | 已实现 |
| 卖出净收入为负 | 现金可补则成交，否则拒单 | 本阶段新增防护 |
| T+N 可卖 | 按 ETF 类别配置 | 已实现 |
| 涨跌停 | 整日近似 | 已知限制 |
| 印花税/过户费 | 默认 0，可配置 | 已实现 |

**未模拟**的真实券商细节：

- 交易所对零股卖出的精确申报校验（本模型只允许「整个持仓不足一手」时卖零股）
- 券商的「卖出所得当日可用」与「T+1 提现」差异
- 分笔成交的逐笔佣金（本模型按单笔订单一次收费）

这些限制已在报告中如实标注，不假装模拟了真实券商。
