# 阶段3B-5.2 用户自选基金代码查询与研究报告工作流 V1.0

- 基线 HEAD：`6db751fb12e463f8ec689d8e9956d5aa1daf8e09`
- 执行日期：2026-11-23
- 新增模块：`app/fund/research/lookup.py`
- 扩展模块：`app/fund/research/engine.py` / `__main__.py`
- 专项测试：`tests/test_3b5_2_code_lookup.py`

> **本阶段只扩展「按代码直接查库」能力，不重新设计已完成模块。**
> 只读、不联网采集、不写库、不排名、不出信号。

---

## 0. 结论先行

| 项 | 结果 |
| --- | --- |
| `--code` 可查默认研究池外基金 | **是**（直接查 `fund_master`/`fund_share_classes`） |
| 本体代码定位全部份额 | **是** |
| 份额代码定位正确本体 | **是** |
| 批量查询单只失败不中断 | **是** |
| 12 份额 / 9 本体回归 | **不变** |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

---

## 1. 新增能力

### 1.1 按代码直接查询（`lookup.py`）

**不先调 `load_universe()` 再过滤**——直接按代码索引查 `fund_master` /
`fund_share_classes`，因此可以查到默认研究池之外、但已经入库的基金。

| 查询状态 | 含义 |
| --- | --- |
| `found` | 命中且属于场外研究池 |
| `not_found` | 数据库中不存在该代码 |
| `invalid_code` | 代码格式非法（非 6 位数字） |
| `excluded_product` | 场内 ETF / QDII 等明确排除 |
| `terminated` | 库内标记为已终止（清盘事件） |
| `no_nav_data` | 基金信息存在但无净值/货币收益记录 |

全部状态都不把「没数据」伪装成「净值为 0」。

### 1.2 代码格式校验

```python
_CODE_RE = re.compile(r"^[0-9]{6}$")
```

非法字符串（含 SQL 注入片段）在进 SQL 前就被拒绝，只返回 `invalid_code`。

### 1.3 CLI 扩展

```bash
# 保留原有
python -m app.fund.research --list
python -m app.fund.research --code 110022
python -m app.fund.research --all
python -m app.fund.research --all --json out.json

# 新增批量
python -m app.fund.research --codes-file my_funds.txt --json my_report.json
```

`--code` 改为直接查库：输入份额代码返回该份额 + 本体全部份额；
输入本体代码返回本体全部份额。

`--codes-file` 一行一个代码，支持 `#` 注释与空行；
非法行跳过并记录；重复代码去重；**单只失败不中断其他基金**。

---

## 2. 数据覆盖审计

每个份额在计算指标前输出 `coverage` 摘要：

| 字段 | 说明 |
| --- | --- |
| `share_code` / `share_name` | 份额标识 |
| `is_primary` | 是否主份额 |
| `nav_rows` | 净值记录数 |
| `nav_date_min` / `nav_date_max` | 净值起止 |
| `null_unit_nav` / `null_acc_nav` | 空值数 |
| `nonpositive_unit_nav` | 非正净值数 |
| `money_yield_rows` | 货币收益记录数 |
| `fee_rules_total` | 费率规则数 |
| `fee_rules_with_effective_from` | 有历史生效日的费率数 |
| `has_historical_effective_date` | 是否可用于历史费率 |
| `alipay_purchasable` | **恒为 unknown**（无可靠数据源） |

**四种情况明确区分**：

| 情况 | 状态 |
| --- | --- |
| 数据库没有该基金 | `not_found` |
| 有基金信息但无净值 | `no_nav_data` |
| 有净值但质量有问题 | `found` + `quality_flags` 保留 |
| 数据存在但指标不可算 | `found` + 指标 `status=insufficient_data` |

---

## 3. 份额处理（沿用 3B-5.1）

| 规则 | 状态 |
| --- | --- |
| 表现以 `fund_id` 为唯一统计单位 | 保持 |
| A/C/E 不重复计数 | 保持（`fund_count=1`，`share_count=N`） |
| 费用比较保留份额维度 | 保持（`cost_comparison.share_count`） |
| 代表份额有规则与原因 | 保持（`representative_reason`） |
| 不把费率差异当收益差异 | 保持 |
| 不重复扣除已含在净值里的费率 | 保持（`deducted_in_nav=true`） |

---

## 4. 实测结果

### 4.1 CLI 实际运行

```bash
$ python -m app.fund.research --code 161725
# 基金本体 161725 招商中证白酒指数(LOF)
# 份额数：2  代表份额：161725

$ python -m app.fund.research --code 012414
# 同一本体；share_count=2，fund_count=1

$ python -m app.fund.research --code 000007
# 状态：terminated

$ python -m app.fund.research --code 999999
# 状态：not_found
```

### 4.2 批量查询实测

输入：`110022 / 161725 / 012414 / 000007 / 000198 / 999999 / abc`

| 代码 | 状态 | 份额 |
| --- | --- | ---: |
| `110022` | found | 1 |
| `161725` | found | 2 |
| `012414` | found | 2（同 161725 本体） |
| `000007` | terminated | 1 |
| `000198` | found（货币） | 1 |
| `999999` | not_found | 0 |
| `abc` | 非法行跳过 | — |

**6 只全部逐条报告，未因 `999999` 中断。**

### 4.3 12 份额 / 9 本体回归

| 项 | 结果 |
| --- | ---: |
| 份额 | 12 |
| 本体 | 9 |
| 同类成员总数 | 9 |
| 场内 ETF 混入 | 否 |

---

## 5. 测试结果

### 5.1 新增专项（真实运行）

```
$ pytest tests/test_3b5_2_code_lookup.py -q
32 passed
```

全部使用**临时 SQLite 库**（`tmp_path`），不碰正式库。

覆盖 17 项要求：

| # | 要求 | 测试 |
| ---: | --- | --- |
| 1 | 已入库份额代码 | `test_lookup_share_code` |
| 2 | 已入库本体代码 | `test_lookup_fund_code` |
| 3 | A/C 归属同一本体 | `test_share_codes_same_fund_id` |
| 4 | 多份额不重复计数 | `test_multi_share_not_double_counted` |
| 5 | 不存在代码 | `test_not_found` |
| 6 | 场内 ETF 排除 | `test_onshore_etf_excluded` |
| 7 | QDII 排除 | `test_qdii_excluded` |
| 8 | 已终止基金 | `test_terminated` |
| 9 | 无净值 | `test_no_nav_data` |
| 10 | 质量缺口保留 | `test_nav_quality_gap_preserved` |
| 11 | 货币独立口径 | `test_money_fund_independent` |
| 12 | 批量单只失败不中断 | `test_batch_one_failure_does_not_break_others` |
| 13 | 空文件/重复/非法 | `test_codes_file_parsing` 等 |
| 14 | JSON 可解析 | `test_json_serializable` |
| 15 | 只读保护 | `test_lookup_is_readonly` |
| 16 | 费用保留全份额 | `test_cost_comparison_all_shares` |
| 17 | 支付宝不推断 | `test_alipay_never_inferred` |

### 5.2 3B-5.1 专项回归（真实运行）

```
$ pytest tests/test_3b5_1_fund_research.py -q
103 passed
```

### 5.3 全量（真实运行）

```
$ pytest -q
1418 passed, 1 warning in 341.79s (0:05:41)
```

---

## 6. 已知限制

| # | 限制 |
| ---: | --- |
| 1 | 只能查**已入库**基金；未入库返回 `not_found`，不自动补录 |
| 2 | 库内 `tracking_index` 全为 NULL，指数分组走 benchmark 回落 |
| 3 | 支付宝可购买状态恒 `unknown` |
| 4 | 79 条费率无生效日，历史成本模拟不可算 |
| 5 | 无基准收益序列与无风险利率，超额收益 / 常规 Sharpe 不可算 |
| 6 | 净值连续性 `cannot_verify` |
| 7 | 41 条清盘事件非完整名录 |

---

## 7. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

查询能力增强**不改变**回测与排名的阻塞状态。
