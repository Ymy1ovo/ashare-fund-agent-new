# 阶段3B-6.2.3.0.4 设计：10 条 2004-01-01 suspect 占位记录来源溯源审计

> **严格只读审计。本轮只查明事实，不负责修复。**

**基线 HEAD**：`759bcabaae6efee26abfbe056e4978d3d16e15c6`
**正式数据库**：`D:\ymy\jj-agent\data\fund_agent.db`

---

## 1. 审计对象

| 项 | 值 |
| --- | --- |
| 表 | `index_daily` |
| 筛选 | `trade_date = '2004-01-01'` |
| 预期条数 | **10** |
| 指数 | `000012` `000016` `000300` `000905` `000906` `000922` `000942` `399997` `930930` `H30184` |

**前置硬约束**：若实际条数 ≠ 10，立即停止并报告，不得擅自扩大或缩小范围。
（脚本中以 `RuntimeError` 强制拦截，见 `audit()` 首段。）

---

## 2. 审计设计

### 2.1 逐条还原记录来源

| 步骤 | 方法 |
| --- | --- |
| 读取全字段 | `pragma table_info` + `select *` |
| 追溯 `run_id` | 关联 `index_ingest_runs` 读取采集批次 |
| 追溯 `source` | 定位 `app/fund/index_ingest.py` 的常量与接口调用 |
| 原始响应是否存在 | 真实请求官方接口并保存原始响应 + SHA256 |
| 是否为真实接口响应 | **对照实验**：从 `20040101` 请求 vs 从 `20040102` 请求 |

### 2.2 关键判据（不靠数值巧合）

**不能仅凭 close 恰好等于 1000/3000 就断定是占位数据。** 本设计采用三重交叉验证：

| 判据 | 含义 |
| --- | --- |
| **A. 起始日依赖** | 从 `20040101` 请求时首行为 `2004-01-01`；改从 `20040102` 请求后该日**消失** |
| **B. 首行重复** | 该行 close 与第二行 close **完全相同** |
| **C. 零成交** | `tradingVol` 与 `tradingValue` 为 0 或 null |

三条同时成立 → 官方接口的**起始日合成行**，而非真实交易日行情。

### 2.3 逐指数官方资料核验

| 查证项 | 来源 |
| --- | --- |
| 官方全称 | `csindex-home/indexInfo/index-basic-info/<code>` |
| 官方基日 `basicDate` | 同上 |
| 官方基点 `basicIndex` | 同上 |
| 官方发布日 `publishDate` | 同上 |
| **API 响应首日** | `csindex-home/perf/index-perf` 全量返回首行 |
| **真实最早历史行情日期** | 需独立证据；无则 `unknown` |
| `2004-01-01` 是否为有效交易日 | 项目 `trade_calendar`（**A股代理，非官方日历**） |

### 2.4 内部生成逻辑排查

在 `*.py` / `*.sql` 中搜索 9 个关键值，**区分生产代码与测试/报告**：

`2004-01-01`、`20040101`、`1000.0`、`3000.0`、`994.47`、`1204.61`、`1028.64`、`1011.35`、`99.22`

**因果判定原则**：代码中出现相同数字 ≠ 该代码生成了该记录。
必须找到可建立因果联系的证据（如采集起始日参数、基线标记逻辑）。

---

## 3. 证据分级

| 等级 | 定义 |
| --- | --- |
| **L1** | 官方原始文件、官方接口原始响应 |
| **L2** | 可追溯的权威文件或官方公告 |
| **L3** | 第三方资料、项目内部间接线索 |
| **insufficient** | 缺乏足够证据 |

**不得将 L3 描述为官方确认。**

---

## 4. 每条记录的输出字段

| 字段 | 说明 |
| --- | --- |
| `source_origin` | 官方接口 / 项目内部生成 / 第三方 / unknown |
| `official_base_date` | 官方基日及证据 |
| `official_publish_date` | 官方发布日期及证据 |
| `earliest_response_date` | 本次接口响应的**第一条**日期（非真实历史起点） |
| `actual_earliest_historical_quote_date` | 真实最早历史行情日期；无独立证据时为 `unknown` |
| `is_valid_trading_day` | 2004-01-01 是否有效交易日 |
| `base_value_confusion` | 是否混淆基点值与行情 |
| `placeholder_evidence` | 是否有证据证明人为占位 |
| `historical_availability` | 能否证明历史时点可用 |
| `evidence_grade` | L1 / L2 / L3 / insufficient |
| `final_conclusion` | 最终判断 |
| `recommended_action` | 保留 / 待核实 / 建议修复 / 建议删除（本轮不执行） |

---

## 5. 数据库不变性设计

任务开始与结束各采集一次完整快照并**逐项比对**：

| 项 | 内容 |
| --- | --- |
| 数据库完整 SHA256 | `file_sha256()` |
| 文件大小 | `os.path.getsize` |
| `index_daily` 总行数 | 50,603 |
| 10 条目标记录完整字段 | 含**行级内容指纹**（全字段哈希） |
| 其他 9 个指数指纹 | `(trade_date, close)` 序列哈希 |
| `integrity_check` | 必须 `ok` |
| `foreign_key_check` | 必须 0 |

**任一项变化视为本轮失败，必须停止。**

---

## 6. 安全边界

| 禁止 | 落实 |
| --- | --- |
| 修改正式数据库 | `mode=ro` 只读连接 |
| 删除/更新任何 `index_daily` 记录 | 无 `UPDATE`/`DELETE` |
| 修改 `quality_status` / `quality_note` | 未执行 |
| 修改 Schema | 未执行 |
| 重跑 H30184 修复 | 未执行（测试断言其结果未变） |
| 接入全收益数据 | 未执行 |
| 修改收益计算 / 基准映射 | 未执行 |
| 开放回测或正式排名 | 未执行 |
| 为通过测试而改数据或放宽测试 | 未执行 |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

