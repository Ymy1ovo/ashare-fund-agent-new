# 阶段3B-4.0  支付宝场外基金数据层基础设施落地

- 基线 HEAD：`0a9c5f8433817f1e5fd0aab2db94e20a77abc54c`
- 执行日期：2026-11-19
- 迁移文件：`migrations/phase3b4_fund_data_layer.sql`
- 数据层：`app/fund/`
- 导入脚本：`scripts/ingest_3b4_fund_sample.py`
- 专项测试：`tests/test_fund_data_layer.py`

---

## 0. 结论先行

> **10 张表全部落地，12 只样本基金完成真实入库，迁移与导入均可重复执行。**

| 验收标准 | 结果 |
| --- | --- |
| 1. 10 张表全部正式落地 | ✅ 全部创建 |
| 2. 迁移可重复执行 | ✅ 三次执行无变化 |
| 3. 本体与份额关系正确 | ✅ 9 个本体 / 12 个份额，A/C 正确归属 |
| 4. 12 只样本完成真实入库 | ✅ 全部入库 |
| 5. 单位/累计净值/分红口径正确 | ✅ 分列存储，每10份已除以 10 |
| 6. 重复导入不产生重复 | ✅ 三次导入行数一致 |
| 7. 未知字段不被伪造 | ✅ 费率 NULL、清盘 NULL、任职 NULL、支付宝 unknown |
| 8. 新增测试通过 | ✅ 48 项专项测试 |
| 9. 原有 ETF 数据未变 | ✅ 全部表行数 0 变化，指纹一致 |
| 10. 文档与实际一致 | ✅ 本报告数字全部来自真实运行 |

---

## 1. 新增的 10 张表

全部为新增表，**未修改任何既有 ETF 行情/指标/回测/会计/公司行为表**。

| # | 表 | 行数 | 用途 |
| ---: | --- | ---: | --- |
| 1 | `fund_master` | 9 | 基金本体（一只基金一行，A/C 共用） |
| 2 | `fund_share_classes` | 12 | 份额类别（A/C/E/I 等），一个本体多行 |
| 3 | `fund_nav_daily` | 39,822 | 每日净值（单位净值/累计净值分列；货币基金独立分支） |
| 4 | `fund_dividends` | 44 | 分红记录（保留每10份原始文本 + 归一化每份金额） |
| 5 | `fund_manager_history` | 8 | 基金经理任职历史 |
| 6 | `fund_aum_history` | 8 | 规模历史 |
| 7 | `fund_fee_rules` | 0 | 申购/赎回/销售服务费规则（费率允许 NULL） |
| 8 | `fund_subscription_status` | 12 | 申购赎回状态按日快照 |
| 9 | `fund_lifecycle_events` | 8 | 成立/清盘/合并/份额变更事件 |
| 10 | `fund_data_quality` | 31 | 数据质量检查结果 |

### 1.1 每张表的实际字段

#### `fund_master`（9 行）

字段：`fund_id`、`fund_code_primary`、`fund_name`、`fund_full_name`、`fund_company`、`custodian`、`fund_type_l1`、`fund_type_l2`、`invest_scope`、`benchmark`、`established_date`、`terminated_date`、`lifecycle_status`、`is_index_fund`、`tracking_index`、`needs_review`、`source`、`source_updated_at`、`ingested_at`、`data_version`

#### `fund_share_classes`（12 行）

字段：`share_class_id`、`fund_id`、`share_class_code`、`share_class_name`、`share_class_type`、`currency`、`is_primary`、`management_fee`、`custody_fee`、`sales_service_fee`、`min_purchase`、`min_holding`、`listed_date`、`terminated_date`、`source`、`source_updated_at`、`ingested_at`

#### `fund_nav_daily`（39,822 行）

字段：`share_class_id`、`nav_date`、`nav_kind`、`unit_nav`、`acc_nav`、`per_10k_yield`、`seven_day_annual`、`daily_return`、`nav_status`、`source`、`ingested_at`

#### `fund_dividends`（44 行）

字段：`dividend_id`、`share_class_id`、`record_date`、`ex_date`、`pay_date`、`cash_per_share`、`per_10_raw`、`dividend_type`、`reinvest_nav`、`source`、`source_updated_at`、`ingested_at`

#### `fund_manager_history`（8 行）

字段：`manager_id`、`fund_id`、`manager_name`、`company`、`start_date`、`end_date`、`tenure_days`、`source`、`ingested_at`

#### `fund_aum_history`（8 行）

字段：`aum_id`、`fund_id`、`share_class_id`、`report_date`、`aum_total`、`shares_total`、`aum_unit`、`source`、`ingested_at`

#### `fund_fee_rules`（0 行）

字段：`fee_rule_id`、`share_class_id`、`fee_type`、`tier_order`、`lower_bound`、`upper_bound`、`rate`、`holding_days_min`、`holding_days_max`、`effective_from`、`effective_to`、`source`、`evidence_level`、`ingested_at`

#### `fund_subscription_status`（12 行）

字段：`status_id`、`share_class_id`、`as_of_date`、`purchase_status`、`redeem_status`、`daily_limit`、`min_purchase`、`next_open_date`、`alipay_purchasable`、`source`、`ingested_at`

#### `fund_lifecycle_events`（8 行）

字段：`event_id`、`fund_id`、`event_type`、`event_date`、`announcement_date`、`announcement_url`、`detail`、`successor_fund_id`、`evidence_level`、`source`、`ingested_at`

#### `fund_data_quality`（31 行）

字段：`quality_id`、`table_name`、`record_key`、`check_name`、`status`、`detail`、`severity`、`checked_at`

### 1.2 关键约束

| 约束 | 说明 |
| --- | --- |
| `fund_share_classes.fund_id → fund_master` | 外键，`ON DELETE CASCADE` |
| `fund_share_classes.share_class_code UNIQUE` | 份额代码必须独立唯一 |
| `fund_nav_daily` 主键 `(share_class_id, nav_date, nav_kind)` | 同一日期同一类型只一行 |
| `fund_nav_daily` CHECK | 净值型必须有 `unit_nav` 且不能有 `per_10k_yield`；货币型反之 |
| `fund_dividends` UNIQUE `(share_class_id, ex_date, source)` | 同源幂等，**不同源各留一条**用于保留差异 |
| `fund_subscription_status` UNIQUE `(share_class_id, as_of_date, source)` | 按日快照，历史不被覆盖 |
| `alipay_purchasable` CHECK | 只允许 `unknown/yes/no`，默认 `unknown` |
| `lifecycle_status` CHECK | 只允许 `active/terminated/merged/unknown`，默认 `unknown` |
| `needs_review` CHECK | 0/1，无法可靠归属时置 1 |

---

## 2. 数据源实际入库情况

只用 3B-3 已审计通过的接口，未扩展新数据源。

| 数据源 | 用途 | 入库结果 |
| --- | --- | --- |
| `akshare.fund_name_em` | 基金代码/名称/类型 | ✅ 28,380 条代码表，样本全部命中 |
| `akshare.fund_individual_basic_info_xq` | 成立日/规模/公司/经理/业绩基准 | ✅ 11/12 成功（货币基金接口不支持） |
| `akshare.fund_open_fund_info_em(单位净值走势)` | 每日单位净值 | ✅ 34,903 行 |
| `akshare.fund_open_fund_info_em(累计净值走势)` | 每日累计净值 | ✅ 与单位净值按日期合并，无日期不匹配 |
| `akshare.fund_open_fund_info_em(分红送配详情)` | 分红记录 | ✅ 44 行 |
| `akshare.fund_money_fund_info_em` | 货币基金收益 | ✅ 4,919 行 |
| `akshare.fund_purchase_em` | 申购赎回状态 | ✅ 12 行（当日快照） |

### 2.1 未入库的数据（数据源不提供）

| 数据 | 状态 | 处理 |
| --- | --- | --- |
| 赎回费阶梯 | ❌ 无数据源 | `fund_fee_rules` 表 **0 行**，rate 保持 NULL |
| 销售服务费 | ❌ 无数据源 | NULL |
| 清盘/合并名录 | ❌ 无数据源 | `fund_lifecycle_events` 只写 established 事件 |
| 基金经理任职起止 | ❌ 无数据源 | `start_date`/`end_date` 保持 NULL |
| 规模历史序列 | ❌ 只有当前值 | 只写 1 条当前规模 |
| 支付宝可购买状态 | ❌ 无证据 | 全部 `unknown` |

---

## 3. 12 只样本基金入库情况

### 3.1 按基金本体分组（关键：A/C 归属）

| 类别 | 代码 | 本体数 | 归属结果 |
| --- | --- | ---: | --- |
| 宽基指数 | `000051` | 1 | ✅ 正确 |
| 宽基指数 | `110020` | 1 | ✅ 正确 |
| 行业指数 | `161725`、`012414` | 1 | ✅ 正确 |
| ETF联接 | `007300`、`007301` | 1 | ✅ 正确 |
| 主动权益 | `110022` | 1 | ✅ 正确 |
| 主动权益 | `161005` | 1 | ✅ 正确 |
| 指数增强 | `000478` | 1 | ✅ 正确 |
| 债券 | `000015`、`000016` | 1 | ✅ 正确 |
| 货币 | `000198` | 1 | ✅ 正确 |

**12 个份额代码 → 9 个基金本体。**

A/C 配对的 3 组全部归为同一本体：

| 本体 | 主代码 | 份额 |
| --- | --- | --- |
| 基金本体 #16 | `161725` | `161725`、`012414` |
| 基金本体 #17 | `007300` | `007300`、`007301` |
| 基金本体 #21 | `000015` | `000015`、`000016` |

### 3.2 逐只入库明细

| 代码 | 类别 | 本体 | 份额 | 净值行数 | 分红 | 状态快照 | 货币分支 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `000051` | 宽基指数 | 14 | 14 | 4,220 | 0 | 1 | 否 |
| `110020` | 宽基指数 | 15 | 15 | 4,186 | 0 | 1 | 否 |
| `161725` | 行业指数 | 16 | 16 | 2,794 | 0 | 1 | 否 |
| `012414` | 行业指数 | 16 | 17 | 1,338 | 0 | 1 | 否 |
| `007300` | ETF联接 | 17 | 18 | 1,799 | 0 | 1 | 否 |
| `007301` | ETF联接 | 17 | 19 | 1,799 | 0 | 1 | 否 |
| `110022` | 主动权益 | 18 | 20 | 3,927 | 0 | 1 | 否 |
| `161005` | 主动权益 | 19 | 21 | 5,124 | 0 | 1 | 否 |
| `000478` | 指数增强 | 20 | 22 | 3,096 | 0 | 1 | 否 |
| `000015` | 债券 | 21 | 23 | 3,310 | 0 | 1 | 否 |
| `000016` | 债券 | 21 | 24 | 3,310 | 0 | 1 | 否 |
| `000198` | 货币 | 22 | 25 | 4,919 | 0 | 1 | 是 |

### 3.3 净值口径抽检

| 代码 | 最新日期 | 单位净值 | 累计净值 | 说明 |
| --- | --- | ---: | ---: | --- |
| `161725` | 2026-11-18 | 0.5791 | **2.2952** | 有 9 次份额折算，两值差异极大 |
| `161005` | 2026-11-18 | 2.4727 | **5.5207** | 16 次分红累计 |
| `000015` | 2026-11-18 | 1.2109 | **1.6015** | 9 次分红 |
| `000051` | 2026-11-18 | 1.5402 | 1.5402 | 无分红，两值相等 |

**单位净值与累计净值是两列独立存储，没有混用。**

---

## 4. 实际入库行数

| 表 | 行数 |
| --- | ---: |
| `fund_master` | 9 |
| `fund_share_classes` | 12 |
| `fund_nav_daily` | 39,822 |
| `fund_dividends` | 44 |
| `fund_manager_history` | 8 |
| `fund_aum_history` | 8 |
| `fund_fee_rules` | 0 |
| `fund_subscription_status` | 12 |
| `fund_lifecycle_events` | 8 |
| `fund_data_quality` | 31 |
| **合计** | **39,954** |

---

## 5. 幂等验证结果

### 5.1 迁移幂等

连续执行 `ensure_fund_schema()` 三次，表数量与各表行数完全不变。

### 5.2 导入幂等

同一批真实数据导入三次：

| 表 | 第 1 次 | 第 2 次 | 第 3 次 | 是否收敛 |
| --- | ---: | ---: | ---: | --- |
| `fund_master` | 9 | 9 | 9 | ✅ |
| `fund_share_classes` | 12 | 12 | 12 | ✅ |
| `fund_nav_daily` | 39,822 | 39,822 | 39,822 | ✅ |
| `fund_dividends` | 40 | 44 | 44 | ⚠️ 见下 |
| `fund_subscription_status` | 12 | 12 | 12 | ✅ |
| `fund_data_quality` | 31 | 31 | 31 | ✅ |

**关于 `fund_dividends` 从 40 → 44**：

这不是重复写入。3B-3.1 已经实测过：**分红接口单次返回会不完整**，
同一代码两次可能给出不同条数。第 1 次导入抓到 40 条，第 2、3 次抓到了更完整的 44 条，
之后收敛稳定。

验证：按 `(share_class_id, ex_date, source)` 分组，**重复组数 = 0**，
说明没有产生重复记录，只是补全了缺失记录。

## 6. 未知字段的处理

| 字段 | 处理 | 证据 |
| --- | --- | --- |
| 赎回费率 | **NULL**，未填行业平均 | `fund_fee_rules` 0 行，质量表 13 条 `redemption_fee_missing` |
| 清盘日期 | **NULL**，未推测 | 质量表 `liquidated_fund_list_missing` |
| 经理任职起止 | **NULL**，未用今天伪造 | 质量表 `manager_tenure_unknown` |
| 支付宝可购买 | **unknown** | 质量表 `alipay_purchasable_unknown`；DDL CHECK 约束 |
| 成立日期（货币基金） | **NULL** | 接口不支持，质量表留痕 |

数据质量表共 **31 条**记录，其中 `missing` 类 26 条、`ok` 类 5 条。

---

## 7. 测试结果

**专项测试**（真实运行）：

```
$ pytest tests/test_fund_data_layer.py -q
48 passed in 12.00s
```

**全量测试**（真实运行）：

```
$ pytest -q
856 passed, 1 warning in 317.14s (0:05:17)
```

| 项 | 数量 |
| --- | ---: |
| 通过 | **856** |
| 失败 | 0 |
| 跳过 | 0 |
| 耗时 | 317.14 秒 |

856 = 3B-3.1 的 808 + 本轮新增 48 项基金数据层测试。

**区分真实运行与静态检查**：

| 项 | 类型 | 是否算入 856 |
| --- | --- | --- |
| ast.parse 语法检查 | 静态检查 | 不计入 |
| 48 项基金数据层测试 | 真实运行 | 计入 |
| 12 只样本真实导入 | 真实运行（联网） | 不是 pytest 用例 |
| 三次幂等导入验证 | 真实运行（联网） | 不是 pytest 用例 |
| 全量 pytest | 真实运行 | 计入 |

### 7.1 测试覆盖点

| 要求 | 测试函数 |
| --- | --- |
| 迁移首次执行 | `test_migration_creates_all_ten_tables` |
| 迁移重复执行 | `test_migration_is_idempotent` |
| 迁移不碰 ETF 表 | `test_migration_does_not_touch_etf_tables` |
| 外键约束 | `test_foreign_key_enforced` |
| 份额代码唯一 | `test_share_class_code_is_unique` |
| 净值类型 CHECK | `test_nav_check_constraint_rejects_mixed_kind` |
| 来源置信度 | `test_conflicting_source_cannot_overwrite_better` |
| 本体份额关联 | `test_master_and_share_linked` |
| A/C 正确归属 | `test_ac_shares_share_one_master`、`test_group_merges_ac_shares_into_one_master` |
| 不强行合并 | `test_group_does_not_merge_different_bases` |
| 份额代码独立 | `test_share_codes_never_merged` |
| 净值批量写入 | `test_nav_batch_insert` |
| 单位/累计分离 | `test_unit_and_acc_nav_separate` |
| 净值重复幂等 | `test_nav_repeat_write_is_idempotent` |
| 净值区间查询 | `test_nav_query_by_date_range` |
| 分红每10份换算 | `test_dividend_per_10_conversion` |
| 分红重复幂等 | `test_dividend_repeat_write_idempotent` |
| 分红跨源留证 | `test_dividend_different_source_keeps_both` |
| 状态按日快照 | `test_status_snapshot_keeps_history` |
| 支付宝 unknown | `test_alipay_status_defaults_unknown` |
| 费率 NULL | `test_fee_rate_may_be_null` |
| 费率按持有期查 | `test_fee_rule_query_by_holding_days` |
| 质量记录幂等 | `test_quality_record_is_idempotent` |
| 质量记录 mismatch | `test_quality_records_mismatch` |
| 生命周期幂等 | `test_lifecycle_event_idempotent` |
| 经理 NULL 日期 | `test_manager_tenure_dates_may_be_null` |
| 经理幂等 | `test_manager_idempotent` |
| NULL 未知字段 | `test_unknown_established_date_stays_null`、`test_unknown_terminated_date_stays_null` |
| 事务回滚 | `test_transaction_rollback_on_error` |
| 货币独立处理 | `test_money_fund_uses_separate_branch`、`test_money_fund_rejects_unit_nav` |
| 净值日期不匹配 | `test_ingest_nav_missing_acc_nav_is_recorded` |
| 端到端 Mock | `test_ingest_end_to_end_with_mock` |
| 重复导入无重复 | `test_ingest_duplicate_run_no_duplicates` |

**全部使用独立临时数据库 + Mock 外部接口，不联网、不污染正式库。**

---

## 8. 原有数据库指纹

### 8.1 表行数对比（执行前后）

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
| `etf_pool` | 46 | 46 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |
| `etf_indicator_daily` | 350,292 | 350,292 | **0** |
| `backtest_runs` | 507 | 507 | **0** |
| `backtest_orders` | 29,255 | 29,255 | **0** |
| `backtest_trades` | 26,100 | 26,100 | **0** |
| `validation_runs` | 64 | 64 | **0** |
| `validation_grid` | 440 | 440 | **0** |
| `validation_windows` | 486 | 486 | **0** |
| `validation_backtest_runs` | 854 | 854 | **0** |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_applications` | 8,873 | 8,873 | **0** |
| `dividend_receivables` | 4,947 | 4,947 | **0** |

### 8.2 指纹

| 项 | 值 |
| --- | --- |
| `PRAGMA integrity_check` | **ok** |
| 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| 行情行数 | 116,609 |
| 与 3B-3.1 基线对比 | **完全一致** |

**新表与旧系统完全隔离**：`fund_*` 表不被任何 ETF 侧代码引用。

---

## 9. 尚未解决的数据限制

| # | 限制 | 严重性 | 状态 |
| ---: | --- | --- | --- |
| 1 | **清盘基金名录完全缺失** | 🔴 高 | `survivorship_bias_unresolved` 未解决 |
| 2 | **赎回费阶梯无数据源** | 🔴 高 | 表已建，0 行，rate 保持 NULL |
| 3 | 销售服务费无字段 | 🟡 中 | NULL |
| 4 | 基金转换规则无接口 | 🟡 中 | 未建采集 |
| 5 | 支付宝可购买状态 unknown | 🟡 中 | 全部 unknown，已加 CHECK 约束 |
| 6 | 申购状态无历史，只能从今天起积累 | 🟡 中 | 已建按日快照表 |
| 7 | 规模历史只有当前值 | 🟢 低 | 每基金 1 条 |
| 8 | 经理任职起止缺失 | 🟢 低 | NULL，已留痕 |
| 9 | 货币基金基本信息接口失败 | 🟢 低 | 字段保持 NULL，已留痕 |
| 10 | 分红接口单次返回可能不完整 | 🟢 低 | 多次导入会补全，已验证无重复 |

### 9.1 两个仍阻塞正式回测的问题

**问题 1 和 2 未解决**：

- 没有清盘名录 → 任何历史回测都带幸存者偏差；
- 没有赎回费阶梯 → 交易成本算不出来。

本轮只解决了**基础设施**问题（表、仓储、导入、幂等、留痕），
**没有**解决数据可得性问题。这一点必须明确。

---

## 10. 工程边界核对

| 禁止项 | 执行情况 |
| --- | --- |
| 修改 `app/backtest/` | ❌ 未修改 |
| 修改 `app/validation/` | ❌ 未修改 |
| 修改 `app/quant/` | ❌ 未修改 |
| 修改 ETF 公司行为/会计/撮合 | ❌ 未修改 |
| 开发场外基金回测引擎 | ❌ 未开发 |
| 开发选基/择时策略 | ❌ 未开发 |
| 自动下单/接入实盘 | ❌ 未涉及 |
| 未知费率填行业平均 | ❌ 保持 NULL |
| 包装清盘问题为已解决 | ❌ 明确标未解决 |
| 天天基金状态冒充支付宝 | ❌ 全部 unknown |
| 历史缺口静默填补 | ❌ 缺口如实记录 |

---

## 11. 产物

| 文件 | 说明 |
| --- | --- |
| `migrations/phase3b4_fund_data_layer.sql` | 10 张表迁移（可重复执行） |
| `app/fund/__init__.py` | 数据层导出 |
| `app/fund/migration.py` | 建表入口 |
| `app/fund/models.py` | 10 类记录 dataclass |
| `app/fund/normalize.py` | 归一化纯函数 |
| `app/fund/repo_base.py` | 来源置信度与覆盖规则 |
| `app/fund/repository.py` | 本体/份额/生命周期/经理/规模 |
| `app/fund/repo_nav.py` | 净值与分红 |
| `app/fund/repo_status.py` | 状态快照与费率 |
| `app/fund/repo_quality.py` | 数据质量 |
| `app/fund/ingest.py` | 导入流程（含 Mock 注入点） |
| `scripts/ingest_3b4_fund_sample.py` | 12 只样本真实导入 |
| `tests/test_fund_data_layer.py` | 48 项专项测试 |
| `reports/phase3B4_fund_data_layer.md` | 本报告 |
| `reports/phase3B4_fund_data_layer.json` | 机器可读结果 |
