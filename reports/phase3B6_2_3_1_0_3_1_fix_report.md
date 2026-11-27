# 阶段3B-6.2.3.1.0.3.1 修正报告：代理验证准入缺失真实历史起点条件

> **只读修正。不重新下载数据，不修改数据库，不开始正式序列建设。**

**基线 HEAD**：`586cd83b5a86728c10556079ac69fde4c66b3007`

---

## 0. 问题

`compute_admission()` 中两个准入条件的判据**不对称**：

| 准入状态 | 修正前条件 | 问题 |
| --- | --- | --- |
| `validated_series_candidate` | 身份+口径+映射+质量+覆盖+**官方日历连续**+**真实起点已知** | 正确 |
| `proxy_qualified_series_candidate` | 身份+口径+映射+质量+覆盖+代理日历连续 | **缺少「真实起点已知」** |

这与报告定义不一致。报告明确规定：

> 代理验证候选与已验证候选使用相同的身份、口径、映射、质量、覆盖和历史起点条件，
> 仅把连续性等级要求放宽为代理日历验证。

---

## 1. 修正内容

```python
# 修正前
proxy_qualified = bool(
    identity and basis and mapping and quality and coverage
    and cont_level in ("verified_official_calendar",
                       "verified_against_proxy_calendar"))

# 修正后
proxy_qualified = bool(
    identity and basis and mapping and quality and coverage
    and cont_level in ("verified_official_calendar",
                       "verified_against_proxy_calendar")
    and real_start_known)      # ← 新增
```

同时新增 `proxy_blockers` 字段，独立记录代理验证的阻断原因。

---

## 2. 预期结果已达成

| 状态 | 修正前 | **修正后** |
| --- | ---: | ---: |
| `raw_data_layer_ingest_candidate` | 12 | **12** |
| `validated_series_candidate` | 0 | **0** |
| **`proxy_qualified_series_candidate`** | **1** | **0** |
| `formal_series_admitted` | 0 | **0** |

### 连续性五态未变

| 等级 | 数量 |
| --- | ---: |
| `verified_official_calendar` | 0 |
| **`verified_against_proxy_calendar`** | **1** |
| `has_unresolved_suspicion` | 8 |
| `has_issues` | 0 |
| `unknown` | 3 |

**连续性证据等级保持不变，只是准入判定更严格。**

---

## 3. `399997CNY02` 的完整状态

| 项 | 值 | 说明 |
| --- | --- | --- |
| `continuity_level` | **`verified_against_proxy_calendar`** | **保留** |
| 覆盖状态 | `verified` | **保留**（相对 A 股代理日历） |
| 连续性原始状态 | `verified` | **保留** |
| `calendar_is_official` | `false` | 代理日历 |
| `raw_data_layer_ingest_candidate` | **true** | 可进原始隔离层 |
| `validated_series_candidate` | **false** | — |
| **`proxy_qualified_series_candidate`** | **false** | **本轮修正** |
| `formal_series_admitted` | **false** | — |

### 阻断原因

| 字段 | 内容 |
| --- | --- |
| `blockers` | `["连续性=verified_against_proxy_calendar", "真实历史起点未知", "时点可用性"]` |
| **`proxy_blockers`** | **`["真实历史起点未知"]`** |

### 结论

> 可进原始隔离层；连续性已达代理等级，但**代理验证候选仍未通过**；不得正式准入

**代理日历审计结果完整保留，未删除、未改写。**

---

## 4. 为什么真实起点是关键条件

`399997CNY02` 的 `real_history_start` 为 `unknown`，原因：

| 事实 | 说明 |
| --- | --- |
| 首行 `20040101` | 是请求起始日合成行（`strong_inference`） |
| 候选自身对照证据 | **无**（12/12 候选均无） |
| 第二行 `20081231` | **未被确认为真实历史起点** |

**如果不知道序列从哪天开始是真实的，就无法判定「覆盖」和「连续性」是否有意义。**
代理日历下的「无缺失」可能只是因为起点取错了。

---

## 5. 数据库安全

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
| 官方原始证据（`basic_`/`hist_`/`csindex_`） | SHA256 全部一致 |
| 是否重新下载 | **否** |

---

## 6. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

