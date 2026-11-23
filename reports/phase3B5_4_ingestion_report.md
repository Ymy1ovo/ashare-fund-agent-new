# 阶段3B-5.4 真实接入报告

- 基线 HEAD：`a94325080a449a4a84e40b8a1bc4bbabcb0bab03`
- 执行日期：2026-11-23
- 写入入口：`python -m app.fund.ingest_user_funds`（唯一写入口，未改）

> **本报告全部为真实接入**。数据来自 AKShare 已审计接口，
> 不是模拟、不是桩、不是构造数据。

---

## 1. 执行顺序（临时库先行）

| 步骤 | 库 | 结果 |
| --- | --- | --- |
| ① 临时库全量接入 | `%TEMP%/tmp54.db` | 9 份额 / 7 本体 全部 `ingested` |
| ② 临时库幂等复跑 | 同上 | 9 份额全部 `already_present` |
| ③ 临时库研究验证 | 同上 | 7 只分析全部 `found` |
| ④ 正式库受控接入 | `data/fund_agent.db` | 9 份额 / 7 本体 全部 `ingested` |

临时库验证通过后才写正式库，未跳过任何一步。

---

## 2. 正式库接入明细

| # | 代码 | 名称 | 类型字段 | 分类 | 净值行 | 起 | 止 | 数据形态 |
| ---: | --- | --- | --- | --- | ---: | --- | --- | --- |
| 1 | `050002` | 博时裕富沪深300指数A | 股票型-标准指数 | `ordinary_index` | 5644 | 2003-08-26 | 2026-11-20 | `net_value` |
| 2 | `001052` | 华夏中证500ETF联接 | 股票型-标准指数 | `etf_linked` | 2802 | 2015-05-05 | 2026-11-20 | `net_value` |
| 3 | `001938` | 中欧时代先锋 | 股票型-普通 | `active_equity` | 2678 | 2015-11-03 | 2026-11-20 | `net_value` |
| 4 | `519066` | 汇添富蓝筹稳健混合 | 混合型-灵活配置 | `active_equity` | 4461 | 2008-07-08 | 2026-11-20 | `net_value` |
| 5 | `000032` | 易方达信用债A | 债券型-长期纯债 | `bond_pure` | 3288 | 2013-04-24 | 2026-11-20 | `net_value` |
| 6 | `000033` | 易方达信用债C | 债券型-长期纯债 | `bond_pure` | 3288 | 2013-04-24 | 2026-11-20 | `net_value` |
| 7 | `000509` | 广发钱袋子货币 | 货币型 | `money_market` | 4676 | 2014-01-15 | 2026-11-22 | `money_yield` |
| 8 | `001548` | 天弘上证50ETF联接A | 股票型-标准指数 | `etf_linked` | 2764 | 2015-07-16 | 2026-11-20 | `net_value` |
| 9 | `001549` | 天弘上证50ETF联接C | 股票型-标准指数 | `etf_linked` | 2764 | 2015-07-16 | 2026-11-20 | `net_value` |

---

## 3. 六种产品类型覆盖

| 目标类型 | 实测样本 | 分类 | 净值行 | 覆盖 |
| --- | --- | --- | ---: | --- |
| 普通指数基金 | `050002` 博时裕富沪深300指数A | `ordinary_index` | 5644 | ✅ |
| ETF 联接基金 | `001052` 华夏中证500ETF联接 | `etf_linked` | 2802 | ✅ |
| ETF 联接基金 | `001548`/`001549` 天弘上证50ETF联接 A/C | `etf_linked` | 2764 | ✅ |
| 主动权益基金 | `001938` 中欧时代先锋 | `active_equity` | 2678 | ✅ |
| 混合型基金 | `519066` 汇添富蓝筹稳健混合 | `active_equity` | 4461 | ✅ |
| 债券基金 | `000032`/`000033` 易方达信用债 A/C | `bond_pure` | 3288 | ✅ |
| 货币基金 | `000509` 广发钱袋子货币 | `money_market` | 4676 | ✅ |

**六类全部有真实成功接入样本**，无一类靠模拟数据。

> 「混合型」在 3B-5.0 九类体系中归入 `active_equity`（不单独设类），
> 类型差异保留在 `fund_type_l1`：`股票型-普通` vs `混合型-灵活配置`。

---

## 4. A/C 份额归组

| 组 | A | C | 公司 | fund_id | 归组 |
| --- | --- | --- | --- | ---: | --- |
| 1 | `000032` | `000033` | 易方达基金管理有限公司 | **73** | ✅ 同一本体 |
| 2 | `001548` | `001549` | 天弘基金管理有限公司 | **75** | ✅ 同一本体 |

**2 组真实 A/C 配对全部正确归组**；C 类 `is_primary=0`，A 类 `is_primary=1`。

---

## 5. 幂等验证

正式库接入后立即重复接入同一批 9 个代码：

| 代码 | 首次 | 复跑 |
| --- | --- | --- |
| `050002` | `ingested` | `already_present` |
| `001052` | `ingested` | `already_present` |
| `001938` | `ingested` | `already_present` |
| `519066` | `ingested` | `already_present` |
| `000032` | `ingested` | `already_present` |
| `000033` | `ingested` | `already_present` |
| `000509` | `ingested` | `already_present` |
| `001548` | `ingested` | `already_present` |
| `001549` | `ingested` | `already_present` |

临时库幂等复跑同为 9/9 `already_present`，指纹未变。

---

## 6. 数据库变更

**接入前先备份**：`data/backups/fund_agent_before_3b5_4_before_20261123_132335.db`

### 6.1 行数变化

| 表 | 接入前 | 接入后 | 增量 |
| --- | ---: | ---: | ---: |
| `fund_master`（基金本体） | 53 | 60 | +7 |
| `fund_share_classes`（份额） | 80 | 89 | +9 |
| `fund_nav_daily`（净值） | 47718 | 80083 | +32365 |
| `fund_dividends`（分红） | 44 | 105 | +61 |
| `fund_manager_history`（经理历史） | 21 | 21 | 0 |
| `fund_aum_history`（规模历史） | 683 | 683 | 0 |
| `fund_fee_rules`（费率） | 90 | 90 | 0 |
| `fund_subscription_status`（申赎状态） | 12 | 12 | 0 |
| `fund_lifecycle_events`（生命周期事件） | 49 | 49 | 0 |
| `fund_data_quality`（数据质量） | 31 | 32 | +1 |

### 6.2 关键不变项

| 项 | 接入前 | 接入后 |
| --- | ---: | ---: |
| 清盘本体（terminated） | 41 | **41** |
| 生命周期事件 | 49 | **49** |
| 费率规则 | 90 | **90** |
| 经理历史 | 21 | **21** |
| 规模历史 | 683 | **683** |

### 6.3 完整性

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| `PRAGMA foreign_key_check` | **0 违规** |
| ETF 行情指纹 | `d54727c0…`（不变） |

### 6.4 内容指纹

| 时点 | SHA256 |
| --- | --- |
| 接入前 | `f71c36f9f1a5d73f9f0b1f930b6c2dfaff58cb08f985d0828feb2e4288cd635b` |
| 接入后 | `11c56eba1489976fa35be92586a99bc21a27e20c06e95cacab5c8ca553c05116` |
| 备份库（独立文件） | `f71c36f9f1a5d73f9f0b1f930b6c2dfaff58cb08f985d0828feb2e4288cd635b` |

接入前后**必然不同**（新增 9 份额 / 32,365 行净值）；
备份库指纹与接入前**完全一致**，证明备份可用、回滚可行。

### 6.5 回滚方案

```bash
# 1) 停服，确保无写入
# 2) 直接用备份覆盖
copy data\backups\fund_agent_before_3b5_4_before_20261123_132335.db data\fund_agent.db
# 3) 校验
python -c "import sqlite3; c=sqlite3.connect('data/fund_agent.db'); print(c.execute('PRAGMA integrity_check').fetchone())"
```

备份库完整性已验证为 `ok`，可直接回滚。

---

## 7. 数据证据边界

| 字段 | 状态 | 原因 |
| --- | --- | --- |
| 支付宝可购买状态 | **unknown** | 无支付宝数据源，不推断 |
| 支付宝实际申购费率 | **not_obtainable** | 不接入、不推断 |
| 赎回费阶梯 | **not_obtainable** | 无基金合同原文核实 |
| 历史时点规模 | **not_obtainable** | 只有平台观测快照 |
| 历史时点基金经理 | **not_obtainable** | 只有当前快照 |
| 历史清盘完整名单 | **cannot_verify** | 无全量公告源 |
| 净值公布日历 | **cannot_verify** | 不可得，不用 A 股日历代理 |

以上字段在库内均保持 NULL / unknown，**未填任何推测值**。

---

## 8. 数据质量问题（如实记录，不掩盖）

| # | 基金 | 问题 | 处理 |
| ---: | --- | --- | --- |
| 1 | `050002` | 2003-08-26→2003-09-26 有 31 天缺口 | 年化收益**拒绝计算**；波动率不年化 |
| 2 | 全部 | 库内 `tracking_index` 全 NULL | 指数分组走 benchmark 回落，标注 `grouping_source=benchmark` |
| 3 | 部分 | 分红接口偶发返回空 | 不写虚假分红，`fund_dividends` 保持真实值 |
| 4 | 全部 | 无净值公布日历 | 连续性恒 `cannot_verify` |
| 5 | `000509` | 货币基金无净值 | 使用 `per_10k_yield` / `seven_day_annual`，与净值型隔离 |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
