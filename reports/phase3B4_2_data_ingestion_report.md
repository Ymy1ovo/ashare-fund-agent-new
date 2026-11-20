# 阶段3B-4.2 场外基金关键历史数据正式入库报告

- 基线 HEAD：`e90a2b38f851c5cf79ddbd5f6dc4240bdf45c426`
- 执行日期：2026-11-20
- 执行脚本：`scripts/ingest_3b4_2.py`
- 导入模块：`app/fund/ingest_3b4_2.py`
- 迁移模块：`app/fund/migration_3b4_2.py`

---

## 0. 结论先行

| 项 | 结果 |
| --- | --- |
| 生命周期事件计划 / 实际 | 41 / **41** |
| 场内 ETF 排除 | 2（`511000`、`511050`） |
| 费率规则计划 / 实际 | 90 / **90** |
| 证据等级 | 生命周期 **B** / 费率 **C** |
| 幂等（两次导入） | ✅ 第二次插入 0 条、跳过 41 + 90 条 |
| SQLite 完整性 | **ok** |
| 外键违规 | 0 |
| 支付宝状态 | ✅ 全部 `unknown`，导入未改变 |
| ETF 侧数据 | ✅ 前后行数完全一致 |

### 0.1 本阶段核心原则执行情况

> **宁可保留 NULL 和 unknown，也不允许为了填满数据库而制造数据。**

| 检查项 | 是否守住 |
| --- | --- |
| 清盘日期缺失保持 NULL | ✅ 12 条 event_date 为 NULL
| 费率有效日期无证据保持 NULL | ✅ 全部 90 条 effective_from 为 NULL
| 缺失费率为 NULL 不用 0 | ✅ 1 条 rate_original 为 NULL
| 持有期口径未确认 | ✅ 全部 90 条 holding_days_basis 为 NULL
| 支付宝状态不推断 | ✅ 全部 unknown |
| 天天基金费率不冒充支付宝 | ✅ `platform_name` 全部 `eastmoney` |
| 场内 ETF 不混入场外 | ✅ 0 条泄漏 |
| 多份额不生成多本体 | ✅ 每事件唯一 fund_id |

---

## 1. 数据库迁移

### 1.1 迁移文件

`migrations/phase3b4_2_lifecycle_fee_ingestion.sql`（65 行）

设计原则：**只补列、只加索引**，不改已有列类型、不删数据、不重建表。

SQLite 的 `ALTER TABLE ADD COLUMN` 不支持 `IF NOT EXISTS`，
实际执行由 `app/fund/migration_3b4_2.py` 先查 `PRAGMA table_info` 再逐列补，
保证可重复执行。SQL 文件作为同一迁移的可读文档与打包产物。

### 1.2 新增列

**`fund_lifecycle_events`（+5）**：

| 列 | 类型 | 用途 |
| --- | --- | --- |
| `announcement_id` | TEXT | 公告 ID，可追溯原文 |
| `product_structure` | TEXT | 产品结构，区分场内 ETF 与场外 |
| `fund_codes` | TEXT | 份额代码清单，多份额不重复成本体 |
| `event_fingerprint` | TEXT | 跨来源稳定幂等键 |
| `fetched_at` | TEXT | 数据采集时间 |

**`fund_fee_rules`（+15）**：

| 列 | 类型 | 用途 |
| --- | --- | --- |
| `lower_inclusive` / `upper_inclusive` | INTEGER | 金额区间开闭 |
| `lower_inferred` | INTEGER | 金额下界是否推断 |
| `holding_days_min_inclusive` / `holding_days_max_inclusive` | INTEGER | 持有期区间开闭 |
| `holding_days_min_inferred` | INTEGER | 持有期下界是否推断 |
| `rate_original` | REAL | **原始费率** |
| `rate_platform` | REAL | **平台优惠费率** |
| `platform_name` | TEXT | 平台名（eastmoney / alipay / contract） |
| `is_annual` | INTEGER | 是否年化费率 |
| `holding_days_basis` | TEXT | 自然日 / 交易日（本轮全 NULL） |
| `source_name` / `source_url` / `fetched_at` | TEXT | 来源追溯 |
| `detail` | TEXT | 原文条件文本 |

### 1.3 新增索引

| 索引 | 作用 |
| --- | --- |
| `uq_fund_life_fingerprint`（UNIQUE, WHERE NOT NULL） | 事件幂等硬约束 |
| `idx_fund_life_announcement` | 按公告 ID 查 |
| `idx_fund_life_structure` | 按产品结构筛 |
| `idx_fund_fee_type` | 按份额+费率类型查 |
| `idx_fund_fee_platform` | 按平台筛 |

### 1.4 兼容性

保留全部旧列（`rate`、`evidence_level`、`effective_from` 等），旧 Repository 方法
（`add_fee_rule` / `add_lifecycle_event`）不改一行仍可用。

---

## 2. 生命周期事件入库

### 2.1 计划与实际

| 项 | 数量 |
| --- | ---: |
| 校准 JSON 中清盘事件总数 | 43 |
| 排除（场内 ETF） | 2 |
| **计划入库** | **41** |
| **实际入库** | **41** |
| 失败 | 0 |

### 2.2 场内 ETF 分离结果

| 代码 | 名称 | 结构 | 处理 |
| --- | --- | --- | --- |
| `511000` | 招商中债-0-3年长三角地方政府债交易型开放式指数证券投资基金 | `etf` | **排除** |
| `511050` | 兴业上证1-5年期地方政府债交易型开放式指数证券投资基金 | `etf` | **排除** |

泄漏检查：`fund_codes` 含 511000 或 511050 的行数 = **0**

### 2.3 场外结构分布

| 结构 | 入库数量 |
| --- | ---: |
| `etf_linked` | 3 |
| `lof` | 11 |
| `ordinary_open_ended` | 27 |
| **合计** | **41** |

与校准报告一致：普通开放式 27 + ETF 联接 3 + LOF 11 = 41。

### 2.4 证据等级

| 等级 | 数量 |
| --- | ---: |
| **B** | **41** |
| A / C / D | 0 |

保存的是本轮校准后的真实等级，不是「公告可下载就标 A」。

### 2.5 来源可追溯性

| 项 | 数量 |
| --- | ---: |
| 同时有 announcement_url + announcement_id | **41 / 41** |
| detail 含来源声明 | **41 / 41** |

每条 detail 都写有：

```
来源为东方财富转载，未经基金管理人官网或交易所官网逐条回源验证，证据等级B。
```

detail 里同时保存结构化的可追溯字段（JSON）：

```json
{"fund_entity": "...", "fund_entity_old": "...", "product_structure": "...",
 "investment_type": "...", "name_source": "...", "evidence_reason": "...",
 "alipay_purchasable": "unknown", "alipay_evidence": "not_obtainable",
 "announcement_title": "...", "doc_format": "pdf", "disclaimer": "..."}
```

### 2.6 NULL 处理

| 字段 | NULL 数量 | 原因 |
| --- | ---: | --- |
| `event_date` | **12** | 公告只写「清算报告公告日」，未写清算开始日 |
| `successor_fund_id` | 41 | 清盘无承接基金（公告未写） |

**关键验证**：这 12 条 `event_date IS NULL` 的记录，其 `announcement_date` 都有值，
且**没有一条**把公告日期复制成事件日期。

### 2.7 多份额代码 → 单一本体

| 检查 | 结果 |
| --- | --- |
| 事件数 | 41 |
| 涉及的 fund_id 数 | 41（**每个事件唯一**） |
| 含多个份额代码的事件 | ≥10（如 `000091/000092/000093`） |

实现方式：从 `fund_codes` 里挑主代码建 `fund_master`，其余代码登记为
`fund_share_classes`（`is_primary=0` 语义由 `_ensure_share` 处理），
**绝不把多个份额代码写成多个基金本体**。

---

## 3. 费率阶梯入库

### 3.1 计划与实际

| 项 | 数量 |
| --- | ---: |
| 费率样本基金数 | 12 |
| 计划行数 | 90 |
| **实际入库** | **90** |
| 失败 | 0 |

### 3.2 按费率类型

| 费率类型 | 数量 | 说明 |
| --- | ---: | --- |
| `custody` | 12 | 托管费（年化） |
| `management` | 12 | 管理费（年化） |
| `purchase` | 20 | 申购（金额阶梯） |
| `redemption` | 34 | 赎回（持有期阶梯） |
| `sales_service` | 12 | 销售服务费（年化） |
| **合计** | **90** | |

### 3.3 原始费率与平台优惠费率分列

| 项 | 数量 |
| --- | ---: |
| 有平台优惠费率的行 | **20**（全部是 purchase） |
| `platform_name` = `eastmoney` | 20 |
| `platform_name` = `alipay` | **0** |

**天天基金优惠费率绝不会写进支付宝字段**，也没有支付宝费率字段被填值。

### 3.4 区间边界表达

以 `110020` 易方达沪深300ETF联接A 的赎回费为例（原文用「小于等于」）：

| 档 | `holding_days_min` | min含 | `holding_days_max` | max含 | `holding_days_min_inferred` | `rate_original` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 1 | 6 | 1 | **1** | 1.50% |
| 1 | 7 | 1 | 364 | 1 | 0 | 0.50% |
| 2 | 365 | 1 | 729 | 1 | 0 | 0.25% |
| 3 | 730 | 1 | NULL | NULL | 0 | 0.00% |

**闭区间能被准确表达**：`max=6, max_inclusive=1` 与 `max=7, max_inclusive=0` 是两种不同含义，
3B-4.0 的单列 `holding_days_max` 无法区分，新列能。

### 3.5 推断下界标记

| 项 | 数量 |
| --- | ---: |
| `holding_days_min_inferred = 1` 或 `lower_inferred = 1` | **19** |

「小于7天」首档在原文没有显式下界，补 0 是**推断**，必须标记，
下游按区间取值时能区分「原文写的 0」与「推断的 0」。

### 3.6 NULL 与不可确认字段

| 字段 | NULL 数量 | 原因 |
| --- | ---: | --- |
| `rate_original` | **1** | `110022` 销售服务费页面是 `---`，不当 0 |
| `effective_from` | **90** | 无历史生效时间证据，抓取日期不冒充 |
| `holding_days_basis` | **90** | 自然日/交易日合同未明确 |
| `rate_platform` | 70 | 非申购费无平台优惠概念 |

### 3.7 货币基金不伪造赎回阶梯

`000198` 天弘余额宝：赎回阶梯行数 = **0**。
货币基金本来就没有按持有期分档的赎回费，页面无数据就是无数据，不补空行。

### 3.8 证据等级

| 等级 | 数量 |
| --- | ---: |
| **C**（天天基金 F10） | **90** |
| A / B / D | 0 |

---

## 4. 支付宝状态保护

### 4.1 导入前后状态

| 项 | 结果 |
| --- | --- |
| `fund_subscription_status` 分布 | `{"unknown": 12}` |
| 是否全部 unknown | **True** |

本阶段导入**没有触碰** `fund_subscription_status` 表，
也没有任何代码从 `product_structure` 推断支付宝可购买性。

### 4.2 三条禁令执行

| 禁令 | 执行 |
| --- | --- |
| 不从产品结构推断支付宝可购买 | ✅ 代码里无此逻辑 |
| 不从天天基金数据推断 | ✅ `platform_name` 固定 `eastmoney` |
| 不把 unknown 写成 no | ✅ 值始终 `unknown` |
| 不把未确认解释成实际为 0 | ✅ 无任何 `alipay_*_count` 推断字段 |

---

## 5. 幂等验证

### 5.1 两次导入对比

| 表 | 导入前 | 第1次后 | 第2次后 |
| --- | ---: | ---: | ---: |
| `fund_lifecycle_events` | 8 | 49 | 49 |
| `fund_fee_rules` | 0 | 90 | 90 |
| `fund_master` | 9 | 50 | 50 |
| `fund_share_classes` | 12 | 75 | 75 |
| `fund_nav_daily` | 39822 | 39822 | 39822 |
| `fund_dividends` | 44 | 44 | 44 |

### 5.2 第二次导入的写入统计

| 项 | 生命周期 | 费率 |
| --- | ---: | ---: |
| 新增 | **0** | **0** |
| 跳过（已存在） | 41 | 90 |
| 失败 | 0 | 0 |

### 5.3 幂等键设计

| 表 | 幂等键 | 层级 |
| --- | --- | --- |
| `fund_lifecycle_events` | `event_fingerprint` = `life:{announcement_id}:{fund_code}` | 应用层查 + UNIQUE 索引兜底 |
| `fund_fee_rules` | `(share_class_id, fee_type, tier_order, effective_from)` | 应用层查 + UNIQUE 索引兜底 |

测试 `test_unique_constraint_works` 直接验证 DB 层 UNIQUE 索引会拒绝重复。

---

## 6. 数据库完整性

| 检查 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| `PRAGMA foreign_key_check` 违规数 | **0** |

### 6.1 ETF 侧未受影响

| 表 | 导入前 | 导入后 | 变化 |
| --- | ---: | ---: | ---: |
| `etf_pool` | 46 | 46 | 0 |
| `etf_daily_prices` | 116609 | 116609 | 0 |
| `etf_indicator_daily` | 350292 | 350292 | 0 |
| `backtest_runs` | 507 | 507 | 0 |
| `backtest_orders` | 29255 | 29255 | 0 |
| `backtest_trades` | 26100 | 26100 | 0 |
| `validation_runs` | 64 | 64 | 0 |
| `validation_grid` | 440 | 440 | 0 |

全部 **0 变化**。

### 6.2 原有基金数据未丢失

| 表 | 导入前 | 导入后 | 说明 |
| --- | ---: | ---: | --- |
| `fund_nav_daily` | 39822 | 39822 | 未动 |
| `fund_dividends` | 44 | 44 | 未动 |
| `fund_manager_history` | 8 | 8 | 未动 |
| `fund_aum_history` | 8 | 8 | 未动 |
| `fund_data_quality` | 31 | 31 | 未动 |

---

## 7. 备份

| 项 | 值 |
| --- | --- |
| 备份路径 | `D:\ymy\jj-agent\data\backups\fund_agent_before_ingest_3b4_2_20261120_100028.db` |
| 大小 | 283,824,128 字节 |
| 备份方式 | `sqlite3` backup API（非文件复制，保证一致性） |
| 备份时机 | 迁移与导入**之前** |
| 是否入库 Git | ❌ `data/backups/` 在 `.gitignore` 中 |

---

## 8. 专项测试

`tests/test_ingest_3b4_2.py`，**41 项**，全部用独立临时数据库 + JSON 数据源，
不联网、不碰正式库。

**专项测试结果**：

```
$ pytest tests/test_ingest_3b4_2.py -q
52 passed in 18.81s
```

**全量测试结果**：

```
$ pytest -q
1040 passed, 1 warning in 299.81s (0:04:59)
```

| 项 | 数量 |
| --- | ---: |
| 专项测试 | **52** |
| 全量测试 | **1051** |
| 失败 | 0 |
| 跳过 | 0 |

1051 = 3B-4.1.1 的 999 + 3B-4.2 的 41 + 主从修正 11。

### 8.1 覆盖矩阵

| 类别 | 测试数 | 关键用例 |
| --- | ---: | --- |
| 迁移 | 5 | 列已加、幂等、旧列保留、UNIQUE 索引存在 |
| 范围筛选 | 4 | 41 场外 / 2 场内、结构分布 27/3/11 |
| 生命周期 | 9 | 41 行、排除 ETF、全 B、URL+ID、声明、多份额单本体、NULL 日期、幂等、支付宝不动 |
| 费率 | 15 | 类型齐全、原始/平台分列、金额边界、持有期边界、开闭区间、推断标记、NULL 费率、货币不伪造、C 级、effective 为 NULL、basis 为 NULL、年化标记、幂等 |
| 数据库 | 6 | integrity、外键、UNIQUE、原有数据、Repository 兼容 |
| 数据源不变 | 2 | 校准 JSON 仍 43 条、费率样本仍 12 只 |

### 8.2 关键断言示例

```python
# 场内 ETF 不得泄漏
assert not any("511000" in c or "511050" in c for c in off_codes)

# 缺失日期保持 NULL 且不冒充公告日
for r in nulls:
    assert r["announcement_date"] is not None
    assert r["event_date"] != r["announcement_date"]

# 闭区间可表达
assert d["holding_days_max_inclusive"] in (0, 1)

# 推断下界必须标记
assert r["holding_days_min"] == 0 and r["holding_days_min_inferred"] == 1

# 平台不是支付宝
assert r["platform_name"] == "eastmoney"
assert r["platform_name"] != "alipay"

# 抓取日期不冒充生效日期
assert effective_from is None and fetched_at is not None
```

---

## 9. 与阶段目标对照

| 要求 | 状态 |
| --- | --- |
| 41 个场外结构清盘事件入库 | ✅ 41 |
| 2 个场内 ETF 排除 | ✅ 0 泄漏 |
| 证据等级如实保存 | ✅ 生命周期 B、费率 C |
| 原始费率与平台费率分列 | ✅ `rate_original` / `rate_platform` |
| 费率区间边界可准确表达 | ✅ 新增 6 个开闭/推断字段 |
| 历史生效时间无证据保持未知 | ✅ 90 条 effective_from 全 NULL |
| 支付宝费率/状态不推断 | ✅ 全 unknown，无 alipay 平台行 |
| 缺失费率 NULL 不用 0 | ✅ 1 条 NULL（110022 销售服务费） |
| 货币基金不伪造赎回阶梯 | ✅ 000198 赎回 0 行 |
| 幂等 | ✅ 二次导入 0 新增 |
| SQLite 完整性 | ✅ ok，外键 0 违规 |
| 备份 | ✅ 导入前已备份 |

---

## 10. 尚未解决

| # | 问题 | 影响 |
| ---: | --- | --- |
| 1 | 43 条清盘公告仅 B 级（东财转载） | 未回源基金公司/交易所官网，证据等级无法升 A |
| 2 | 12 条清盘记录缺 `event_date` | 公告只写清算报告日，未写清算开始日 |
| 3 | 费率仅 C 级 | 天天基金 F10 非合同原文 |
| 4 | 费率 `effective_from` 全 NULL | 无法做历史费率模拟 |
| 5 | `holding_days_basis` 全 NULL | 自然日/交易日未确认，计算持有期成本时需明确标注 |
| 6 | 支付宝可购买状态全 unknown | 无公开合法接口 |
| 7 | 合并事件 0 个 | 无法验证 merge 类型 schema |
| 8 | 清盘名录覆盖率不可量化 | 无权威全量清单 |

---

## 11. 一句话

> **41 个场外结构清盘事件（全 B 级）、90 条费率规则（全 C 级）已正式入库，
> 幂等、完整性、外键全部通过，支付宝状态与 12 条缺失清盘日期都老老实实留在 NULL / unknown。
> 没有为了填满数据库制造任何一条数据。**

---

## 12. 验收修正：多份额基金主从标记（is_primary）

### 12.1 发现的 Bug

`app/fund/ingest_3b4_2.py` 的 `_ensure_share()` 在为同一基金本体创建**非主份额**时，
也用了 `is_primary=1`。结果：**同一基金本体出现多个主份额**。

| 项 | 修复前 |
| --- | ---: |
| 涉及基金本体 | 41 |
| 份额记录 | 63 |
| 主份额（`is_primary=1`） | **63** |
| 非主份额 | **0** |
| 恰好一个主份额的本体 | **21 / 41** |
| 违规本体 | **20** |

违规本体（主份额数 > 1）共 20 个，最多一个有 3 个主份额。

另一个问题：`_ensure_share()` 遇到已存在的份额代码时直接返回，
**没有校验该份额是否属于传入的 `fund_id`**——可能静默返回错误关联。

### 12.2 函数修复

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| 非主份额 `is_primary` | **1**（错） | **0** |
| 已存在份额归属校验 | 无 | **校验 `fund_id`，不一致抛 `ShareOwnershipError`** |
| 冲突处理 | 静默返回 | **抛错 + 记录到 `stat.conflicts`** |
| 主份额创建者 | 两处都可建 | **只由 `_ensure_master()` 建，唯一 `is_primary=1`** |

新增异常类 `ShareOwnershipError`，携带 `code` / `expected_fund_id` / `actual_fund_id`。

`_ensure_share()` 新签名：`_ensure_share(conn, fund_id, code, name, now, *, is_primary=0)`

### 12.3 正式数据库修复

修复脚本：`scripts/fix_3b4_2_primary_flags.py`

范围严格受限：

- 只处理 3B-4.2 那 **41 个**清盘事件涉及的基金本体；
- 用校准 JSON 的 `codes_in_event` + 原始 `_pick_primary_code()` 规则重算主代码；
- 份额代码若已属于其他本体 → 记录冲突、跳过、不覆盖；
- 不碰 3B-4.0 的 12 只存续基金。

**修复前后对比**：

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 检查的基金本体 | 41 | 41 |
| 份额记录 | 63 | 63 |
| 主份额 | 63 | **41** |
| 非主份额 | 0 | **22** |
| 恰好一个主份额的本体 | 21 | **41** |
| 违规本体 | 20 | **0** |
| 实际变更行数 | — | **22** |

变更的 22 个份额代码（全部由 1 改为 0）：

`000023`、`000027`、`000052`、`000088`、`000092`、`000093`、`010002`、`010007` 等。

### 12.4 修复后审计

| 检查项 | 结果 |
| --- | --- |
| 每个本体恰好一个主份额 | ✅ True |
| 主份额代码与 `_pick_primary_code()` 一致 | ✅ True |
| 其余份额全部 `is_primary=0` | ✅ 22 条 |
| 跨本体错误关联 | ✅ 0 |
| 冲突数量 | **0** |
| 3B-4.0 的 12 只存续基金主从 | ✅ 未变（`seeded_funds_unchanged=True`） |
| 41 个清盘事件数量 | ✅ 41（不变） |
| 90 条费率规则 | ✅ 90（不变） |
| `integrity_check` | ✅ ok |
| `foreign_key_check` 违规 | ✅ 0 |

### 12.5 幂等

| 执行 | 变更行数 | 幂等剩余待改 |
| --- | ---: | ---: |
| 第 1 次（修复） | **22** | 0 |
| 第 2 次（验证） | **0** | 0 |

备份：`D:\ymy\jj-agent\data\backups\fund_agent_before_primary_fix_20261120_105913.db`（283,930,624 字节）

### 12.6 新增测试

`tests/test_ingest_3b4_2.py` 新增 **11 项**（41 → 52）：

| # | 要求 | 测试 |
| ---: | --- | --- |
| 1 | 单代码本体一个主份额 | `test_single_code_fund_has_one_primary` |
| 2 | 双代码本体恰好一个主份额 | `test_two_code_fund_has_one_primary` |
| 3 | 三代码本体恰好一个主份额 | `test_three_code_fund_has_one_primary` |
| 4 | 主代码与 `_pick_primary_code()` 一致 | `test_primary_matches_pick_rule` |
| 5 | 其他份额全部 `is_primary=0` | `test_all_other_shares_non_primary` |
| 6 | 重复导入后主从不变 | `test_primary_unchanged_after_reimport` |
| 7 | 同本体已存在份额可复用 | `test_existing_share_same_fund_reused` |
| 8 | 属于他本体的份额报错 | `test_share_owned_by_other_fund_raises`、`test_conflict_does_not_reassign` |
| 9 | 修复脚本幂等 | `test_primary_fix_idempotent` |
| 10 | 不改变其他基金本体 | `test_primary_fix_only_touches_41_funds` |

---

## 13. 一句话（修正后补充）

> **主从关系修复前 41 个本体里只有 21 个合规、共 63 个主份额；
> 修复后 41 个全部恰好一个主份额（41 主 + 22 非主），
> 变更 22 行，二次执行 0 变更，3B-4.0 的 12 只存续基金主从完全未动。**

---
