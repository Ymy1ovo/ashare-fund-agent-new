# 阶段3A.3.2.3.1 历史验证记录盘点报告

- 生成时间：2026-11-14
- 基线 HEAD：`f99c6ea379b297ff1bf141823e88f4413451ee5b`
- 数据来源：`data/fund_agent.db` 的 `validation_runs` 实际字段
- 复现命令：`python scripts/audit_replay_history.py`

## 1. 总量与分类

| 项 | 数量 |
| --- | ---: |
| `validation_runs` 总数 | **44** |
| `current_formal` | **5** |
| `replayed` | 0 |
| `legacy` | **37** |
| `unknown_legacy` | 0 |
| `non_replayable` | **2** |
| 待重放 | **37** |
| 已重放 | 0 |

合计 5+0+37+0+2 = 44 = 总数。

## 2. 参数可证明性：config_hash 反证法

`validation_runs` 只存了区间、ETF 池、参数网格这几列；
**初始资金、佣金、最低佣金、滑点、执行价、指标版本、Walk-Forward 网格、
池模式全部没有独立列**，只体现为一列 `config_hash`（`ValidationConfig.params_hash()`
的 SHA256 前 16 位）。

要「忠实沿用源参数」，唯一诚实的做法是反证：

```
把候选参数代入 params_hash()
  → 结果等于 config_hash  ⇒ 全部参数被证明（包括默认值那批）
  → 结果不等             ⇒ 参数不可证明，判 non_replayable
```

候选字段集有两套：

| 变体 | 字段数 | 说明 |
| --- | ---: | --- |
| `current` | 28 | 当前 `ValidationConfig` 字段全集 |
| `historical` | 26 | 去掉 `regime_ma_window` / `min_validation_days`（3A.3.2.1 之前） |

日期端点还要考虑「请求日对齐到下一交易日」：仓库里存的是对齐后的日期
（请求 2021-01-01 → 存 2021-01-04）。反证时把「存储值」和「该月 1 日」
都作为候选。

**反证成功 = 参数被证明**，不是「大概差不多」。

## 3. 分类结果

| classification | 数量 | 说明 |
| --- | ---: | --- |
| `current_formal` | 5 | `accounting_version='ca-v2-receivable'` |
| `legacy` | 37 | legacy 会计版本 + `config_hash` 反证命中 |
| `non_replayable` | 2 | `config_hash` 反证失败 **且** 源记录本身 `status=failed` |

5 条 `current_formal`：

| validation_id | input_hash | 结论 |
| --- | --- | --- |
| `e0ac2b1b3b9748ac` | `2ac80bcdfb5459c5` | 有条件通过 |
| `6e310be0193643c1` | `5f8a4c05613552fa` | 有条件通过 |
| `06600b4faac146c5` | `63d62a67a797c55b` | 有条件通过 |
| `e8b052dd2db542f9` | `6da51a1c462b7c65` | 有条件通过 |
| `0df22f3810974bea` | `6da51a1c462b7c65` | 有条件通过 |

2 条 `non_replayable`：

| validation_id | 原因 |
| --- | --- |
| `c99a2a75b7e646c5` | `config_hash=994f0f5410491661` 反证失败 + `status=failed` |
| `03bf88593cd54841` | 同上（两条记录 `config_hash` 相同，都是 44/41 只池的失败尝试） |

这两条不仅是参数不可证明，源记录本身就没有跑完（`summary_json` 为空）。

## 4. 37 条 legacy 的分布

| 维度 | 分布 |
| --- | --- |
| 池模式 | `representative` 33 条（6 只），`all` 4 条（41 只） |
| 参数网格 | `[5,10,20,30,60,120,250]` 31 条，`[5,20,60]` 3 条，`[10,30,120]` 3 条 |
| 区间 | 35 条标准 2021-01-04~2024-12-31 / 2025-01-02~2026-11-09；1 条样本内起点 2021-06-01；1 条样本外起点 2025-06-03 |
| `input_hash` 去重 | 37 条记录只有 **10 个不同 `input_hash`** |

`input_hash` 重复说明：早期 `_input_hash()` 尚未纳入公司行为事件指纹，
同一套参数在事件数据不同的时点会得到相同哈希。这正是本轮要做重放的原因之一。

## 5. 逐条（37 条 legacy，节选前 12 条）

| validation_id | 区间 | ETF | 池模式 | 网格 | input_hash |
| --- | --- | ---: | --- | --- | --- |
| `f9898c695b394808` | 2021-01-04~2024-12-31 / 2025-01-02~2026-11-09 | 6 | representative | 7 档 | `51fb37419139a52e` |
| `5ec77faf42d64162` | 同上 | 6 | representative | 7 档 | `51fb37419139a52e` |
| `e725034e46ff47e5` | 同上 | 41 | all | 7 档 | `7a5a694c3fd321a9` |
| `7d884a1a03d94915` | 同上 | 6 | representative | 7 档 | `3e064b6673929193` |
| `e1e11a114ff74326` | 同上 | 6 | representative | 7 档 | `3e064b6673929193` |
| `9ecdd5ec67594110` | 同上 | 6 | representative | 7 档 | `3e064b6673929193` |
| `f07b281c296841a4` | 同上 | 6 | representative | 7 档 | `3e064b6673929193` |
| `b6e1155d19ba4b6a` | 同上 | 41 | all | 7 档 | `33fbd255d81813b5` |
| `27e4937128fb4135` | 同上 | 6 | representative | 7 档 | `dc5137ab80c92d71` |
| `32aead3291734f91` | 同上 | 41 | all | 7 档 | `dbfac114e6900c87` |
| `c84356bd50ca4bb5` | 同上 | 6 | representative | `[5,20,60]` | `e4b62767ad909949` |
| `2b21ca9b2c434444` | 同上 | 6 | representative | `[10,30,120]` | `5fbdd777b0f24a82` |

完整 37 条见 `data/replay_manifest_3a3_2_3_1.json`。

## 6. 待重放清单（37 条）

全部 37 条 `legacy` 验证记录都可重放（参数已由 `config_hash` 证明）。
命令：

```bash
# 单条
python scripts/replay_validation_3a3_2.py --source 32aead3291734f91

# 全部（预计 37 × 约 24 分钟 ≈ 15 小时）
python scripts/replay_validation_3a3_2.py --pending
```

**本轮不执行批量重放**，只建机制。任务书明确要求「先建设工具并完成盘点，
不执行全量批量重放」。

## 7. 与回测盘的差异

| 项 | backtest | validation |
| --- | ---: | ---: |
| 总数 | 12 | 44 |
| 可重放比例 | 2/12 | 37/44 |
| 不可重放根因 | `ma_window` 未落库 | `config_hash` 无法反证（2 条，均为失败记录） |

`validation_runs` 之所以可重放比例高，是因为它有 `config_hash` 可以反证；
`backtest_runs` 的 `strategy_params` 恒为空，没有任何反证材料。

## 8. 结论

- 44 条记录全部盘点，分类合计等于总数
- 5 条已是当前正式口径，37 条待重放，2 条永久不可重放
- 参数忠实性由 `config_hash` 反证保证，不是「按默认值重建」
- 所有历史行未被修改
