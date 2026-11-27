# 阶段3B-6.2.3.1.1 设计：全收益指数独立原始数据层

> **只建原始归档与隔离存储。不建设正式全收益序列，不开放回测。**

**基线 HEAD**：`3aae887da4a82ba77481c0efdb2f32c11feef618`

---

## 1. 设计目标

建设一个与 `index_daily` **完全物理隔离**的全收益指数原始数据归档层。

**核心约束**：

| 约束 | 落实方式 |
| --- | --- |
| 与 `index_daily` 隔离 | 全部表使用 `tr_` 前缀；不读不写 `index_daily` |
| 原始数据不清洗 | 逐行原样归档，异常行保留原值 |
| 未验证行不默认有效 | 逐行质量标记，**无 `verified` 状态** |
| 可追溯 | 每行引用原始证据文件 + SHA256 |
| 幂等 | 主键 `(tr_code, trade_date)` + 唯一 `batch_key` |
| 可回滚 | 独立 down 迁移，只删 `tr_*` 表 |

---

## 2. 表结构设计

### 2.1 六张表

| 表名 | 用途 |
| --- | --- |
| `tr_candidate_master` | 候选注册表（12 条） |
| `tr_evidence_files` | 原始证据与 SHA256 |
| `tr_ingest_runs` | 导入批次审计 |
| `tr_index_daily_raw` | 原始历史行情（逐行） |
| `tr_candidate_quality` | 质量与连续性快照 |
| `tr_price_index_mapping` | 候选与价格指数映射（技术推断） |

### 2.2 关键字段设计

#### `tr_candidate_master`

| 字段 | 说明 |
| --- | --- |
| `market_group` | `stock` / `bond` / `hk`，**三者严格隔离** |
| `return_basis` | `gross_total_return` / `net_total_return` / `bond_clean_price` / `bond_interest_reinvestment` / `unknown` |
| `calendar_type` + `calendar_available` + `calendar_is_official` | 适用日历三要素 |
| `continuity_level` | 五态（官方/代理/疑似/有问题/未知） |
| `real_history_start` | **默认 `unknown`**，未确认不得改 |
| `mapping_evidence_level` | 默认 `technical_inference`，**非官方确认** |
| 四个准入状态 | 独立字段，本阶段全部保持审计结论 |

#### `tr_index_daily_raw`

| 字段 | 说明 |
| --- | --- |
| `close` / `open` / `high` / `low` | **可 NULL**，缺失即 NULL，**不补 0** |
| `volume` / `amount` / `change` / `change_pct` | 原样保留 |
| `returned_code` / `returned_name` | 接口返回的代码与名称 |
| `evidence_relative_path` + `evidence_sha256` | **每行可追溯到原始文件** |
| `row_quality_status` | 五态，**默认 `unknown`** |

**质量状态枚举（无 verified）**：

| 状态 | 含义 |
| --- | --- |
| `normal_unverified` | 原始值正常但**未经验证** |
| `suspected_synthetic` | 疑似请求起始日合成行 |
| `suspected_market_closed_placeholder` | 疑似休市占位行 |
| `invalid_value` | 非正值/缺失/非数值 |
| `unknown` | 无法判定 |

---

## 3. 隔离设计

### 3.1 三层隔离

| 层 | 手段 |
| --- | --- |
| 表名 | 全部 `tr_` 前缀，白名单 `TR_TABLES` |
| 数据 | 全收益代码**不得出现在 `index_daily`**（测试断言） |
| 访问 | 正式回测只查 `index_daily`，读不到 `tr_*` |

### 3.2 隔离证明

`assert_isolated()` 检查：

1. `tr_*` 表全部在 `TR_TABLES` 白名单内；
2. 12 个全收益代码在 `index_daily` 中行数为 **0**。

**注意**：`trade_calendar` 因前缀 `tr` 曾被误匹配，已改用白名单而非 `like 'tr_%'`。

### 3.3 导入批次自证

`tr_ingest_runs` 记录：

- `index_daily_before` / `index_daily_after`（行数）
- `index_daily_fingerprint_before` / `_after`（内容 SHA256）

**两者必须完全一致。**

---

## 4. 幂等与事务

| 机制 | 实现 |
| --- | --- |
| 行级幂等 | 主键 `(tr_code, trade_date)` + `insert or ignore` |
| 批次幂等 | `batch_key` 唯一，重复执行复用同一 `run_id` |
| 快照幂等 | 同一 `(tr_code, run_id)` 先删后插 |
| 映射幂等 | 同一 `tr_code` 先删后插 |
| 事务原子性 | 使用 `get_connection()` 上下文，异常自动回滚 |
| 重标记 | `relabel_existing_rows()` 只改质量标记，**不动原始数值** |

---

## 5. 异常行处理策略

**三类异常行全部保留原值，只加标记**：

| 异常 | 标记 | 保留内容 |
| --- | --- | --- |
| `20040101` 合成行（12 行） | `suspected_synthetic` | 原始 close（如 1000.0） |
| `2018-06-18` 疑似休市（8 行） | `suspected_market_closed_placeholder` | 原始 close |
| `H20184` `2013-06-28` 零值（1 行） | `invalid_value` | `close = 0.0` |

**不得删除、不得插值、不得修正。**

---

## 6. 状态不升级保证

| 状态 | 本阶段值 | 保证 |
| --- | ---: | --- |
| `raw_data_layer_ingest_candidate` | 12 | 审计结论 |
| `validated_series_candidate` | **0** | 不得升级 |
| `proxy_qualified_series_candidate` | **0** | 不得升级 |
| `formal_series_admitted` | **0** | 不得升级 |

**原始数据层建设完成 ≠ 序列验证完成。**

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

