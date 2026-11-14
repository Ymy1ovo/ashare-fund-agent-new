# 阶段3A.3.2.3.1 历史回测记录盘点报告

- 生成时间：2026-11-14
- 基线 HEAD：`f99c6ea379b297ff1bf141823e88f4413451ee5b`
- 数据来源：`data/fund_agent.db` 实际字段，非历史报告推测
- 复现命令：`python scripts/audit_replay_history.py`

## 1. 总量与分类

| 项 | 数量 |
| --- | ---: |
| `backtest_runs` 总数 | **12** |
| `current_formal` | **1** |
| `replayed` | **1** |
| `legacy` | **1** |
| `unknown_legacy` | 0 |
| `non_replayable` | **9** |
| 待重放 | **1** |
| 已重放 | **1** |

分类合计 1+1+1+0+9 = 12 = 总数，`sum_matches_total = True`。

> 说明：本轮实际重放了 `ac8f4cc7cf234d7e`（见 §5），因此该条从 `legacy` 变为
> `replayed`，同时新增 1 条 `current_formal` 重放记录。本轮开始前是 11 条、
> `legacy` 2 条、`non_replayable` 9 条。

## 2. 分类规则

| 分类 | 判定条件 | 依据字段 |
| --- | --- | --- |
| `current_formal` | `accounting_version == 'ca-v2-receivable'`；列缺失时才看 `summary_json` 同时写着 `accounting_basis=formal_receivable` + `formal_valuation=true` | `accounting_version` |
| `replayed` | `replay_attempts` 中存在该源记录 `status=success` 的行 | `replay_attempts` |
| `legacy` | `accounting_version == 'legacy_corporate_action_accounting'` 且全部关键参数可读 | `accounting_version` + `config_json` |
| `unknown_legacy` | `accounting_version` 为空或非已知值 | `accounting_version` |
| `non_replayable` | 缺少关键参数（策略参数 / 成本 / ETF 池 / 快照） | `config_json` |

判定顺序：`replayed` → `current_formal` → `unknown_legacy` → `non_replayable` → `legacy`。

## 3. 逐条盘点（12 条）

| run_id | 策略 | 区间 | ETF | 初始资金 | 执行价 | accounting_version | input_hash | 分类 |
| --- | --- | --- | ---: | ---: | --- | --- | --- | --- |
| `7181d2a6ed3f4555` | buy_and_hold | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `1816a3088cb9708a` | non_replayable |
| `d08db2c030a64458` | ma_trend | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `6427322117905b63` | non_replayable |
| `2ecc9c0803174978` | ma_trend | 2024-01-02~2026-11-09 | 46 | 1,000,000 | open | legacy | `3ecaadf82c2770a8` | non_replayable |
| `6a7fe99ac55a4639` | ma_trend | 2024-01-02~2026-11-09 | 46 | 1,000,000 | open | legacy | `dedf697290ef26c8` | non_replayable |
| `ac8f4cc7cf234d7e` | buy_and_hold | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `783858ffd0a628c5` | **replayed** |
| `dbf4bc0e46104b23` | ma_trend | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `46f0329230d26195` | non_replayable |
| `8412fc1cefb4437e` | buy_and_hold | 2024-01-02~2026-11-09 | 1 | 1,000,000 | open | legacy | `5bd01d68a81b0a1b` | **legacy** |
| `c72cc00273624760` | ma_trend | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `46f0329230d26195` | non_replayable |
| `90c76130c8884212` | ma_trend | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `46f0329230d26195` | non_replayable |
| `08a4c7f1529b42e2` | ma_trend | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `46f0329230d26195` | non_replayable |
| `cabbfe77035d40f3` | ma_trend | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | legacy | `1972a83fc569e5c6` | non_replayable |
| `355948ec40224eb5` | buy_and_hold | 2024-01-02~2026-11-09 | 5 | 1,000,000 | open | **ca-v2-receivable** | `9a107ccaff142b43` | **current_formal** |

## 4. 9 条 non_replayable 的原因

**根因：`ma_trend` 的 `ma_window` 从未落库。**

11 条历史记录全部写于 `strategy_params` 字段启用之前，`config_json`
里该键恒为 `{}`。`ma_trend` 的真实参数只有 `ma_window`，没有它就无从复现
同一批信号——`--ma-window` 在 `scripts/run_backtest.py` 里是命令行参数，
不是落库字段。

| run_id | 策略 | 缺失项 |
| --- | --- | --- |
| `7181d2a6ed3f4555` | buy_and_hold | `config:rebalance_tolerance` |
| `d08db2c030a64458` | ma_trend | `strategy_param:ma_window`、`config:rebalance_tolerance` |
| `2ecc9c0803174978` | ma_trend | `strategy_param:ma_window`、`config:rebalance_tolerance` |
| `6a7fe99ac55a4639` | ma_trend | `strategy_param:ma_window` |
| `dbf4bc0e46104b23` | ma_trend | `strategy_param:ma_window` |
| `c72cc00273624760` | ma_trend | `strategy_param:ma_window` |
| `90c76130c8884212` | ma_trend | `strategy_param:ma_window` |
| `08a4c7f1529b42e2` | ma_trend | `strategy_param:ma_window` |
| `cabbfe77035d40f3` | ma_trend | `strategy_param:ma_window` |

`7181d2a6ed3f4555` 是 `buy_and_hold`，不需要 `ma_window`，但 `config_json`
里连 `rebalance_tolerance` 都没有（早期版本该字段尚未加入配置），
同样判为不可重放。

**没有做的事**：没有从 `input_hash` 反推窗口、没有用默认 20 兜底、
没有拿报告里的数字猜参数。这三种做法都会产出一条「看起来一样、其实不知道
是不是同一次回测」的记录。

## 5. 本轮真实重放

| 项 | 值 |
| --- | --- |
| 源记录 | `ac8f4cc7cf234d7e`（buy_and_hold，5 只，legacy） |
| 新记录 | `355948ec40224eb5` |
| 源 input_hash | `783858ffd0a628c5` |
| 新 input_hash | `9a107ccaff142b43` |
| 源 accounting_version | `legacy_corporate_action_accounting` |
| 新 accounting_version | `ca-v2-receivable` |
| 新记录 accounting_basis | `formal_receivable` |
| 新记录 formal_valuation | `True` |
| 行情指纹 | 前后一致（`d54727c0…`） |

登记行（`replay_attempts`）已写入，含 `source_record_id`、`replay_record_id`、
两个 `input_hash`、两个 `accounting_version`、`replay_timestamp`。

## 6. 待重放清单（1 条）

| run_id | 策略 | 区间 | ETF | 可重放 |
| --- | --- | --- | ---: | --- |
| `8412fc1cefb4437e` | buy_and_hold | 2024-01-02~2026-11-09 | 1 | 是 |

命令：

```bash
python scripts/replay_3a3_2.py --source 8412fc1cefb4437e
```

## 7. 结论

- 12 条记录全部盘点完毕，分类合计等于总数
- 真正可重放的只有 2 条 `buy_and_hold`；9 条因 `ma_window` 缺失永久不可重放
- 这不是工具缺陷，是历史数据本身的缺陷：当时的回测没有记录策略参数
- 已重放 1 条，待重放 1 条
- 所有历史行未被修改，`integrity_check` ok
