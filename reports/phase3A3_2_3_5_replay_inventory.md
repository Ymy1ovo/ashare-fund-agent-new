# 阶段3A.3.2.3.5 历史回测与验证记录重放候选清点

- 基线 HEAD：`7b9c9f54e7007854b2df26c0c627f0d671a74dae`
- 执行日期：2026-11-17
- 性质：**只清点，不重放**。本轮未执行任何历史回测或验证重放。

---

## 1. 清点方法与数据来源

全部数字由项目现有只读脚本产出，可复算：

```bash
python scripts/audit_replay_history.py
python scripts/audit_replay_history.py --json data/replay_manifest.json
```

底层函数：`app/replay/manifest.py::backtest_manifest()` /
`validation_manifest()` / `summarize()`，
`app/replay/registry.py::success_map()`。

本次清点导出的机器可读快照：`reports/phase3A3_2_3_5_replay_inventory.json`（221,542 字节）。

### 1.1 分类口径

本阶段题目要求的五分类与项目既有分类的对应关系：

| 题目分类 | 项目既有常量 | 判定依据 |
| --- | --- | --- |
| `current_formal` | `CLASS_CURRENT_FORMAL` | `accounting_version == ca-v2-receivable` |
| `replayed` | `CLASS_REPLAYED` | `replay_attempts` 中存在 `status=success` 且能追到源记录 |
| `legacy_replayable` | `CLASS_LEGACY` | `accounting_version == legacy_corporate_action_accounting` 且全部关键参数可证明 |
| `non_replayable` | `CLASS_NON_REPLAYABLE` + `CLASS_UNKNOWN_LEGACY` | 缺关键参数，或会计口径无法确认 |
| `failed_attempt` | 无独立常量（按 `status='failed'` 拆出） | 源记录本身 `status=failed`，不能伪装成有效结果 |

`failed_attempt` 是本阶段新增的**呈现分类**，不新增数据库字段、不新增代码常量，
只是在报告层把「源记录自己就失败了」从 `non_replayable` 里拆出来单独统计，
避免把「参数缺失」和「跑失败了」混成一类。

---

## 2. 统计汇总

### 2.1 总量

| 项 | 数量 |
| --- | ---: |
| 历史记录总数 | **66** |
| `backtest_runs` | 12 |
| `validation_runs` | 54 |

### 2.2 validation_runs（54 条）

| 分类 | 数量 |
| --- | ---: |
| `current_formal` | 14 |
| `replayed` | 2 |
| `legacy_replayable` | 35 |
| `non_replayable` | 0 |
| `failed_attempt` | 3 |
| **合计** | **54** |

交叉核对：分类合计 = 总数 ✅

### 2.3 backtest_runs（12 条）

| 分类 | 数量 |
| --- | ---: |
| `current_formal` | 1 |
| `replayed` | 1 |
| `legacy_replayable` | 1 |
| `non_replayable` | 9 |
| `failed_attempt` | 0 |
| **合计** | **12** |

交叉核对：分类合计 = 总数 ✅

### 2.4 合并

| 分类 | backtest | validation | 合计 |
| --- | ---: | ---: | ---: |
| `current_formal` | 1 | 14 | **15** |
| `replayed` | 1 | 2 | **3** |
| `legacy_replayable` | 1 | 35 | **36** |
| `non_replayable` | 9 | 0 | **9** |
| `failed_attempt` | 0 | 3 | **3** |
| **合计** | **12** | **54** | **66** |

---

## 3. 已重放的两条 P0 记录（核实，不重复执行）

题目要求核实 `32aead3291734f91` 与 `c46fa37b932944c2`，避免重复执行。

### 3.1 `32aead3291734f91`

| 项 | 值 |
| --- | --- |
| 策略 | `ma_trend` 1.0.0 |
| 区间 | IS 2021-01-04~2024-12-31 / OOS 2025-01-02~2026-11-09 |
| ETF 池 | 41 只，`pool_mode=all` |
| 网格 | `[5, 10, 20, 30, 60, 120, 250]` |
| config_hash | `11ce7469245afab0` |
| input_hash | `dbfac114e6900c87` |
| 参数证明 | `config_hash 完全命中（current 字段集，pool_mode=all，请求区间 2021-01-01~2024-12-31 / 2025-01-01~2026-11-09）` |
| 会计口径 | `legacy_corporate_action_accounting` |
| 重放去向 | `03410886d1f64fa7`（`current_formal`） |
| 重放尝试 | `63a6005bacf74a39` → `success`，2026-11-14T15:57:30 ~ 16:24:34 |

**历史尝试**：另有 `d1113ae9bf1e4a4b` → `397118a140c44f47`，状态 `failed`，
失败原因「重放记录会计版本异常：None（3A.3.2.3.3 首次执行，口径标记缺失）」。
该失败尝试**保留**，未删除，判 `failed_attempt`。

### 3.2 `c46fa37b932944c2`

| 项 | 值 |
| --- | --- |
| 策略 | `ma_trend` 1.0.0 |
| 区间 | IS 2021-01-04~2024-12-31 / OOS 2025-01-02~2026-11-09 |
| ETF 池 | 41 只，`pool_mode=all` |
| 网格 | `[5, 10, 20, 30, 60, 120, 250]` |
| config_hash | `5bc9252086c515e2` |
| input_hash | `2ac80bcdfb5459c5` |
| 参数证明 | `config_hash 完全命中（current 字段集，pool_mode=all，请求区间 2021-01-04~2024-12-31 / 2025-01-02~2026-11-09）` |
| 会计口径 | `legacy_corporate_action_accounting` |
| 重放去向 | `aad7935a2bac4cc4`（`current_formal`） |

**重放链路共 8 次成功尝试**（同一源记录被反复重放以验证一致性）：

| 尝试 ID | 重放记录 | 时间 |
| --- | --- | --- |
| `1d5e43c4ccda45d9` | `321caeb581e54d3b` | 2026-11-14T16:26:36~16:56:31 |
| `6058e974df3441d6` | `8181fa3cbf394466` | 2026-11-16T11:52:37~12:22:30 |
| `f1214b82a2154b31` | `e815aee4f01b4146` | 2026-11-16T12:32:43~13:02:48 |
| `5bd1902d38ac44a3` | `61a7829c9f7d4fac` | 2026-11-16T13:11:12~13:44:20 |
| `cce62a0afaac4c72` | `d8dc7e7c109342c1` | 2026-11-16T13:51:49~14:20:21 |
| `4855d9fab239482d` | `67ad070efc0d4b7b` | 2026-11-16T14:22:55~14:53:44 |
| `3fc511174f70470b` | `159cfe0708fb49c6` | 2026-11-16T15:07:09~15:34:45 |
| `b19ea41c98f44bcb` | `aad7935a2bac4cc4` | 2026-11-16T15:44:35~16:14:21 |

这 8 条的 `replay_input_hash` 全部为 `6da51a1c462b7c65`，
`replay_accounting_version` 全部为 `ca-v2-receivable`。

### 3.3 核实结论

| 检查项 | 结论 |
| --- | --- |
| 两条源记录当前分类 | 均为 `replayed` |
| 是否有成功重放记录 | 是，分别指向 `03410886d1f64fa7` / `aad7935a2bac4cc4` |
| 是否在待重放清单里 | **否**（`pending.validation` 不含这两个 ID） |
| 本轮是否重复执行 | **否** |

### 3.4 顺带发现：另有一条已成功重放但不在题目点名范围内

`c46fa37b932944c2` 的 8 次成功重放中，有 7 条记录的 `config_hash` 与
`c46fa37b932944c2` 完全相同（`5bc9252086c515e2`），只有 `321caeb581e54d3b`
等少数带完整审计证据。这意味着当前 `current_formal` 的 14 条里，
多数是**同一配置的重复执行**，不是 14 个不同实验。详见 §6。

---

## 4. backtest_runs 逐条清单（12 条）

| # | run_id | 分类 | 策略 | 区间 | 池 | 初始资金 | 指标版本 | 会计口径 | 参数缺失 | 重放去向 |
| ---: | --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- |
| 1 | `7181d2a6ed3f4555` | non_replayable | buy_and_hold 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | config:rebalance_tolerance | — |
| 2 | `d08db2c030a64458` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window、config:rebalance_tolerance | — |
| 3 | `2ecc9c0803174978` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 46 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window、config:rebalance_tolerance | — |
| 4 | `6a7fe99ac55a4639` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 46 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window | — |
| 5 | `ac8f4cc7cf234d7e` | replayed | buy_and_hold 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | — | `355948ec40224eb5` |
| 6 | `dbf4bc0e46104b23` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window | — |
| 7 | `8412fc1cefb4437e` | legacy_replayable | buy_and_hold 1.0.0 | 2024-01-02~2026-11-09 | 1 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | — | — |
| 8 | `c72cc00273624760` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window | — |
| 9 | `90c76130c8884212` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window | — |
| 10 | `08a4c7f1529b42e2` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window | — |
| 11 | `cabbfe77035d40f3` | non_replayable | ma_trend 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `legacy_corporate_action_accounting` | strategy_param:ma_window | — |
| 12 | `355948ec40224eb5` | current_formal | buy_and_hold 1.0.0 | 2024-01-02~2026-11-09 | 5 | 1000000 | `v1.0.2-30b821a1af15` | `ca-v2-receivable` | — | — |
### 4.1 backtest 不可重放原因（9 条，逐条）

| run_id | 缺失项 | 具体含义 |
| --- | --- | --- |
| `7181d2a6ed3f4555` | `config:rebalance_tolerance` | `config_json` 无 `rebalance_tolerance` 字段；该值影响调仓容忍带，缺了只能猜 |
| `d08db2c030a64458` | `strategy_param:ma_window`、`config:rebalance_tolerance` | 策略参数 `ma_window` 未落 `config_json`；MA 策略没有它无法复现 |
| `2ecc9c0803174978` | 同上 | 同上（46 只池） |
| `6a7fe99ac55a4639` | `strategy_param:ma_window` | 同上（46 只池，但 `rebalance_tolerance` 有） |
| `dbf4bc0e46104b23` | `strategy_param:ma_window` | 同上（5 只池） |
| `c72cc00273624760` | `strategy_param:ma_window` | 同上 |
| `90c76130c8884212` | `strategy_param:ma_window` | 同上 |
| `08a4c7f1529b42e2` | `strategy_param:ma_window` | 同上 |
| `cabbfe77035d40f3` | `strategy_param:ma_window` | 同上（5 只池：159915/510050/510300/510500/510880） |

**共同点**：这 9 条都是 2024-01-02~2026-11-09 的短区间用户回测，
`ma_trend` 策略的参数写在当时的调用代码里、没进 `config_json`；
`rebalance_tolerance` 则是在后续版本才加入配置。

**不做的事**：不根据「同期其他记录都用 ma_window=20」之类的间接推断补值。
缺就是缺。

### 4.2 backtest 唯一可重放的一条

`8412fc1cefb4437e` — `buy_and_hold` 1.0.0，1 只标的（`510300`），
区间 2024-01-02~2026-11-09，初始资金 1,000,000，指标版本 `v1.0.2-30b821a1af15`。

参数恢复依据（`params_source` 全部为 `recorded`）：

| 参数 | 值 | 来源 |
| --- | --- | --- |
| `weights` | 记录值（空，等权） | `config_json.weights` |
| `start_date` | `2024-01-02` | 列 |
| `end_date` | `2026-11-09` | 列 |
| `initial_cash` | `1000000.0` | 列 |
| `execution_price` | `open` | `config_json` |
| `costs` | 佣金 0.00025 / 最低 5 / 滑点 5bp / 其他 0 | `config_json.costs` |
| `max_defer_days` | 3 | `config_json` |
| `risk_free_rate` | 0.0 | `config_json` |
| `annualization` | 252 | `config_json` |
| `rebalance_tolerance` | 0.02 | `config_json` |
| `cash_shortfall_policy` | `recorded` | `config_json` |
| `allow_partial_fill` | `recorded` | `config_json` |
| `instrument_overrides` | `recorded` | `config_json` |
| `lot_size_override` | `recorded` | `config_json` |

**全部字段均为 `recorded`，没有一个走默认值。** 这是它可重放的全部理由。

---

## 5. validation_runs 逐条清单（54 条）

| # | validation_id | 分类 | 状态 | 代码数 | 样本内 | 样本外 | 网格 | 池模式 | config_hash | 重放去向 |
| ---: | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| 1 | `c99a2a75b7e646c5` | failed_attempt | failed | 44 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | — | `994f0f5410491661` | — |
| 2 | `03bf88593cd54841` | failed_attempt | failed | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | — | `994f0f5410491661` | — |
| 3 | `f9898c695b394808` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `86e4b4e8bac296ad` | — |
| 4 | `5ec77faf42d64162` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `86e4b4e8bac296ad` | — |
| 5 | `e725034e46ff47e5` | legacy_replayable | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `4457e246afad6e79` | — |
| 6 | `7d884a1a03d94915` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 7 | `e1e11a114ff74326` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 8 | `9ecdd5ec67594110` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 9 | `f07b281c296841a4` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 10 | `b6e1155d19ba4b6a` | legacy_replayable | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `11ce7469245afab0` | — |
| 11 | `27e4937128fb4135` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 12 | `32aead3291734f91` | replayed | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `11ce7469245afab0` | `03410886d1f64fa7` |
| 13 | `a04091b514ce4c4f` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 14 | `a36545a411904c01` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 15 | `45eb41bac1514669` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 16 | `c84356bd50ca4bb5` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `b1de1d7323a8a35d` | — |
| 17 | `2b21ca9b2c434444` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `177a329b6fd72cec` | — |
| 18 | `c5589f7dcd1a4a5d` | legacy_replayable | success | 6 | 2021-06-01~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `9c245d882cb1cc72` | — |
| 19 | `838a58fa5f3b4025` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-06-03~2026-11-09 | 7 档 | representative | `88d40b3069c50f0a` | — |
| 20 | `6b9cc7ef14e44878` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 21 | `471ae52410de427a` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `b1de1d7323a8a35d` | — |
| 22 | `55a0df1bb2bb477d` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `177a329b6fd72cec` | — |
| 23 | `a6d35304e92e4fca` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `b1de1d7323a8a35d` | — |
| 24 | `03ff00a306bf4141` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `177a329b6fd72cec` | — |
| 25 | `3eebe3d53b5b462d` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 26 | `aa51841d096f4ada` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `b1de1d7323a8a35d` | — |
| 27 | `02edb3dd966042b3` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `177a329b6fd72cec` | — |
| 28 | `4a03b4cfc2c142f0` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `b1de1d7323a8a35d` | — |
| 29 | `bdfe34dbfe91424a` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 3 档 | representative | `177a329b6fd72cec` | — |
| 30 | `9bfe82141e2c41c4` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 31 | `c7e86fb64c914cb2` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 32 | `d1f811a567f24252` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 33 | `81f0cc3fe8e34e64` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 34 | `05b9af375c4e4ee5` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 35 | `4b37c111e6ab4403` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 36 | `e18525b7d5244d9f` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 37 | `e3507c7defa34229` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `b6b1babace517bdc` | — |
| 38 | `b3f1e2c89ebc4b95` | legacy_replayable | success | 6 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | representative | `39bac25b0ec4ce91` | — |
| 39 | `c46fa37b932944c2` | replayed | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | `aad7935a2bac4cc4` |
| 40 | `e0ac2b1b3b9748ac` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 41 | `6e310be0193643c1` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 42 | `06600b4faac146c5` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 43 | `e8b052dd2db542f9` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 44 | `0df22f3810974bea` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 45 | `397118a140c44f47` | failed_attempt | failed | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `11ce7469245afab0` | — |
| 46 | `03410886d1f64fa7` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `11ce7469245afab0` | — |
| 47 | `321caeb581e54d3b` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 48 | `8181fa3cbf394466` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 49 | `e815aee4f01b4146` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 50 | `61a7829c9f7d4fac` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 51 | `d8dc7e7c109342c1` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 52 | `67ad070efc0d4b7b` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 53 | `159cfe0708fb49c6` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
| 54 | `aad7935a2bac4cc4` | current_formal | success | 41 | 2021-01-04~2024-12-31 | 2025-01-02~2026-11-09 | 7 档 | all | `5bc9252086c515e2` | — |
### 5.1 35 条 `legacy_replayable` 去重后只有 9 组唯一配置

35 条按 `config_hash` 分组，实为 **9 个唯一参数组合**，其余是同一配置的重复执行：

| 组 | config_hash | 条数 | 代码数 | 池模式 | 网格 | 区间 | 代表 ID |
| ---: | --- | ---: | ---: | --- | --- | --- | --- |
| G1 | `b6b1babace517bdc` | 18 | 6 | representative | 7 档 | 2021-01-04~2024-12-31 / 2025-01-02~2026-11-09 | `7d884a1a03d94915` |
| G2 | `b1de1d7323a8a35d` | 5 | 6 | representative | 3 档 `[5,20,60]` | 同上 | `c84356bd50ca4bb5` |
| G3 | `177a329b6fd72cec` | 5 | 6 | representative | 3 档 `[10,30,120]` | 同上 | `2b21ca9b2c434444` |
| G4 | `86e4b4e8bac296ad` | 2 | 6 | representative | 7 档 | 同上 | `f9898c695b394808` |
| G5 | `4457e246afad6e79` | 1 | 41 | all | 7 档 | 同上 | `e725034e46ff47e5` |
| G6 | `11ce7469245afab0` | 1 | 41 | all | 7 档 | 同上 | `b6e1155d19ba4b6a` |
| G7 | `9c245d882cb1cc72` | 1 | 6 | representative | 7 档 | 2021-06-01~2024-12-31 / 2025-01-02~2026-11-09 | `c5589f7dcd1a4a5d` |
| G8 | `88d40b3069c50f0a` | 1 | 6 | representative | 7 档 | 2021-01-04~2024-12-31 / 2025-06-03~2026-11-09 | `838a58fa5f3b4025` |
| G9 | `39bac25b0ec4ce91` | 1 | 6 | representative | 7 档 | 2021-01-04~2024-12-31 / 2025-01-02~2026-11-09 | `b3f1e2c89ebc4b95` |
| | | **35** | | | | | |

### 5.2 参数恢复方式（不猜默认值）

validation 记录的参数**只存在于 `config_hash` 里**。恢复的唯一诚实做法是：
把候选参数代入哈希函数，**完全命中**才算证明，否则判不可证明。

命中即证明全部参数等于候选值（含默认值那一批），因为哈希覆盖了
`_VALIDATION_FIELDS_CURRENT` 的 28 个字段：

```
strategy_name, strategy_version, is_start, is_end, oos_start, oos_end,
initial_cash, execution_price, max_defer_days, risk_free_rate,
annualization, commission_rate, min_commission, slippage_bps,
rebalance_tolerance, indicator_version, ma_window_grid, wf_grid,
pool_mode, train_months, test_months, step_months, regime_proxy_code,
regime_ma_window, min_validation_days, exclude_insufficient,
min_coverage_ratio, notes
```

同时尝试历史的 26 字段集（无 `regime_ma_window` / `min_validation_days`），
`pool_mode` 试 `all` 与 `representative`，日期试「原值」与「月初值」。

### 5.3 哈希可重建性实测

用 `app/replay/runner.py::build_validation_config()` 从 `resolved_params`
重建 `ValidationConfig` 再算 `params_hash()`：

| 代表 ID | 重建 hash | 记录 hash | 一致 |
| --- | --- | --- | --- |
| `7d884a1a03d94915` | `b6b1babace517bdc` | `b6b1babace517bdc` | ✅ |
| `c84356bd50ca4bb5` | `b1de1d7323a8a35d` | `b1de1d7323a8a35d` | ✅ |
| `2b21ca9b2c434444` | `177a329b6fd72cec` | `177a329b6fd72cec` | ✅ |
| `f9898c695b394808` | `b6b1babace517bdc` | `86e4b4e8bac296ad` | ❌ |
| `e725034e46ff47e5` | `11ce7469245afab0` | `4457e246afad6e79` | ❌ |
| `b6e1155d19ba4b6a` | `11ce7469245afab0` | `11ce7469245afab0` | ✅ |
| `c5589f7dcd1a4a5d` | `9c245d882cb1cc72` | `9c245d882cb1cc72` | ✅ |
| `838a58fa5f3b4025` | `88d40b3069c50f0a` | `88d40b3069c50f0a` | ✅ |
| `b3f1e2c89ebc4b95` | `39bac25b0ec4ce91` | `39bac25b0ec4ce91` | ✅ |

**9 组中 7 组可用当前 `ValidationConfig` 完全重建，2 组不能**：

| 组 | 原因 |
| --- | --- |
| G4 `f9898c695b394808` | 记录 hash 由 **historical 26 字段集**命中；当前 `ValidationConfig` 多了 `regime_ma_window` / `min_validation_days` 两个字段，重建时带入默认值 250 / 120，哈希因此不同。**参数本身已被证明**，只是当前构造器无法复现旧哈希。 |
| G5 `e725034e46ff47e5` | 同上，historical 字段集命中。 |

这两组的 `resolved_params` 里确实缺 `regime_ma_window` / `min_validation_days`
两个键（因为历史字段集不含它们），重放时必须显式补这两个值——
按项目当时的默认（250 / 120）补，属**有证据的补**，不是猜。

### 5.4 三条 `failed_attempt`（逐条）

| validation_id | 失败原因 | 参数状态 | 处置 |
| --- | --- | --- | --- |
| `c99a2a75b7e646c5` | 样本内没有任何可用参数组合（44 只池，hash `994f0f5410491661` 不可证明） | `config_hash_unproven` | 不可重放，保留原样 |
| `03bf88593cd54841` | 手动中断：性能调优后重跑（41 只池，同一 hash） | `config_hash_unproven` | 不可重放，保留原样 |
| `397118a140c44f47` | 重放记录会计版本异常：`None`（3A.3.2.3.3 首次执行，口径标记缺失） | hash `11ce7469245afab0` **可证明** | 这是重放尝试本身失败，不是待重放源记录 |

`397118a140c44f47` 需要单独说明：它的参数其实是可证明的（与
`32aead3291734f91` 同一 hash），但它**本身就是一次重放尝试的产物**，
失败原因是写库时会计版本字段为空。它的正确处置是：
作为 `failed_attempt` 保留，**不重放它**，因为它没有独立的历史价值——
它对应的源记录 `32aead3291734f91` 已经成功重放到 `03410886d1f64fa7`。

---

## 6. 关键发现：重复执行远多于独立实验

### 6.1 `current_formal` 14 条实为 2 个配置

| config_hash | 该 hash 全表条数 | 其中 `current_formal` | 对应源记录 |
| --- | ---: | ---: | --- |
| `5bc9252086c515e2` | 14 | 13 | `c46fa37b932944c2`（replayed，1 条仍为 legacy） |
| `11ce7469245afab0` | 4 | 1 | `32aead3291734f91`（replayed） |

`5bc9252086c515e2` 的 14 条里，`input_hash` 分 4 种：
`6da51a1c462b7c65` ×10、`2ac80bcdfb5459c5` ×2、
`5f8a4c05613552fa` ×1、`63d62a67a797c55b` ×1。
其中 10 条 `6da51a1c462b7c65` 的 OOS 收益全部为 `0.2011455307731449`
——**同一配置重复跑出的同一结果**。

`11ce7469245afab0` 的 4 条分别是：
`b6e1155d19ba4b6a`（legacy）、`32aead3291734f91`（replayed）、
`397118a140c44f47`（failed_attempt，会计版本为 None）、
`03410886d1f64fa7`（current_formal）。

### 6.2 `legacy_replayable` 35 条实为 9 个配置

G1 一组 18 条，`input_hash` 有 3 种，OOS 收益 `0.214356` / `0.214967` / `0.224288`。
差异来自当时的代码版本或数据状态，不是参数差异（`config_hash` 相同）。

### 6.3 对重放计划的意义

如果按「记录条数」安排重放，35 条 legacy 会跑 35 次；
按「唯一配置」只要跑 9 次，且其中 G1/G2/G3 的重复记录结果可互相验证一致性。

---

## 7. 推荐第一批重放记录

排序原则：**先小后大、先能验证后只能跑、先有对照后有空白**。

| 优先级 | 记录 | 类型 | 理由 |
| ---: | --- | --- | --- |
| 1 | `8412fc1cefb4437e` | backtest `buy_and_hold` | 唯一参数 100% `recorded` 的 backtest；1 只标的、单策略、无网格，跑一次最快；已有 `ac8f4cc7cf234d7e → 355948ec40224eb5` 的成功重放可作口径对照 |
| 2 | `b3f1e2c89ebc4b95`（G9） | validation | 6 只池、7 档网格、单配置，`resolved_params` 与当前构造器完全一致（hash 可重建），是最干净的 legacy 验证样本 |
| 3 | `f9898c695b394808`（G4） | validation | 与 G9 同为 6 只池 / 7 档，但 hash 走 historical 字段集，正好用来验证「历史字段集重放」这条路径 |
| 4 | `c5589f7dcd1a4a5d`（G7） | validation | 样本内起点 `2021-06-01`（晚 5 个月），覆盖「短样本内」分支 |
| 5 | `838a58fa5f3b4025`（G8） | validation | 样本外起点 `2025-06-03`，覆盖「短样本外」分支 |
| 6 | `7d884a1a03d94915`（G1） | validation | 18 条重复组，跑 1 条即可代表；但它是 `conclusion=不通过`，价值低于前 5 个 |

**不建议第一批就碰的**：

- `e725034e46ff47e5`（G5）/ `b6e1155d19ba4b6a`（G6）：41 只池、7 档网格，
  单次运行最久；且 G5 需补两个历史字段的默认值，先确认前 5 个跑通再上。
- 3 条 `failed_attempt`：不重放。
- 2 条 `replayed`：已重放，不重复执行。

### 7.1 第一批的预期成本

| 记录 | 池大小 | 网格 | 估算相对耗时 |
| --- | ---: | ---: | --- |
| `8412fc1cefb4437e` | 1 | — | 1× |
| `b3f1e2c89ebc4b95` | 6 | 7 | ~40× |
| `f9898c695b394808` | 6 | 7 | ~40× |
| `c5589f7dcd1a4a5d` | 6 | 7 | ~40× |
| `838a58fa5f3b4025` | 6 | 7 | ~40× |
| `7d884a1a03d94915` | 6 | 7 | ~40× |

参照：`c46fa37b932944c2`（41 只 / 7 档）单次约 30 分钟。
6 只池理论上是其 1/7 量级，单次约 4~5 分钟。

---

## 8. 数据库前后对照

本阶段**未发生任何数据库结构或数据变更**。

| 表 | 清点前 | 清点后 | 变化 |
| --- | ---: | ---: | --- |
| `validation_runs` | 54 | 54 | 0 |
| `backtest_runs` | 12 | 12 | 0 |
| `validation_backtest_runs` | 361 | 361 | 0 |
| `validation_regime_stats` | 28 | 28 | 0 |
| `validation_stress` | 364 | 364 | 0 |
| `validation_windows` | 415 | 415 | 0 |
| `validation_grid` | 376 | 376 | 0 |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |
| `etf_indicator_daily` | 350,292 | 350,292 | 0 |
| `replay_attempts` | 11 | 11 | 0 |
| `corporate_action_applications` | 6,910 | 6,910 | 0 |
| `dividend_receivables` | 3,274 | 3,274 | 0 |
| `audit_sparse_applications` | 0 | 0 | 0 |
| `audit_sparse_receivables` | 0 | 0 | 0 |

关键内容指纹：

| 项 | 值 |
| --- | --- |
| `validation_runs` 内容指纹 | `9c40fcbf2e7b010c65a2fa4b62313fe6` |
| `backtest_runs` 内容指纹 | `449be0fda8b7c24ddca7f6a7ae6ac3b3` |
| 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| `PRAGMA integrity_check` | ok |

---

## 9. 本轮实际执行的检查

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 盘点脚本 | `python scripts/audit_replay_history.py` | 正常输出 66 条，分类合计校验通过 |
| JSON 导出 | `python scripts/audit_replay_history.py --json reports/phase3A3_2_3_5_replay_inventory.json` | 221,542 字节 |
| 哈希可重建性 | `build_validation_config()` → `params_hash()` | 9 组中 7 组一致 |
| 数据库完整性 | `PRAGMA integrity_check` | ok |
| 行情指纹 | `fingerprint_from_db()` | `d54727c0…`，116,609 行，未变 |
| 全量 pytest | `python -m pytest -q` | **688 passed / 0 failed / 0 skipped** |

全量 pytest 在清点前后各跑一次，均为 688 passed——本轮未改任何代码，
测试数量与上一阶段终值一致。

---

## 10. 本轮未做的事（边界声明）

| 禁止项 | 执行情况 |
| --- | --- |
| 执行历史回测 | **未执行** |
| 执行历史验证重放 | **未执行** |
| 修改历史记录 | **未修改**（表行数与内容指纹前后相同） |
| 修改策略 / 撮合 / 会计 / 指标算法 | **未修改** |
| 修改行情 / 公司行为 / 历史数据 | **未修改**（行情指纹相同） |
| 为可重放而猜参数 | **未猜**（9 条 backtest 不可重放，逐条写明缺失项） |
| 删除历史记录 | **未删除** |
| 进入 3A.3.3 / 3B | **未进入** |

---

## 11. 尚待确认的问题

1. **G4 / G5 两组的哈希重建不一致需要定调。**
   这两组参数已被 historical 字段集证明，但当前 `ValidationConfig`
   带上了 `regime_ma_window` / `min_validation_days` 两个新字段，
   重建出的哈希对不上。重放时是否允许「按历史字段集 + 补齐两个默认值」执行，
   需要下一阶段明确。本轮**只记录**，未做决定。

2. **重复执行组（G1 18 条、`5bc9252086c515e2` 13 条）是否要全部重放。**
   本报告建议每组只跑 1 条代表，但「重放到什么程度算清账」没有既定标准，
   需要下一阶段确认。

3. **9 条不可重放 backtest 的最终归属。**
   它们的参数确实丢了，但模型版本、数据版本都是可查的。
   是永久标 `non_replayable`，还是补一个「只能定性复核」的中间态，
   本轮未做决定。

4. **`397118a140c44f47` 的处理。**
   它是一次失败的重放尝试，源记录已有成功重放。建议保留为 `failed_attempt`
   不重放，但这条建议需要下一阶段确认。

---

## 12. 结论

| 完成标准 | 状态 | 证据 |
| --- | --- | --- |
| 所有历史记录均已盘点 | ✅ | 66 条（12 + 54），§4 §5 逐条列出 |
| 每条记录都有明确分类 | ✅ | §2 五分类统计，§4 §5 逐条标注 |
| 可重放记录都有完整参数依据 | ✅ | §4.2 backtest 全字段 `recorded`；§5.2 哈希证明机制；§5.3 重建实测 |
| 不可重放记录都有具体原因 | ✅ | §4.1 九条逐条；§5.4 三条逐条 |
| 已重放的两条 P0 记录没有被重复执行 | ✅ | §3.3 核实结论；本轮未执行任何重放 |
| 数据库记录数量和核心内容前后没有变化 | ✅ | §8 全部 0 变化，指纹相同 |
| 没有执行任何历史重放 | ✅ | 本报告全部为只读查询 |

**本阶段只清点，不重放。等待验收后再执行下一阶段。**

---

## 13. 附：清点数据文件

| 文件 | 说明 |
| --- | --- |
| `reports/phase3A3_2_3_5_replay_inventory.json` | 本次清点的机器可读快照（66 条完整字段） |

该文件可在验收时用于复算本报告全部数字。
