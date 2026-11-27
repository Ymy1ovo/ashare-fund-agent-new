# 阶段3B-6.2.3.1.1 数据导入审计与数据库安全核验报告

> **只建原始归档层。不建设正式全收益序列，不开放回测。**

**基线 HEAD**：`3aae887da4a82ba77481c0efdb2f32c11feef618`

---

## 1. 导入结果

| 项 | 值 |
| --- | ---: |
| 候选注册 | **12** |
| 原始行情插入 | **55,942 行** |
| 原始行情跳过（幂等） | 55,942（第二次执行） |
| 证据登记 | **34** |
| 质量快照 | **12** |
| 映射记录 | **12** |

### 表行数

| 表 | 行数 |
| --- | ---: |
| `tr_candidate_master` | 12 |
| `tr_evidence_files` | 34 |
| `tr_ingest_runs` | 1 |
| `tr_index_daily_raw` | **55,942** |
| `tr_candidate_quality` | 12 |
| `tr_price_index_mapping` | 12 |

---

## 2. 逐候选行数

| 候选 | 行数 | 合成行 | 疑似休市 | 无效值 |
| --- | ---: | ---: | ---: | ---: |
| `399997CNY02` | 4,349 | 1 | 0 | 0 |
| `H00012` | 3,376 | 1 | 0 | 0 |
| `H00016` | 5,563 | 1 | 1 | 0 |
| `H00300` | 5,321 | 1 | 1 | 0 |
| `H00905` | 5,321 | 1 | 1 | 0 |
| `H00906` | 5,321 | 1 | 1 | 0 |
| `H00922` | 5,321 | 1 | 1 | 0 |
| `H00942` | 5,321 | 1 | 1 | 0 |
| `H20184` | 5,320 | 1 | 1 | **1** |
| `H20539` | 4,350 | 1 | 1 | 0 |
| `H20930` | 3,003 | 1 | 0 | 0 |
| `N00012` | 3,376 | 1 | 0 | 0 |
| **合计** | **55,942** | **12** | **8** | **1** |

---

## 3. 质量状态分布

| 状态 | 行数 | 占比 |
| --- | ---: | ---: |
| `normal_unverified` | 55,921 | 99.96% |
| `suspected_synthetic` | **12** | 0.02% |
| `suspected_market_closed_placeholder` | **8** | 0.01% |
| `invalid_value` | **1** | 0.00% |
| **`verified`** | **0** | — |

**没有任何一行被标记为 `verified`。**

---

## 4. 异常行保留验证

### 4.1 `20040101` 疑似合成行（12 行，全部保留）

| 候选 | 原始 close | 标记 |
| --- | ---: | --- |
| `H00300` `H00905` `H00906` `H00922` `H00942` `H20539` `399997CNY02` | 1,000.0 | `suspected_synthetic` |
| `H00012` `N00012` | 100.0 | `suspected_synthetic` |
| `H00016` | 1,011.35 | `suspected_synthetic` |
| `H20184` | 994.47 | `suspected_synthetic` |
| `H20930` | 3,000.0 | `suspected_synthetic` |

### 4.2 `2018-06-18` 疑似休市占位（8 行，全部保留）

| 候选 | close | 标记 |
| --- | ---: | --- |
| `H00300` | 4,614.35 | `suspected_market_closed_placeholder` |
| `H00905` | 6,060.55 | 同 |
| `H00906` | 4,906.05 | 同 |
| `H00016` | 3,616.55 | 同 |
| `H20539` | 8,059.48 | 同 |
| `H20184` | 3,422.74 | 同 |
| `H00942` | 10,721.51 | 同 |
| `H00922` | 6,475.67 | 同 |

**`399997CNY02` 无该日记录，`H20930` 该日未判为疑似（港股无 A 股日历证据）。**

### 4.3 `H20184` 零值（1 行，原值保留）

| 项 | 值 |
| --- | --- |
| 日期 | `2013-06-28` |
| close | **`0.0`（原样保留，未修正）** |
| 标记 | `invalid_value` |
| 说明 | `close 非正值：0.0` |

---

## 5. 数据隔离验证

| 检查 | 结果 |
| --- | --- |
| `tr_*` 表全部在白名单内 | ✅ 6/6 |
| 12 个全收益代码在 `index_daily` 行数 | **全部 0** |
| `index_daily` 行数（前 → 后） | **50,603 → 50,603** |
| `index_daily` 内容指纹（前 → 后） | **完全一致** |
| 正式引擎能否读到全收益数据 | **否** |

**导入批次自证**：

| 字段 | 值 |
| --- | --- |
| `index_daily_before` | 50,603 |
| `index_daily_after` | 50,603 |
| `fingerprint_before` == `fingerprint_after` | **✅** |
| `status` | `success` |

---

## 6. 证据可追溯性

| 项 | 结果 |
| --- | --- |
| 证据文件总数 | **34** |
| SHA256 真实复核通过 | **34 / 34** |
| 行情行缺证据引用 | **0** |
| 行引用 SHA256 与证据表一致 | **✅** |

**每行行情都可通过 `evidence_relative_path` + `evidence_sha256` 追溯到原始文件。**

---

## 7. 连续性状态一致性

| 等级 | 数据库 | 审计 JSON | 一致 |
| --- | ---: | ---: | --- |
| `verified_official_calendar` | 0 | 0 | ✅ |
| `verified_against_proxy_calendar` | 1 | 1 | ✅ |
| `has_unresolved_suspicion` | 8 | 8 | ✅ |
| `has_issues` | 0 | 0 | ✅ |
| `unknown` | 3 | 3 | ✅ |

---

## 8. 准入状态未升级

| 状态 | 值 |
| --- | ---: |
| `raw_data_layer_ingest_candidate` | **12** |
| `validated_series_candidate` | **0** |
| `proxy_qualified_series_candidate` | **0** |
| `formal_series_admitted` | **0** |

---

## 9. 数据库安全核验

| 项 | 值 |
| --- | --- |
| 备份文件 | `data/backups/fund_agent_before_3b6_2_3_1_1.db`（334,036,992 字节） |
| 实施前 SHA256 | `1671e4037cd265a2dead8b78d43614189a782385ca450ac6c2de3c4ff36ee873` |
| 实施后 SHA256 | `1c6327d9b7fb1b504fac55684fa62dc0984da13d51256747dfbb5fe6b54d2e62` |
| 变化原因 | **新增 6 张 `tr_*` 表**（预期） |
| `index_daily` 行数 | 50,603（**未变**） |
| `index_daily` 内容指纹 | **未变** |
| `index_master` 行数 | 10（未变） |
| `fund_master` | 120（未变） |
| `fund_nav_daily` | 245,656（未变） |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

**结论：仅新增独立表，现有行情与基金数据完全未变。**

---

## 10. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

