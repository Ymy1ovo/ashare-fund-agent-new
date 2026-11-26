# 阶段3B-6.2.3.0.3 设计：H30184 历史零值异常官方复核与最小修复

> **本轮允许修改正式数据库，但严格限定为一条记录。**

**基线 HEAD**：`8fdc51df2c9cd31f321041f9ff3dfc3d8d6f5de3`
**正式数据库**：`D:\ymy\jj-agent\data\fund_agent.db`

---

## 1. 问题定义

| 字段 | 异常值 |
| --- | --- |
| `index_code` | `H30184`（中证全指半导体产品与设备指数） |
| `trade_date` | `2013-06-28` |
| `close` | **0.0** |
| `open` / `high` / `low` | **NULL** |
| `quality_status` | **valid**（标记错误） |

**风险**：该记录进入收益序列会在 `2013-06-28` 产生 **-100% 假跌幅**，污染后续全部累计收益与回测结果。

**范围限定**：本轮**只处理这一条**，不扩展到其他指数。

---

## 2. 第一步：官方证据复核设计

### 2.1 必须查证的 5 项

| # | 查证项 | 方法 |
| ---: | --- | --- |
| 1 | 该日是否存在官方公布点位 | 中证指数官网行情接口单日查询 |
| 2 | 该日是否处于实际发布/回溯区间 | 官方基本信息接口 `publishDate` / `basicDate` |
| 3 | 前后交易日是否连续 | 官方区间查询 `20130624~20130703` |
| 4 | 官方返回是缺失、0 值还是有效点位 | 原始响应逐字段比对 |
| 5 | 是否存在代码/回溯/默认值/转换错误 | 与同期 `000300` 对照 |

### 2.2 证据保存要求

| 项 | 要求 |
| --- | --- |
| 官方请求 URL | 完整记录 |
| 原始响应 | 原样落盘，不加工 |
| 请求时间 | ISO 8601 |
| 官方指数名称 | 从响应提取 |
| 日期与收盘点位 | 从响应提取 |
| 原始证据文件 SHA256 | 完整 64 位 |
| 证据等级 | L1（官方发布机构原始响应） |

### 2.3 明确禁止的推断方式

- ❌ 用相邻日期插值
- ❌ 用收益率反推真实点位
- ❌ 凭经验填补
- ❌ 按代码/名称规律推测

---

## 3. 第二步：最小修复方案设计

### 3.1 三种情况的判定逻辑

| 情况 | 触发条件 | 允许动作 |
| --- | --- | --- |
| **A** | 官方确认真实收盘点位（正值） | 只修复 `close`；**不得补造 OHLC** |
| **B** | 官方无法确认 | 标记 `suspect`；**保留原值** |
| **C** | 发现更复杂问题 | **停止修改**，只提交证据 |

### 3.2 代码层面的强制约束

```python
def validate_decision(decision, official):
    if decision == "A":
        close = official.get("official_close")
        if close is None or close <= 0:
            raise ValueError("情况 A 需要官方确认的真实收盘点位，当前证据不足")
    elif decision in ("B", "C"):
        if official.get("official_close") not in (None, 0.0):
            raise ValueError("官方已提供正值收盘，不应按 B/C 处理")
```

**这一层保证：证据不足时无法走 A 路径，官方给了正值时也无法静默走 B 路径。**

### 3.3 本轮实际决策

**决策 = B**，理由见 repair_report 的「官方确认事实」段。

---

## 4. 第三步：数据库安全设计

### 4.1 修改前

| 步骤 | 实现 |
| --- | --- |
| 1. SQLite 一致性备份 | `sqlite3.Connection.backup()` 到 `fund_agent_backup_3b6_2_3_0_3_20261126.db` |
| 2. 记录 64 位 SHA256 | `file_sha256()` |
| 3. 记录目标记录全部字段 | `read_target()` 返回 `pragma table_info` 全字段 |
| 4. 记录总行数 | 50,603 |
| 5. `integrity_check` / `foreign_key_check` | ok / 0 |

### 4.2 修改时

| 约束 | 实现 |
| --- | --- |
| 只改目标记录 | `where index_code=? and trade_date=?` 双条件 |
| 使用事务 | `with conn:` |
| 影响行数必须恰好 1 | `if affected != 1: raise RuntimeError` → 自动回滚 |
| 不允许删除其他数据 | 只执行 `UPDATE`，无 `DELETE` |

### 4.3 修改后

| 核对项 | 实现 |
| --- | --- |
| 再次计算 SHA256 | `file_sha256()` |
| `integrity_check` / `foreign_key_check` | 重新执行 |
| 核对目标记录 | `read_target()` |
| 核对总行数 | 必须仍为 50,603 |
| **其他 9 个指数指纹对比** | `index_fingerprints()` 逐指数 `(trade_date, close)` 序列哈希 |

---

## 5. 明确禁止事项

| # | 禁止 |
| ---: | --- |
| 1 | 修改 10 条 `2004-01-01` suspect 占位记录 |
| 2 | 修改其他指数行情 |
| 3 | 修改数据库 Schema |
| 4 | 接入全收益指数行情 |
| 5 | 修改基金基准映射 |
| 6 | 修改基金合同或基金净值 |
| 7 | 修改收益计算公式 |
| 8 | 开放回测或正式排名 |
| 9 | 开始 3B-6.2.3.1 |

---

## 6. 测试设计

| # | 测试目标 | 对应测试 |
| ---: | --- | --- |
| 1 | 目标异常记录准确识别 | `test_target_anomaly_identified` |
| 2 | 证据不足不允许填补 | `test_insufficient_evidence_blocks_repair` |
| 3 | 证据充分时只修目标记录 | `test_apply_repair_dry_run_does_not_write` + `test_target_marked_suspect` |
| 4 | OHLC 缺失不得补造 | `test_ohlc_not_fabricated` |
| 5 | 其他指数不受影响 | `test_other_indexes_unaffected` |
| 6 | 10 条占位记录不受影响 | `test_placeholder_rows_intact` |
| 7 | 事务失败能回滚 | `test_transaction_rollback_on_wrong_scope` |
| 8 | 修改前后完整性正常 | `test_integrity_and_fk_ok` |
| 9 | 异常记录不再进入有效收益 | `test_anomaly_excluded_from_valid_series` |
| 10 | 报告记录证据等级与依据 | `test_repair_report_exists` |

---

## 7. 门禁

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **true** |
| `ready_for_backtest` | **false** |
| `ready_for_formal_ranking` | **false** |
| `ready_for_3b6_2_3_1_series_build` | **false** |

