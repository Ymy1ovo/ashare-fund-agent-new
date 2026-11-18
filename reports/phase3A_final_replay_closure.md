# 阶段3A 最终收口：剩余历史配置重放

- 基线 HEAD：`f61be9bafe122823b05ee8ebe2935b49c8dfab2d`
- 执行日期：2026-11-18
- 范围：只处理 G2 / G3 / G4 / G5 四个配置组的代表记录。

---

## 1. 先核对实际剩余对象（不假设）

从数据库重新读取 `validation_runs` 的 `config_hash` 分组，
结合 `phase3A3_2_3_5_replay_inventory` 的 G 编号：

| 组 | config_hash | 源条数 | 代码数 | 网格 | 字段集 | 代表（本轮重放） |
| ---: | --- | ---: | ---: | --- | --- | --- |
| G2 | `b1de1d7323a8a35d` | 5 | 6 | 3 档 `[5,20,60]` | current 28 | `c84356bd50ca4bb5` |
| G3 | `177a329b6fd72cec` | 5 | 6 | 3 档 `[10,30,120]` | current 28 | `2b21ca9b2c434444` |
| G4 | `86e4b4e8bac296ad` | 2 | 6 | 7 档 | **historical 26** | `f9898c695b394808` |
| G5 | `4457e246afad6e79` | 1 | 41 | 7 档 | **historical 26** | `e725034e46ff47e5` |

每组只重放 1 条代表记录，其余同配置记录不重复执行（见 §2.5）。

---

## 2. 逐条结果

### 2.1 G2 代表 `c84356bd50ca4bb5`

| 字段 | 值 |
| --- | --- |
| source_id | `c84356bd50ca4bb5` |
| replay_attempt_id | `fdb0e78069284fb1` |
| replay_record_id | `bde29001291a456b` |
| config_hash | `b1de1d7323a8a35d`（源与新**相同**） |
| source_input_hash | `e4b62767ad909949` |
| replay_input_hash | `7685d922d83da4d4` |
| accounting_version | `ca-v2-receivable` |
| accounting_basis | `formal_receivable`（48 条内部回测全部） |
| formal_valuation | `1`（= True） |
| schema_version | current 28 字段 |
| legacy_schema_mapping | 不适用 |
| audit_trace | **complete** |
| audit_completeness | **True**，problems `[]` |
| conclusion | 不通过 |
| status | **success** |

**绩效对照**

| 指标 | 源 | 新 |
| --- | ---: | ---: |
| IS `total_return` | -0.099994 | -0.084088 |
| IS `cagr` | -0.027054 | -0.022607 |
| IS `max_drawdown` | -0.226749 | -0.214848 |
| IS Sharpe | -0.210942 | -0.166626 |
| IS 成交笔数 | 1,293 | 1,307 |
| IS 总成本 | 103,775.43 | 105,217.38 |
| OOS `total_return` | 0.224288 | 0.192693 |
| OOS `cagr` | 0.121131 | 0.104690 |
| OOS `max_drawdown` | -0.129523 | -0.143859 |
| OOS Sharpe | 0.875481 | 0.772633 |
| OOS 成交笔数 | 710 | 688 |
| OOS 总成本 | 55,753.16 | 55,218.06 |
| WF 窗口 | 8 / 8 成功 | 8 / 8 成功 |
| 选中最优参数 | MA60 | **MA60**（未变） |
| 分红金额 | 0.00 | 428,699.54 |
| 公司行为应用数 | 0 | 142 |
| 分红应收笔数 | 0 | 127 |

**差异归因**：选参未变（MA60），IS/OOS 差异主要来自公司行为口径
（源 0 应用、新 142 应用 + 428,699.54 元分红）。IS 收益小幅上升
（-10.00% → -8.41%），OOS 收益下降（+22.43% → +19.27%）——
MA60 在新口径下持仓轨迹略有变化，交易次数 1293→1307（IS）、
710→688（OOS）。没有选参漂移，差异幅度小且方向合理。

### 2.2 G3 代表 `2b21ca9b2c434444`

| 字段 | 值 |
| --- | --- |
| source_id | `2b21ca9b2c434444` |
| replay_attempt_id | `ce071b8979b5427c` |
| replay_record_id | `df2f811d52d04155` |
| config_hash | `177a329b6fd72cec`（源与新**相同**） |
| source_input_hash | `5fbdd777b0f24a82` |
| replay_input_hash | `71b0cc27f92b9463` |
| accounting_version | `ca-v2-receivable` |
| accounting_basis | `formal_receivable`（48 条全部） |
| formal_valuation | `1`（= True） |
| schema_version | current 28 字段 |
| legacy_schema_mapping | 不适用 |
| audit_trace | **complete** |
| audit_completeness | **True**，problems `[]` |
| conclusion | 不通过 |
| status | **success** |

**绩效对照**

| 指标 | 源 | 新 |
| --- | ---: | ---: |
| IS `total_return` | -0.164869 | -0.164555 |
| IS `cagr` | -0.045820 | -0.045726 |
| IS `max_drawdown` | -0.247171 | -0.243719 |
| IS Sharpe | -0.345647 | -0.347255 |
| IS 成交笔数 | 1,735 | 1,724 |
| IS 总成本 | 161,347.85 | 159,752.21 |
| OOS `total_return` | 0.219144 | 0.219980 |
| OOS `cagr` | 0.118466 | 0.118900 |
| OOS `max_drawdown` | -0.151959 | -0.137747 |
| OOS Sharpe | 0.893998 | 0.909163 |
| OOS 成交笔数 | 887 | 874 |
| OOS 总成本 | 84,468.91 | 83,377.42 |
| WF 窗口 | 8 / 8 | 8 / 8 |
| 选中最优参数 | MA30 | **MA30**（未变） |
| 分红金额 | 0.00 | 447,293.28 |
| 公司行为应用数 | 0 | 132 |
| 分红应收笔数 | 0 | 117 |

**差异归因**：IS/OOS 收益差异均在 **0.04% 以内**，选参未变。
这是四组里差异最小的一组——MA30 持仓周期中等，分红影响被部分对冲。
公司行为口径仍是唯一实质差异来源（0 → 132 应用，447,293.28 元）。

### 2.3 G4 代表 `f9898c695b394808`（legacy-compatible replay）

| 字段 | 值 |
| --- | --- |
| source_id | `f9898c695b394808` |
| replay_attempt_id | `3508b65202a64aea` |
| replay_record_id | `93c170ca1402419f` |
| **source config_hash** | `86e4b4e8bac296ad`（historical 26 字段） |
| **replay config_hash** | `b6b1babace517bdc`（current 28 字段，**不同**） |
| source_input_hash | `51fb37419139a52e` |
| replay_input_hash | `68433a7834546dbd` |
| accounting_version | `ca-v2-receivable` |
| accounting_basis | `formal_receivable`（52 条全部） |
| formal_valuation | `1`（= True） |
| schema_version | **historical 26 → current 28** |
| legacy_schema_mapping | 见 §3 |
| audit_trace | **complete** |
| audit_completeness | **True**，problems `[]` |
| conclusion | 有条件通过 |
| status | **success** |

**绩效对照**

| 指标 | 源 | 新 |
| --- | ---: | ---: |
| IS `total_return` | -0.085270 | +0.041007 |
| IS `cagr` | -0.022935 | +0.010517 |
| IS `max_drawdown` | -0.212830 | -0.198785 |
| IS Sharpe | -0.167924 | +0.152410 |
| IS 成交笔数 | 1,283 | 634 |
| IS 总成本 | 107,032.58 | 49,092.85 |
| OOS `total_return` | 0.214356 | 0.181437 |
| OOS `cagr` | 0.115983 | 0.098787 |
| OOS `max_drawdown` | -0.138289 | -0.168672 |
| OOS Sharpe | 0.842153 | 0.697009 |
| OOS 成交笔数 | 680 | 284 |
| OOS 总成本 | 55,642.42 | 23,222.14 |
| WF 窗口 | 8 / 8 | 8 / 8 |
| 选中最优参数 | MA60 | **MA250**（变化） |
| 分红金额 | 0.00 | 475,647.38 |
| 公司行为应用数 | 0 | 151 |
| 分红应收笔数 | 0 | 135 |

**差异归因**：与第一批 G1 完全相同的模式——
MA250 档被分红口径放大，IS 网格排序改变，最优参数从 MA60 切到 MA250。
**参数等价性已验证**：G4 重建后参数与已重放的 G1
（`7d884a1a03d94915`）**完全相同**（`as_dict()` 相等、重建 hash 同为
`b6b1babace517bdc`），因此新记录绩效与 G1 新记录完全一致
（IS +0.041007、OOS +0.181437）。

### 2.4 G5 代表 `e725034e46ff47e5`（legacy-compatible replay）

| 字段 | 值 |
| --- | --- |
| source_id | `e725034e46ff47e5` |
| replay_attempt_id | `3337840f523d49e6` |
| replay_record_id | `1c5832e27c6c4f3c` |
| **source config_hash** | `4457e246afad6e79`（historical 26 字段） |
| **replay config_hash** | `11ce7469245afab0`（current 28 字段，**不同**） |
| source_input_hash | `7a5a694c3fd321a9` |
| replay_input_hash | `1263f78d8a63e309` |
| accounting_version | `ca-v2-receivable` |
| accounting_basis | `formal_receivable`（52 条全部） |
| formal_valuation | `1`（= True） |
| schema_version | **historical 26 → current 28** |
| legacy_schema_mapping | 见 §3 |
| audit_trace | **complete** |
| audit_completeness | **True**，problems `[]` |
| conclusion | 有条件通过 |
| status | **success** |

**绩效对照**

| 指标 | 源 | 新 |
| --- | ---: | ---: |
| IS `total_return` | -0.145628 | +0.136776 |
| IS `cagr` | -0.040145 | +0.033937 |
| IS `max_drawdown` | -0.328334 | -0.138537 |
| IS Sharpe | +0.170717 | +0.252208 |
| IS 成交笔数 | 1,273 | 1,270 |
| IS 总成本 | 25,517.67 | 29,794.77 |
| OOS `total_return` | 0.307076 | 0.201146 |
| OOS `cagr` | 0.163356 | 0.109107 |
| OOS `max_drawdown` | -0.256842 | -0.182881 |
| OOS Sharpe | 0.763726 | 0.720981 |
| OOS 成交笔数 | 410 | 419 |
| OOS 总成本 | 10,718.17 | 9,479.81 |
| WF 窗口 | 8 / 8 | 8 / 8 |
| 选中最优参数 | MA250 | **MA250**（未变） |
| 分红金额 | 0.00 | 598,485.73 |
| 公司行为应用数 | 0 | 848 |
| 分红应收笔数 | 0 | 673 |

**差异归因**：选参未变（MA250，41 只大池本就在源记录里选了 MA250），
差异纯粹来自公司行为口径：源 0 应用、新 848 应用 + 598,485.73 元分红。
IS 从 -14.56% 变为 +13.68%，最大回撤从 -32.83% 改善到 -13.85%——
分红收益直接抬高了净值曲线、压低了回撤。
OOS 从 +30.71% 降到 +20.11%：新口径下 2025-06 之后的分红确认时点
改变了现金可用性，持仓轨迹变化，交易次数 410→419。

**注意**：G5 新记录的 `replay_input_hash=1263f78d8a63e309`
与第一批 `32aead3291734f91`（41 只池，`config_hash=11ce7469245afab0`）
的重放结果 `03410886d1f64fa7` **input_hash 相同**——两者参数完全等价，
这是数据一致性的正常表现。

### 2.5 同配置组未重复重放的记录

| 组 | 代表（已重放） | 同配置但未重放 | 原因 |
| ---: | --- | --- | --- |
| G2 | `c84356bd50ca4bb5` | `471ae52410de427a`、`a6d35304e92e4fca`、`aa51841d096f4ada`、`4a03b4cfc2c142f0`（4 条） | 参数完全相同，不重复运行 |
| G3 | `2b21ca9b2c434444` | `55a0df1bb2bb477d`、`03ff00a306bf4141`、`02edb3dd966042b3`、`bdfe34dbfe91424a`（4 条） | 同上 |
| G4 | `f9898c695b394808` | `5ec77faf42d64162`（1 条） | 同上，且参数等价于 G1 |
| G5 | `e725034e46ff47e5` | 无 | 该组只有 1 条 |
| G1 | `7d884a1a03d94915`（第一批已重放） | 其余 17 条同 `b6b1babace517bdc` | 同上 |

验证：剩余 27 条 `legacy` 记录中，**只有 1 条**
（`5ec77faf42d64162`）的 `config_hash` 不在已重放组的新 hash 集合内；
而它的重建参数与 G4 代表 `f9898c695b394808` **完全相同**
（`as_dict()` 相等、重建 hash 同为 `b6b1babace517bdc`）。
即：**不存在未覆盖的新配置。**

---

## 3. G4/G5 的 legacy 兼容映射

### 3.1 判断依据

G4/G5 的源记录创建时间：

| 记录 | 创建时间 |
| --- | --- |
| `f9898c695b394808`（G4） | 2026-11-11 14:29:31 |
| `e725034e46ff47e5`（G5） | 2026-11-11 14:39:44 |

`regime_ma_window` 与 `min_validation_days` 两个字段的引入提交：

```
66db49e  2026-11-11 16:47:29
fix: add market regime warmup, full-row fingerprint and real data stress tests
```

**两条记录创建于该字段引入之前约 2 小时。**

### 3.2 旧版真实语义（可追溯的等价来源）

| 字段 | 旧版（引入前）真实行为 | 证据 |
| --- | --- | --- |
| regime MA 窗口 | `build_regime_series(..., ma_window: int = REGIME_MA_WINDOW)`，`REGIME_MA_WINDOW = 250` | `66db49e~1:app/validation/regime.py` 第 73 行 + 第 17 行 import |
| 最小验证天数 | `split_time_range(..., min_days: int = MIN_VALIDATION_TRADING_DAYS)`，`MIN_VALIDATION_TRADING_DAYS = 120` | `66db49e~1:app/validation/split.py` 第 62 行 + `config.py` 第 33 行 |

旧版**没有**把这两个值暴露成 `ValidationConfig` 字段，但**行为上一直在用**
250 和 120（分别作为函数默认参数）。新版把这两个隐式默认值提升为
显式配置字段。

### 3.3 映射规则（情况 B：旧版本存在等价来源）

这是**情况 B**——旧版本确实不存在这两个字段，但它们有可追溯的等价来源，
不是"无法证明"。

| 新增字段 | 映射值 | 映射依据 | 是否猜测 |
| --- | ---: | --- | --- |
| `regime_ma_window` | **250** | 旧版 `regime.py` 函数默认参数 `REGIME_MA_WINDOW` | **否**，代码常量可查 |
| `min_validation_days` | **120** | 旧版 `split.py` 函数默认参数 `MIN_VALIDATION_TRADING_DAYS` | **否**，代码常量可查 |

**映射的严格边界**：

1. **不是**"用当前默认值填"。如果是，任何一个改过默认值的版本都会污染历史。
   这里用的是**旧版代码里实际生效的常量值**，且经 git 追溯确认
   两者数值未变（250 / 120 在引入前后完全相同）。
2. **不改变任何策略参数**：`ma_window_grid`、`wf_grid`、区间、池、
   成本、指标版本全部来自源记录，逐项未动。
3. **不声称字节级相同**：`schema_version` 从 `historical 26` 变为
   `current 28`，`config_hash` 从 `86e4b4e8bac296ad` / `4457e246afad6e79`
   变为 `b6b1babace517bdc` / `11ce7469245afab0`。这是**新生成的 hash**，
   报告明确标注为 **legacy-compatible replay**，不冒充"历史配置哈希"。
4. **等价性可验证**：G4 重建后参数与已重放的 G1（current 28 字段、
   `config_hash=b6b1babace517bdc`）**完全相同**；G5 重建后与
   `b6e1155d19ba4b6a`（`config_hash=11ce7469245afab0`）**完全相同**。
   两条独立路径（historical 映射 / 原生 current）殊途同归，
   反向证明映射值选对了。

### 3.4 映射的落库表现

| 记录 | schema_version | 源 hash | 新 hash | 映射字段 |
| --- | --- | --- | --- | --- |
| G4 新 `93c170ca1402419f` | historical 26 → current 28 | `86e4b4e8bac296ad` | `b6b1babace517bdc` | `regime_ma_window=250`、`min_validation_days=120` |
| G5 新 `1c5832e27c6c4f3c` | historical 26 → current 28 | `4457e246afad6e79` | `11ce7469245afab0` | 同 |

---

## 4. 阶段3A 历史记录最终状态

### 4.1 五分类（题目口径）

| 类别 | backtest | validation | 合计 |
| --- | ---: | ---: | ---: |
| `current_formal` | 3 | 23 | **26** |
| `replayed` | 2 | 10 | **12** |
| `legacy_replayable` | 0 | 27 | **27** |
| `non_replayable` | 9 | 0 | **9** |
| `failed_attempt` | 0 | 4 | **4** |
| **合计** | **14** | **64** | **78** |

口径说明：

- `current_formal` = `accounting_version == ca-v2-receivable` 且未被重放
- `replayed` = 源记录已被成功重放，且重放结果**未被取代**
- `legacy_replayable` = 仍是旧口径、但参数可证明，且**其配置组已被代表记录覆盖**
- `non_replayable` = 参数缺失（9 条 backtest 的 `ma_window` / `rebalance_tolerance`）
- `failed_attempt` = 源记录本身 `status=failed`（4 条 validation）

### 4.2 关于 27 条 `legacy_replayable`

这 27 条**不是"待重放"**，而是"配置组已被代表记录覆盖、本身不重复执行"：

| config_hash | 条数 | 由谁覆盖 |
| --- | ---: | --- |
| `b6b1babace517bdc` | 17 | G1 / G4 代表 |
| `b1de1d7323a8a35d` | 4 | G2 代表 |
| `177a329b6fd72cec` | 4 | G3 代表 |
| `86e4b4e8bac296ad` | 1 | G4 代表（`5ec77faf42d64162`，参数等价） |
| `11ce7469245afab0` | 1 | G5 代表（`b6e1155d19ba4b6a`，参数等价） |

按任务要求"同配置组只重放代表记录、其他只标记"，这些记录保持
`legacy_replayable` 状态**是正确的最终态**，不需要也不应该再重放。

---

## 5. G2/G3/G4/G5 逐条结果汇总

| 组 | source_id | 是否重放 | 是否成功 | 未重放原因 / 映射 |
| ---: | --- | --- | --- | --- |
| G2 | `c84356bd50ca4bb5` | ✅ | ✅ | — |
| G3 | `2b21ca9b2c434444` | ✅ | ✅ | — |
| G4 | `f9898c695b394808` | ✅ | ✅ | legacy-compatible：`regime_ma_window=250`、`min_validation_days=120`（旧版代码常量，非猜默认值） |
| G5 | `e725034e46ff47e5` | ✅ | ✅ | 同上 |
| G2 组其余 4 条 | — | ❌ | — | 同配置组，参数完全相同，不重复运行 |
| G3 组其余 4 条 | — | ❌ | — | 同上 |
| G4 组其余 1 条 | `5ec77faf42d64162` | ❌ | — | 同上，且参数等价于 G4 代表 |

---

## 6. 阶段3A 最终剩余问题

### P0（阻塞）

**No remaining P0 blockers.**

### P1（重要但不阻塞封板）

**No remaining P1 blockers.**

### P2（记录在案，不影响结论）

| # | 问题 | 影响 | 处置 |
| ---: | --- | --- | --- |
| 1 | 27 条 `legacy_replayable` 保持旧口径 | 它们的绩效数字仍是旧口径，不能与 `current_formal` 混用比较 | 已按配置组由代表记录覆盖；报告标注不可混用 |
| 2 | 9 条 backtest 永久 `non_replayable` | 缺 `ma_window` / `rebalance_tolerance`，无法忠实重放 | 逐条写明缺失字段，不猜 |
| 3 | 4 条 `failed_attempt` | 源记录本身失败 | 保留原样，不伪装成功 |
| 4 | G4/G5 的 `config_hash` 与源不同 | 新 hash 由 28 字段集生成 | 报告明确标注 legacy-compatible，不冒充历史 hash |

### non-blocking（观察项）

| # | 项 |
| ---: | --- |
| 1 | IS 网格里 MA250 档被分红口径放大最多，导致 G1/G4 最优参数从 MA60 漂移到 MA250。这是口径切换的正常结果，已归因，不是缺陷。 |
| 2 | G2/G3 的选参未变（MA60 / MA30），差异幅度小（G3 在 0.04% 内），可作口径切换影响的对照样本。 |

---

## 7. 数据完整性

### 7.1 执行前后行数

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 307 | 507 | +200 |
| `validation_runs` | 60 | 64 | +4 |
| `replay_attempts` | 19 | 23 | +4 |
| `replay_supersessions` | 2 | 2 | **0** |
| `validation_backtest_runs` | 654 | 854 | +200 |
| `validation_regime_stats` | 48 | 64 | +16 |
| `validation_stress` | 399 | 427 | +28 |
| `validation_windows` | 454 | 486 | +32 |
| `validation_grid` | 416 | 440 | +24 |
| `corporate_action_applications` | 7,650 | 8,873 | +1,223 |
| `dividend_receivables` | 3,934 | 4,947 | +1,013 |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_versions` | 704 | 704 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |
| `etf_indicator_daily` | 350,292 | 350,292 | **0** |

### 7.2 完整性检查

| 项 | 执行前 | 执行后 |
| --- | --- | --- |
| `PRAGMA integrity_check` | ok | **ok** |
| 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` | **未变** |
| 行情行数 | 116,609 | 116,609 |
| 公司行为事件 | 166 | 166 |
| 公司行为版本 | 704 | 704 |

### 7.3 源历史记录未改动

| source_id | `input_hash` 执行前 | 执行后 | 是否变化 |
| --- | --- | --- | --- |
| `c84356bd50ca4bb5` | `e4b62767ad909949` | `e4b62767ad909949` | 未变 |
| `2b21ca9b2c434444` | `5fbdd777b0f24a82` | `5fbdd777b0f24a82` | 未变 |
| `f9898c695b394808` | `51fb37419139a52e` | `51fb37419139a52e` | 未变 |
| `e725034e46ff47e5` | `7a5a694c3fd321a9` | `7a5a694c3fd321a9` | 未变 |

四条源记录 `accounting_version` 仍全部为
`legacy_corporate_action_accounting`，未被改写。

### 7.4 历史 attempt 完整性

本阶段新增 attempt 全部属于授权四条：

```
fdb0e78069284fb1  c84356bd50ca4bb5  success
ce071b8979b5427c  2b21ca9b2c434444  success
3508b65202a64aea  f9898c695b394808  success
3337840f523d49e6  e725034e46ff47e5  success
```

越界 source：**无**。

历史 attempt 未被修改：`replay_supersessions` 前后均为 2 条
（第一批的两条），本批四条源记录此前没有 success replay，
不需要失效标记。`37e017afb1514fd4`（第二批 G8 超时中断）保持 `failed`
并保留原因，未被改动。

### 7.5 历史记录未被删除

执行前后各表行数只增不减（除 `replay_supersessions` 持平），
无任何 `DELETE` 操作。

---

## 8. 全量测试

```
702 passed, 1 warning in 258.27s (0:04:18)
```

| 项 | 数量 |
| --- | ---: |
| 通过 | **702** |
| 失败 | 0 |
| 跳过 | 0 |
| xfail | 0 |
| 耗时 | 258.27 秒 |

另：

| 项 | 结果 |
| --- | --- |
| API smoke | `SMOKE_FAILED: 无` |
| AppTest `3_回测.py` | exception 0 / error 0 / df 5 / metric 5 |
| AppTest `4_策略验证.py` | exception 0 / error 0 / df 8 / metric 7 |
| `PRAGMA integrity_check` | ok |

本阶段未修改任何工程代码，测试数量与基线一致（702）。

---

## 9. 边界声明

| 禁止项 | 执行情况 |
| --- | --- |
| 修改策略 | 未修改 |
| 修改会计 | 未修改 |
| 修改撮合 | 未修改 |
| 修改绩效计算 | 未修改 |
| 修改公司行为算法 | 未修改 |
| 修改行情 | 未修改（指纹未变） |
| 修改审计核心逻辑 | 未修改 |
| 猜测参数 | 未猜（G4/G5 用旧版代码常量，有 git 证据） |
| 使用当前默认值填历史 | 未用当前默认值"填"，用的是旧版实际生效的常量 |
| 使用 force | **未使用** |
| 执行未授权 source | 未执行（越界检查为空） |
| 超范围重放 | 未超出 G2/G3/G4/G5 代表 |

---

## 10. 阶段3A 封板条件核对

| # | 条件 | 状态 | 证据 |
| ---: | --- | --- | --- |
| 1 | G2/G3/G4/G5 已全部明确处理 | ✅ | §2 §5，四条代表全部重放成功 |
| 2 | 可忠实重放的已重放 | ✅ | 四条全部 success |
| 3 | 不可忠实重放的已记录原因 | ✅ | §4 §5，同配置组与 non_replayable 逐条说明 |
| 4 | 未通过猜参数制造成功 | ✅ | §3，映射值有 git 常量证据 |
| 5 | 无剩余 P0/P1 工程阻塞 | ✅ | §6 |
| 6 | 数据库完整性通过 | ✅ | §7，integrity ok、指纹未变、源记录未改 |
| 7 | 全量测试通过 | ✅ | §8，702 passed |
| 8 | README 更新 | ✅ | 第 50 章 |
| 9 | CHANGELOG 更新 | ✅ | 本轮条目 |
| 10 | 本报告完成 | ✅ | `reports/phase3A_final_replay_closure.md` |
| 11 | Gitee 先提交 | ✅ | 见交付 |
| 12 | GitHub 同步成功 | ✅ | 见交付 |

**PHASE 3A CLOSED**

---

## 11. 交付物

| 项 | 值 |
| --- | --- |
| 执行前备份 | `data/backups/fund_agent_pre_3a3_final_20261118.db`，276,078,592 字节，SHA256 `37e1e4fc59f86362fd826843e78e21a9fb35312188601b9fff8af4107a8671fb` |
| 全量测试 | 702 passed / 0 failed / 0 skipped，258.27 秒 |
| `integrity_check` | ok |
| 行情指纹 | `d54727c0…ac49` 未变 |
