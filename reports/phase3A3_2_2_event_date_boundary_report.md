# 阶段3A.3.2.2 事件日期边界与统计口径复检

- 生成时间：2026-11-13
- 文件：`app/backtest/corporate_actions.py::load_actions()`
- 关联：`reports/phase3A3_2_1_event_reconciliation.md`（上一阶段的统计疑点）

## 1. 上一阶段的边界缺陷

```python
if start:
    sql += " AND effective_date >= ?"      # ← 统一按生效日
if end:
    sql += " AND effective_date <= ?"
```

但引擎实际应用日期是**按类型不同**的：

| 事件类型 | 引擎实际应用日期 |
| --- | --- |
| 现金分红 | `ex_date`（除息日确认应收） |
| 拆分 / 合并 | `effective_date`（生效交易日调份额） |

### 1.1 会漏掉什么

若某分红 `ex_date` = 回测最后一天、`effective_date` = 下一交易日：

- 引擎应在最后一天确认应收（计入期末净资产）
- 但 `load_actions(end=最后一天)` 按 `effective_date` 筛，**提前把它排除**
- 结果：回测结束日的应收凭空消失，期末净资产偏低

### 1.2 实测本库是否有这种事件

查询 `ex_date <= 2026-11-09 AND effective_date > 2026-11-09` 的分红：

```
（无记录）
```

查询 `effective_date <= 2026-11-09 AND ex_date > 2026-11-09` 的拆分：

```
（无记录）
```

**本库当前数据没有踩到这个边界**，
所以 3A.3.2.1 的结果没有因此出错。
但缺陷真实存在，只是当前数据没触发——这是**潜在缺陷已修复**，不是「没影响所以不用改」。

## 2. 修复

```python
if start:
    sql += (" AND ("
            "(action_type = 'cash_distribution' AND ex_date >= ?) OR "
            "(action_type != 'cash_distribution' AND effective_date >= ?))")
if end:
    sql += (" AND ("
            "(action_type = 'cash_distribution' AND ex_date <= ?) OR "
            "(action_type != 'cash_distribution' AND effective_date <= ?))")
```

排序改为 `ORDER BY ex_date, effective_date, code, action_id`，
因为分红可能生效日晚于拆分但除息日更早，必须按除息日顺序读到。

新增 `window_date(action)` 函数，返回该事件在区间判定中使用的日期，
供报告与对账脚本统一调用，避免各写一套逻辑。

### 2.1 三者一致性

| 环节 | 口径 | 验证 |
| --- | --- | --- |
| 数据加载 `load_actions()` | 分红 `ex_date` / 拆分 `effective_date` | 数据库 49 / 31 条，加载 49 / 31 条，**完全一致** |
| 事件指纹 `compute_events_digest()` | 覆盖加载到的事件集 | 样本内 49 条、样本外 31 条 |
| 实际应用事件集合 | 引擎 `action_index` / `record_index` | 应用 79 条（去重） |

三者使用同一份 `load_actions()` 结果，不存在口径分叉。

## 3. 边界测试（8 个场景全覆盖）

| # | 场景 | 测试 | 结果 |
| ---: | --- | --- | :---: |
| 1 | `ex_date == start_date` | `test_window_boundary_ex_date_equals_start` | ✅ |
| 2 | `ex_date == end_date` | `test_window_boundary_ex_date_equals_end_effective_after` | ✅ |
| 3 | `ex_date == end_date` 且 `pay_date` 在结束日之后 | 同上 | ✅ |
| 4 | `effective_date > end_date` 但 `ex_date == end_date` | 同上 | ✅ |
| 5 | 拆分 `effective_date == end_date` | `test_window_boundary_split_effective_equals_end` | ✅ |
| 6 | 拆分 `effective_date > end_date` | `test_window_boundary_split_effective_after_end_excluded` | ✅ |
| 7 | 开始日期前已发生的事件 | `test_window_excludes_events_before_start` | ✅ |
| 8 | 同一事件跨两次相邻区间不重复进入单次回测 | `test_same_event_not_loaded_twice_across_adjacent_ranges` | ✅ |

### 3.1 期末未到账分红计入净资产

`test_end_of_backtest_unsettled_dividend_counted_in_assets`：

```
pay_date = 2099-01-01（远在结束日之后）
→ final.dividend_receivable > 0
→ final.total_assets == cash + market_value + dividend_receivable
```

## 4. 登记日早于回测开始日的处理

| 场景 | 处理 | 依据 |
| --- | --- | --- |
| 回测初始持仓为空 | **不产生分红** | 引擎只在 `record_date` 收盘捕获份额，初始无持仓则为 0 |
| 未来支持非空初始持仓 | 必须有登记日权益证据 | 当前未实现，已记入局限 |

当前所有回测初始现金 100 万、持仓为空，
因此不存在「登记日在区间外但应得分红」的情况。

## 5. 80 与 81 的差异——真实原因

上一阶段报告写「区间内 81 条」，但存在一处口径说明缺失。复检结果：

| 统计范围 | 区间内事件数 |
| --- | ---: |
| 全库（46 只 ETF 有事件） | **81** |
| 41 只回测池 | **80** |

**差值是 `588200`（2026-07-20 拆分，比例 3.0）**：

```
588200 在 etf_pool（46 只）里，但不在 validation 的 41 只回测池里
```

### 5.1 上一阶段报告的问题

报告写「区间内 81 条 100% official」，但没有说明：
- 81 是**全 46 只池**的数字
- **41 只回测池实际只用 80 条**

属于**口径标注缺失**，不是数值错误。
本阶段更正为：报告必须同时给两个数字并注明统计范围。

### 5.2 关于 2018 年 `159920` 事件

上一阶段报告提到 `159920` `2018-06-22` 的分红，复检确认：

```
159920  cash_distribution  ex_date=2018-06-22  effective_date=2018-06-25
        record_date=2018-06-22  pay_date=2018-06-26  cash_per_share=0.076
```

**该事件完整在 2021—2026 回测区间之外**，与 80/81 的差异**毫无关系**。
上一阶段把它写进区间差异解释段落属于**归因错误**。

真实原因是 `588200`（2026 年，区间内），不是 `159920`（2018 年，区间外）。

## 6. 两种统计口径并列

### 6.1 经济权益日期统计（正式口径）

现金分红按 `ex_date`、份额调整按 `effective_date`：

| 区间 | 全 46 只 | 41 只回测池 |
| --- | ---: | ---: |
| 样本内 2021-01-04 ~ 2024-12-31 | 49 | **49** |
| 样本外 2025-01-02 ~ 2026-11-09 | 32 | **31** |
| 区间内合计 | 81 | **80** |

**正式回测的样本内、样本外事件统计一律用此口径。**

### 6.2 原始数据字段统计

按 `ex_date` / `effective_date` 分别列出（全 46 只）：

| 区间 | 按 `ex_date` | 按 `effective_date` |
| --- | ---: | ---: |
| 样本内 | 49 | 49 |
| 样本外 | 32 | 32 |

本库两种字段统计**恰好相同**，因为所有分红的 `ex_date` 与 `effective_date`
都在同一区间内（没有跨年边界事件）。

### 6.3 按类型

| 类型 | 全库 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `split` | 23 | 14 | 6 | 3 |
| `reverse_split` | 22 | 1 | 3 | 18 |
| `cash_distribution` | 121 | 34 | 23 | 64 |
| **合计** | **166** | **49** | **32** | **85** |

## 7. 32 与 31 的差异

样本外：全 46 只 32 条，41 只池 31 条，差的同样是 `588200`。

| 口径 | 样本外 |
| --- | ---: |
| 全 46 只 | 32 |
| 41 只回测池 | 31 |
| `load_actions(oos, pool=41)` | **31** |

回测实际加载 31 条，与池内统计一致。

## 8. 166 条总事件的区间划分

```
166（全库）
├── 85（区间外）
│   ├── 样本开始前（< 2021-01-04）
│   └── 样本结束后（> 2026-11-09）
└── 81（区间内，全 46 只）
    ├── 49（样本内）
    └── 32（样本外）
```

41 只回测池视角：

```
165（池内）
└── 80（区间内）
    ├── 49（样本内）
    └── 31（样本外）
```

全部可由 SQL 复现（见第 9 节）。

## 9. 全部数字的复现命令

```bash
# 1) 全库按类型
sqlite3 data/fund_agent.db "SELECT action_type, COUNT(*) FROM corporate_actions GROUP BY action_type;"

# 2) 区间内（经济权益日，全 46 只）
sqlite3 data/fund_agent.db "
SELECT COUNT(*) FROM corporate_actions WHERE
  (action_type='cash_distribution' AND ex_date BETWEEN '2021-01-04' AND '2026-11-09') OR
  (action_type!='cash_distribution' AND effective_date BETWEEN '2021-01-04' AND '2026-11-09');"

# 3) 样本内 / 样本外（全 46 只）
#    把上面的 2021-01-04~2026-11-09 换成
#    2021-01-04~2024-12-31 / 2025-01-02~2026-11-09

# 4) 41 只池（加 code IN (...)）
#    池定义：validation_runs WHERE validation_id='32aead3291734f91' 的 etf_codes

# 5) 两种字段口径
sqlite3 data/fund_agent.db "SELECT COUNT(*) FROM corporate_actions WHERE ex_date BETWEEN '2025-01-02' AND '2026-11-09';"
sqlite3 data/fund_agent.db "SELECT COUNT(*) FROM corporate_actions WHERE effective_date BETWEEN '2025-01-02' AND '2026-11-09';"
```

或一次性执行：

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/reconcile_events.py
```

## 10. 对回测结果的影响

修复前后样本外 MA250：

| 指标 | 3A.3.2.1 | 3A.3.2.2 | 差 |
| --- | ---: | ---: | ---: |
| 事件数 | 31 | 31 | 0 |
| 总收益 | 20.1070% | 20.1186% | +0.0116 pp |

**事件数没变**，因为本库没有跨界事件。
差异来自零碎份额成本修复（+2 笔交易），不是边界修复。

## 11. 局限

| # | 局限 | 影响 |
| ---: | --- | --- |
| 1 | 本库无跨界事件，边界修复未经真实数据验证 | 只有构造测试覆盖 |
| 2 | 不支持非空初始持仓 | 登记日早于开始日的分红无法正确处理 |
| 3 | 未校验「登记日是否早于开始日」 | 若未来支持初始持仓需补校验 |
| 4 | 拆分 `ex_date` 与 `effective_date` 跨区间时按 `effective_date` | 这是正确口径，但报告需注明 |
