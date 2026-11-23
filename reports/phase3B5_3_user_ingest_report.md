# 阶段3B-5.3 用户自选场外基金受控数据接入 V1.0

- 基线 HEAD：`d311260e1e9056b4176950e1a709cea7e97f3974`
- 执行日期：2026-11-23
- 新增包：`app/fund/ingest_user_funds/`
- 专项测试：`tests/test_3b5_3_user_ingest.py`

> **查询与采集完全分离。**
> `python -m app.fund.research --code` 永远只读；
> `python -m app.fund.ingest_user_funds` 是唯一写入入口。

---

## 0. 结论先行

| 项 | 结果 |
| --- | --- |
| 独立接入命令 | **`python -m app.fund.ingest_user_funds`** |
| 查询命令仍只读 | **是**（未改动 `--code` 行为） |
| 真实接入基金 | **5 个份额 / 3 个本体** |
| A/C 归组 | **成功**（2 对归入同一本体） |
| 重复接入幂等 | **是**（指纹完全不变） |
| 失败不留半成品 | **是** |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

---

## 1. 数据源能力审计

只使用 3B-3 已审计通过的 AKShare 接口，**不抓支付宝、不逆向 APP**。

| 数据 | 接口 | 可获取字段 | 历史覆盖 | 更频 | 缺失/重复 | 披露日 | 证据 | 适合研究 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 基本信息 | `fund_individual_basic_info_xq` | 名称/全称/公司/托管/类型/基准/成立时间/规模 | 当前快照 | 不定 | 无重复 | 无 | third_party | ✅ 有限 |
| 份额代码 | 同上 | 单一代码 | 当前 | 不定 | 每个代码独立 | 无 | third_party | ✅ |
| 单位净值 | `fund_open_fund_info_em(单位净值走势)` | 净值日期/单位净值/日增长率 | 成立以来 | 每交易日 | 无重复（UNIQUE 约束） | **无** | third_party | ✅ 描述性 |
| 累计净值 | `fund_open_fund_info_em(累计净值走势)` | 净值日期/累计净值 | 成立以来 | 每交易日 | 与单位净值日期可能不一致 | **无** | third_party | ✅ 描述性 |
| 货币收益 | `fund_money_fund_info_em` | 净值日期/每万份收益/7日年化 | 成立以来 | 每交易日 | 无重复 | **无** | third_party | ✅ 独立口径 |
| 历史分红 | `fund_open_fund_info_em(分红送配详情)` | 权益登记日/除息日/发放日/每10份分红 | 成立以来 | 事件驱动 | **接口偶发返回空** | 有登记日 | third_party | ⚠️ 不完整 |
| 成立日/生命周期 | 基本信息 + 库内事件 | 成立时间 | 单时点 | 不定 | — | 有 | third_party | ⚠️ 生命周期 unknown |

**明确不可用**：

| 项 | 结论 |
| --- | --- |
| 真实净值公布日历 | **不可得**，只用 `cannot_verify`，不用 A 股交易日历代理 |
| 支付宝可购买状态 | **不可得**，恒 `unknown` |
| 支付宝实际费率 | **不可得**，不接入、不推断 |
| 历史费率生效日 | 大部分不可得，仅少数公告有 |

---

## 2. CLI

```bash
# 单只
python -m app.fund.ingest_user_funds --code 012346

# 批量（一行一个，支持 # 注释与空行）
python -m app.fund.ingest_user_funds --codes-file my_funds.txt
python -m app.fund.ingest_user_funds --codes-file f.txt --json out.json

# 只预检不写库
python -m app.fund.ingest_user_funds --code 012346 --dry-run

# 跳过备份（不推荐）
python -m app.fund.ingest_user_funds --code 012346 --no-backup
```

### 接入状态

| 状态 | 含义 |
| --- | --- |
| `ingested` | 接入成功 |
| `already_present` | 库内已存在，**未重复写入** |
| `not_found` | 接口无该代码 |
| `invalid_code` | 非 6 位数字 |
| `excluded_product` | 场内 ETF / QDII 明确拒绝 |
| `failed` | 取数或写入失败，**不留半成品** |
| `timeout` | 接口超时 |

---

## 3. 数据写入安全

| 措施 | 实现 |
| --- | --- |
| 接入前备份 | `data/backups/fund_agent_before_3b5_3_user_ingest_*.db` |
| 前后指纹 | `fingerprint_before` / `fingerprint_after`（行数 + 内容摘要 SHA256） |
| 幂等 | 已存在直接返回 `already_present`，不写 |
| 不覆盖有效数据 | 复用 `upsert_*` 的来源置信度规则 |
| 失败不留半成品 | **先把数据全取到内存**，任一环节失败直接 return，不写库 |
| 来源与时间 | 每条记录带 `source` + `ingested_at` |
| 不改既有证据 | 不动 `fund_lifecycle_events` / `fund_data_quality` 历史行 |
| 不删除历史 | 只追加质量警告，不删除任何行 |

**无 Schema 变更**：全部复用现有列，未新增字段、未改迁移文件。

---

## 4. 质量审计

每只新接入基金输出：

| 检查项 | 输出 |
| --- | --- |
| 重复日期 | `duplicate_dates`（DDL UNIQUE 保证为 0） |
| 日期乱序 | `out_of_order`（SQL ORDER BY 保证为 0） |
| 空值 | `null_unit_nav` / `null_acc_nav` |
| 非正净值 | `nonpositive_unit_nav` |
| 超 15 天缺口 | `gap_count_over_15d` + `gaps_sample` |
| 起止日期 | `date_min` / `date_max` |
| 来源 | `sources[]` |
| 累计净值语义 | `acc_equals_unit_ratio` / `has_dividend_effect` |
| 货币类型 | `nav_kind=money_yield` |
| A/C 映射 | `fund_id` + `warnings` |
| 连续性 | **恒 `cannot_verify`** |

> 连续性说明固定写明：「无真实基金净值公布日历；不使用 A 股交易日历代理」。

---

## 5. 真实接入结果

| 代码 | 名称 | 类型 | 分类 | 净值行 | 起 | 止 |
| --- | --- | --- | --- | ---: | --- | --- |
| `000961` | 天弘沪深300ETF联接 | 股票型-标准指数 | — | 2882 | 2015-01-20 | 2026-11-20 |
| `012344` | 嘉实领先优势混合 | 混合型-偏股 | — | 1277 | 2021-06-09 | 2026-11-20 |
| `012345` | 嘉实领先优势混合 | 混合型-偏股 | — | 1277 | 2021-06-09 | 2026-11-20 |
| `012346` | 易方达港股通成长混合 | 混合型-偏股 | — | 1230 | 2021-08-31 | 2026-11-20 |
| `012347` | 易方达港股通成长混合 | 混合型-偏股 | — | 1230 | 2021-08-31 | 2026-11-20 |

### A/C 归组验证

| 本体 | 份额 | 主份额 |
| --- | --- | --- |
| `012344` 嘉实领先优势混合 | `012344` / `012345` | `012344` |
| `012346` 易方达港股通成长混合 | `012346` / `012347` | `012346` |

### 拒绝场景验证

| 代码 | 状态 | 原因 |
| --- | --- | --- |
| `511000` | `excluded_product` | 场内 ETF 不进入场外基金数据层 |
| `006479` | `excluded_product` | QDII 不属于场外默认范围 |
| `999999` | `failed` | 接口无该代码，未写任何数据 |
| `abc` | `invalid_code` | 非 6 位数字 |

### 幂等验证

重复接入 5 个已存在代码：全部返回 `already_present`，
`fingerprint_unchanged = true`（`9ac0c6c9e812f427` 前后一致）。

### 接入后可查询

```bash
$ python -m app.fund.research --code 012346
# 基金本体 012346 易方达港股通成长混合
# 份额数：2  代表份额：012346
```

---

## 6. 数据库状态

| 检查 | 结果 |
| --- | --- |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0 违规** |

| 表 | 接入前行数 | 接入后行数 | 变化 |
| --- | ---: | ---: | ---: |
| `fund_aum_history` | 683 | 683 | 0 |
| `fund_data_quality` | 31 | 31 | 0 |
| `fund_dividends` | 44 | 44 | 0 |
| `fund_fee_rules` | 90 | 90 | 0 |
| `fund_lifecycle_events` | 49 | 49 | 0 |
| `fund_manager_history` | 21 | 21 | 0 |
| `fund_master` | 50 | 53 | +3 |
| `fund_nav_daily` | 39822 | 47718 | +7896 |
| `fund_share_classes` | 75 | 80 | +5 |
| `fund_subscription_status` | 12 | 12 | 0 |

**关键不变项**：

| 项 | 值 |
| --- | --- |
| 清盘本体（terminated） | **41**（不变） |
| 清盘事件 | **49**（不变） |
| 分红 | **44**（不变） |
| 费率 | **90**（不变） |
| 经理历史 | **21**（不变） |
| 规模历史 | **683**（不变） |
| ETF 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`（不变） |

---

## 7. 数据来源与证据等级统计

| 来源 | 本体数 |
| --- | ---: |
| `dfcfw.announcement.calibrated` | 41 |
| `akshare.fund_individual_basic_info_xq` | 12（原 7 + 本轮 5） |
| `akshare.fund_name_em` | 1 |

| 证据等级 | 用于 |
| --- | --- |
| `third_party` | 本轮全部新接入（基本信息、净值） |
| `platform_observation` | 规模（未在本轮接入） |

---

## 8. 测试结果

### 8.1 新增专项（本地实际运行）

```
$ pytest tests/test_3b5_3_user_ingest.py -q
27 passed
```

全部使用临时 SQLite + 注入式假抓取器，**不联网、不碰正式库**。

覆盖 20 项要求：

| # | 要求 | 测试 |
| ---: | --- | --- |
| 1 | 普通指数基金 | `test_ingest_ordinary_index` |
| 2 | ETF 联接 | `test_ingest_etf_linked` |
| 3 | 主动权益 | `test_ingest_active_equity` |
| 4 | 债券基金 | `test_ingest_bond` |
| 5 | 货币独立 | `test_ingest_money_independent` |
| 6 | A/C 归组 | `test_ac_shares_grouped` |
| 7 | 不存在代码 | `test_not_found` |
| 8 | 场内 ETF 拒绝 | `test_onshore_etf_rejected` |
| 9 | QDII 处理 | `test_qdii_handled` |
| 10 | 接口失败/超时 | `test_fetch_failure_no_partial` / `test_timeout_status` |
| 11 | 幂等 | `test_reingest_is_idempotent` |
| 12 | 不覆盖旧数据 | `test_reingest_does_not_overwrite` |
| 13 | 空值不填 0 | `test_null_nav_not_zero` |
| 14 | 缺口审计 | `test_gap_quality_audit` |
| 15 | 批量隔离 | `test_batch_isolates_failures` |
| 16 | 来源与证据 | `test_sources_and_evidence_recorded` |
| 17 | 接入后可查询 | `test_queryable_after_ingest` |
| 18 | 原样本回归 | `test_real_default_pool_unchanged` |
| 19 | 清盘不受影响 | `test_real_lifecycle_untouched` |
| 20 | 不留半成品 | `test_fetch_failure_no_partial` / `test_nav_failure_no_partial` |

### 8.2 全量（本地实际运行）

```
$ pytest -q
1445 passed, 1 warning in 355.05s (0:05:55)
```

---

## 9. 已知限制

| # | 限制 |
| ---: | --- |
| 1 | 只能接入 AKShare 能返回的基金；接口无数据返回 `not_found` |
| 2 | 生命周期恒 `unknown`（无运作公告证据，不推断） |
| 3 | 无净值公布日历，连续性 `cannot_verify` |
| 4 | 分红接口偶发返回空，不能据此判断「无分红」 |
| 5 | 支付宝可购买状态恒 `unknown` |
| 6 | 支付宝费率不接入、不推断 |
| 7 | 未接入 QDII 与场内 ETF（明确排除） |
| 8 | 未接入费率/经理/规模（本阶段范围只到净值与基本信息） |

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
