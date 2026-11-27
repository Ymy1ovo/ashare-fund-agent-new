# 阶段3B-6.2.3.1.0.3 修正报告：连续性证据等级与准入统计最终一致性

> ⚠️ **本报告的 `proxy_qualified_series_candidate=1` 已被 3B-6.2.3.1.0.3.1 修正为 0**。
>
> 原因：代理验证准入原缺少「真实历史起点已知」条件，与报告定义不一致。
> `399997CNY02` 保留 `verified_against_proxy_calendar` 等级，
> 但因 `real_history_start=unknown` 不再满足代理验证。
>
> **请以 `reports/phase3B6_2_3_1_0_3_1_fix_report.md` 为准。**
>
> 本报告保留作为历史记录，原文未删除。

**基线 HEAD**：`03f72f061ce16bd1f8d21c8847d7dca3a2052194`

---

## 0. 核心问题与修正

| 项 | 3B-6.2.3.1.0.1 | 3B-6.2.3.1.0.2 | **本轮（最终）** |
| --- | ---: | ---: | ---: |
| 股票 `continuity_verified` | **9** | 1 | **0（官方）/ 1（代理）** |
| 股票 `has_unresolved_suspicion` | — | 8 | **8** |
| `validated_series_candidate` | **8** | 未定义 | **0** |
| `proxy_qualified_series_candidate` | 未定义 | 未定义 | **1** |
| `formal_series_admitted` | 0 | 0 | **0** |

**以 3B-6.2.3.1.0.2 的逐候选证据为准**，010 的 `continuity_verified=9` 已作废。

---

## 1. 五态连续性证据等级

| 等级 | 定义 | 允许 validated | 本轮数量 |
| --- | --- | --- | ---: |
| `verified_official_calendar` | 相对**官方指数发布日历**验证连续 | **是** | **0** |
| `verified_against_proxy_calendar` | 相对**项目 A 股交易日历代理**验证；**不是官方日历** | 否 | **1** |
| `has_unresolved_suspicion` | 存在疑似休市占位行但无官方日历证据 | 否 | **8** |
| `has_issues` | 存在无法解释的日历外日期 | 否 | **0** |
| `unknown` | 适用市场日历未取得 | 否 | **3** |

**关键约束：只有 `verified_official_calendar` 允许 `validated_series_candidate`。**

本轮**没有任何官方交易日历**，因此 `verified_official_calendar = 0`。

---

## 2. 逐候选最终状态

| 候选 | 分组 | 连续性等级 | 原始层 | 已验证 | **代理验证** | 正式准入 |
| --- | --- | --- | --- | --- | --- | --- |
| `H00300` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H00905` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H00906` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H00016` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H20539` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| **`399997CNY02`** | stock | **`verified_against_proxy_calendar`** | ✅ | ❌ | **✅** | ❌ |
| `H20184` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H00942` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H00922` | stock | `has_unresolved_suspicion` | ✅ | ❌ | ❌ | ❌ |
| `H00012` | bond | `unknown` | ✅ | ❌ | ❌ | ❌ |
| `N00012` | bond | `unknown` | ✅ | ❌ | ❌ | ❌ |
| `H20930` | hk | `unknown` | ✅ | ❌ | ❌ | ❌ |
| **合计** | — | — | **12** | **0** | **1** | **0** |

---

## 3. 四个独立状态

| 状态 | 判定规则 | 本轮 |
| --- | --- | ---: |
| **A. `raw_data_layer_ingest_candidate`** | 官方身份 + 历史接口可用 | **12 / 12** |
| **B. `validated_series_candidate`** | 身份+口径+映射+质量+覆盖+**连续性达官方等级**+真实起点已知 | **0 / 12** |
| **B'. `proxy_qualified_series_candidate`** | 同上，但连续性只需达**代理**等级 | **1 / 12** |
| **C. `formal_series_admitted`** | B + 历史时点可用 | **0 / 12** |

### 3.1 为什么 `validated` 是 0 而不是 1

`399997CNY02` 虽然覆盖与连续性在代理日历下通过，但：

| 阻断项 | 原因 |
| --- | --- |
| 连续性等级 | `verified_against_proxy_calendar`，**非官方日历** |
| 真实历史起点 | `unknown`（无候选自身对照证据） |
| 时点可用性 | `unknown` |

**只有 `verified_official_calendar` 才允许 `validated`——本轮没有官方日历，故为 0。**

### 3.2 `proxy_qualified` 是独立统计，不冒充官方

`proxy_qualified_series_candidate = 1`（`399997CNY02`）明确标注：

> **仅代理日历验证**，不得称官方验证

---

## 4. 三方 JSON 已一致

| 文件 | 连续性字段 | 状态 |
| --- | --- | --- |
| `phase3B6_2_3_1_0_1_audit.json` | `continuity_status`（五态） | **已同步** |
| `phase3B6_2_3_1_0_2_audit.json` | `continuity_level`（五态） | **已对齐** |
| `phase3B6_2_3_1_0_3_audit.json` | `continuity_level`（五态） | **基准** |

**12 / 12 候选在三份 JSON 中完全一致。**

### 4.1 原始记录保留

| 文件 | 保留内容 |
| --- | --- |
| 010 JSON | `_superseded_snapshot`（原始 totals 与 stock group）+ 每候选 `_original_continuity_status` |
| 020 JSON | `_superseded_snapshot` + 每候选 `continuity_status_original` |
| 010 报告 | 修正横幅 + 「以 3.0.3 为准」 |
| 020 报告 | 修正横幅 + 「以 3.0.3 为准」 |

**旧报告未删除，均保留修订记录。**

---

## 5. 冲突解决明细

| 候选 | 010 原始 | 020 | **最终（030）** |
| --- | --- | --- | --- |
| `H00300` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H00905` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H00906` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H00016` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H20539` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H20184` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H00942` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `H00922` | `verified` | `has_unresolved_suspicion` | **`has_unresolved_suspicion`** |
| `399997CNY02` | `verified` | `verified` | **`verified_against_proxy_calendar`** |

**8 条实质冲突已解决**；`399997CNY02` 属命名细化（四态 `verified` → 五态 `verified_against_proxy_calendar`）。

---

## 6. 数据库安全

| 项 | 值 |
| --- | --- |
| 路径 | `D:\ymy\jj-agent\data\fund_agent.db` |
| SHA256（前/后） | `1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873` |
| 是否变化 | **未变** |
| `index_daily` 总行数 | 50,603（未变） |
| 全收益代码在库内 | **全部 0** |
| `integrity_check` | ok |
| `foreign_key_check` | 0 |

### 原始证据完整性

| 项 | 结果 |
| --- | --- |
| 3B-6.2.3.1.0 原始证据 | SHA256 全部一致 |
| 3B-6.2.3.0.4 对照文件 | SHA256 全部一致 |
| 是否重新下载 | **否** |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

