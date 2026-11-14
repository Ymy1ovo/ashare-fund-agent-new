# 阶段3A.3.2.3.1 批量重放清单

- 生成时间：2026-11-14
- 基线 HEAD：`f99c6ea379b297ff1bf141823e88f4413451ee5b`
- 复现：`python scripts/audit_replay_history.py --pending-only`
- **本轮不执行全量批量重放**，本文件是执行清单与预估

## 1. 汇总

| 类别 | 总数 | current_formal | replayed | legacy（待重放） | non_replayable |
| --- | ---: | ---: | ---: | ---: | ---: |
| `backtest_runs` | 12 | 1 | 1 | **1** | 9 |
| `validation_runs` | 44 | 5 | 0 | **37** | 2 |
| **合计** | **56** | 6 | 1 | **38** | 11 |

## 2. backtest 待重放（1 条）

| run_id | 策略 | 区间 | ETF | 初始资金 | 执行价 | 预估耗时 |
| --- | --- | --- | ---: | ---: | --- | ---: |
| `8412fc1cefb4437e` | buy_and_hold | 2024-01-02~2026-11-09 | 1 | 1,000,000 | open | 约 15 秒 |

```bash
python scripts/replay_3a3_2.py --source 8412fc1cefb4437e
```

## 3. validation 待重放（37 条）

按池模式与网格分组（同组可视为同一批实验）：

| # | validation_id | 池模式 | ETF | 网格 | input_hash | 预估 |
| ---: | --- | --- | ---: | --- | --- | ---: |
| 1 | `f9898c695b394808` | representative | 6 | 7 档 | `51fb37419139a52e` | 约 24 分钟 |
| 2 | `5ec77faf42d64162` | representative | 6 | 7 档 | `51fb37419139a52e` | 约 24 分钟 |
| 3 | `e725034e46ff47e5` | all | 41 | 7 档 | `7a5a694c3fd321a9` | 约 90 分钟 |
| 4 | `7d884a1a03d94915` | representative | 6 | 7 档 | `3e064b6673929193` | 约 24 分钟 |
| 5 | `e1e11a114ff74326` | representative | 6 | 7 档 | `3e064b6673929193` | 约 24 分钟 |
| 6 | `9ecdd5ec67594110` | representative | 6 | 7 档 | `3e064b6673929193` | 约 24 分钟 |
| 7 | `f07b281c296841a4` | representative | 6 | 7 档 | `3e064b6673929193` | 约 24 分钟 |
| 8 | `b6e1155d19ba4b6a` | all | 41 | 7 档 | `33fbd255d81813b5` | 约 90 分钟 |
| 9 | `27e4937128fb4135` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 10 | `32aead3291734f91` | all | 41 | 7 档 | `dbfac114e6900c87` | 约 90 分钟 |
| 11 | `a04091b514ce4c4f` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 12 | `a36545a411904c01` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 13 | `45eb41bac1514669` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 14 | `c84356bd50ca4bb5` | representative | 6 | `[5,20,60]` | `e4b62767ad909949` | 约 12 分钟 |
| 15 | `2b21ca9b2c434444` | representative | 6 | `[10,30,120]` | `5fbdd777b0f24a82` | 约 12 分钟 |
| 16 | `c5589f7dcd1a4a5d` | representative | 6 | 7 档 | `b7970e3feb8c151f` | 约 24 分钟 |
| 17 | `838a58fa5f3b4025` | representative | 6 | 7 档 | `ab05fa513aed5197` | 约 24 分钟 |
| 18 | `6b9cc7ef14e44878` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 19 | `471ae52410de427a` | representative | 6 | `[5,20,60]` | `e4b62767ad909949` | 约 12 分钟 |
| 20 | `55a0df1bb2bb477d` | representative | 6 | `[10,30,120]` | `5fbdd777b0f24a82` | 约 12 分钟 |
| 21 | `a6d35304e92e4fca` | representative | 6 | `[5,20,60]` | `e4b62767ad909949` | 约 12 分钟 |
| 22 | `03ff00a306bf4141` | representative | 6 | `[10,30,120]` | `5fbdd777b0f24a82` | 约 12 分钟 |
| 23 | `3eebe3d53b5b462d` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 24 | `aa51841d096f4ada` | representative | 6 | `[5,20,60]` | `e4b62767ad909949` | 约 12 分钟 |
| 25 | `02edb3dd966042b3` | representative | 6 | `[10,30,120]` | `5fbdd777b0f24a82` | 约 12 分钟 |
| 26 | `4a03b4cfc2c142f0` | representative | 6 | `[5,20,60]` | `e4b62767ad909949` | 约 12 分钟 |
| 27 | `bdfe34dbfe91424a` | representative | 6 | `[10,30,120]` | `5fbdd777b0f24a82` | 约 12 分钟 |
| 28 | `9bfe82141e2c41c4` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 29 | `c7e86fb64c914cb2` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 30 | `d1f811a567f24252` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 31 | `81f0cc3fe8e34e64` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 32 | `05b9af375c4e4ee5` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 33 | `4b37c111e6ab4403` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 34 | `e18525b7d5244d9f` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 35 | `e3507c7defa34229` | representative | 6 | 7 档 | `dc5137ab80c92d71` | 约 24 分钟 |
| 36 | `b3f1e2c89ebc4b95` | representative | 6 | 7 档 | `451bdcc990343464` | 约 24 分钟 |
| 37 | `c46fa37b932944c2` | all | 41 | 7 档 | `2ac80bcdfb5459c5` | 约 90 分钟 |

预估总耗时：**约 13~15 小时**（4 条 41 只池 × 90 分钟 + 33 条 6 只池 × 12~24 分钟）。

## 4. 建议执行顺序

同一 `input_hash` 的记录参数完全相同，重放结果在会计口径固定后应一致。
建议按「信息增益 / 耗时」排序，而不是按 ID 顺序：

| 优先级 | 目标 | 记录 |
| --- | --- | --- |
| P0 | 41 只全池（唯一能作为正式评价依据的规模） | `32aead3291734f91`、`c46fa37b932944c2`、`e725034e46ff47e5`、`b6e1155d19ba4b6a` |
| P1 | 代表性池标准网格（与最近几轮口径可比） | `dc5137ab80c92d71` 系列共 12 条 |
| P2 | 参数敏感性实验（不同网格） | `[5,20,60]` 4 条 + `[10,30,120]` 4 条 |
| P3 | 区间敏感性实验 | `c5589f7dcd1a4a5d`（样本内起点）、`838a58fa5f3b4025`（样本外起点） |
| P4 | 与已有结论重复的记录 | 其余 |

P0 的 4 条合计约 6 小时，若只需一个正式结论，先跑 `32aead3291734f91`
与 `c46fa37b932944c2` 这 2 条即可覆盖「旧口径 → 3A.3.2 → 当前」的对照。

## 5. 执行命令

```bash
# 单条
python scripts/replay_validation_3a3_2.py --source 32aead3291734f91

# 全部 37 条（幂等：已成功的自动跳过）
python scripts/replay_validation_3a3_2.py --pending

# 中断后恢复：直接重跑同一条命令即可
python scripts/replay_validation_3a3_2.py --pending

# 强制重跑某条
python scripts/replay_validation_3a3_2.py --source 32aead3291734f91 --force

# 只检查不执行
python scripts/replay_validation_3a3_2.py --pending --dry-run
```

## 6. 永久不可重放（11 条）

### 6.1 backtest（9 条）

全部因 `ma_window` 未落库。除非能从外部证据（当时的命令行历史、日志）
恢复窗口值，否则永久不可重放。**不允许用默认 20 或报告数字反推**。

| run_id | 原因 |
| --- | --- |
| `7181d2a6ed3f4555` | 缺 `rebalance_tolerance` |
| `d08db2c030a64458` | 缺 `ma_window` + `rebalance_tolerance` |
| `2ecc9c0803174978` | 缺 `ma_window` + `rebalance_tolerance` |
| `6a7fe99ac55a4639` | 缺 `ma_window` |
| `dbf4bc0e46104b23` | 缺 `ma_window` |
| `c72cc00273624760` | 缺 `ma_window` |
| `90c76130c8884212` | 缺 `ma_window` |
| `08a4c7f1529b42e2` | 缺 `ma_window` |
| `cabbfe77035d40f3` | 缺 `ma_window` |

### 6.2 validation（2 条）

| validation_id | 原因 |
| --- | --- |
| `c99a2a75b7e646c5` | `config_hash` 反证失败 + 源记录 `status=failed` |
| `03bf88593cd54841` | 同上 |

这两条是早期 44/41 只池的失败尝试，`summary_json` 为空，
即使参数能反证也没有可比的原始结果。

## 7. 执行前的检查清单

- [ ] `python scripts/audit_replay_history.py --show none` 分类合计等于总数
- [ ] `PRAGMA integrity_check` = ok
- [ ] 行情指纹记录当前值 `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`
- [ ] 数据库已备份到 `data/backups/`
- [ ] 确认没有其它进程在写库

## 8. 执行后的检查清单

- [ ] 重放后行情指纹与执行前一致
- [ ] `integrity_check` = ok
- [ ] `replay_attempts` 中每条都有 `success` 或明确的 `failed` + `reason`
- [ ] 源记录行数与内容未变（逐条比对 `run_id` / `validation_id` 列表）
- [ ] 新记录的 `accounting_version` 为 `ca-v2-receivable`
- [ ] 新记录的 `accounting_basis` 为 `formal_receivable`、`formal_valuation=True`
