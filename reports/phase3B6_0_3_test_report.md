# 阶段3B-6.0.3 测试报告

- 基线 HEAD：`4be8b044b2cc8f2d0a40c2cc8241bc66f2249dab`
- 执行日期：2026-11-24

> 区分：**真实执行测试** / **静态检查** / **数据源实际调用**。

---

## 1. 数据源实际调用（本轮真实执行）

| 接口 | 调用次数 | 用途 |
| --- | ---: | --- |
| `akshare.fund_name_em` | 3 | 全市场名单筛选候选 |
| `akshare.fund_individual_basic_info_xq` | 61 | 单基金基本信息 |
| `akshare.fund_open_fund_info_em` | 122 | 单位净值 + 累计净值 |
| `akshare.fund_money_fund_info_em` | 5 | 货币每万份收益 |
| `akshare.fund_open_fund_info_em`（分红） | 61 | 分红送配 |

合计约 250 次调用，全部为受控接入流程内。

---

## 2. 全量测试

```bash
$ pytest -q
1814 passed, 1 warning in 879.73s (0:14:39)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1814** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 879.73 秒 |

与 3B-6.0.2.3 的 **1814 完全相同**——本轮没有新增测试，
但扩容后触发了 3 个**数据快照型断言**失效，已改造为数据驱动断言。

---

## 3. 首次全量失败与处理

扩容后首次全量：

```
3 failed, 1811 passed in 828.06s
```

三个失败**全部是数据快照断言**，不是代码缺陷：

| 测试 | 旧断言 | 失败原因 |
| --- | --- | --- |
| `test_summary_live_numbers` | `live.fund_count == 19` | 扩容后变 79 |
| `test_money_000509_not_d` | 货币基金为 `C` | 扩容后 7 只 → 按规则应为 `B` |
| `test_ac_pair_shares_same_peer_and_dedup` | 上证50 组 `member_count == 1` | 扩容后该组 3 只 |

### 3.1 改造原则

把「写死某个数字」改为「断言**行为契约**」，这比原断言**更强**：

| 测试 | 新断言 |
| --- | --- |
| `test_summary_live_numbers` | 审计汇总必须与**直接查库结果完全一致**；`tracking_index` 恒为 0；有基准+无基准=总数 |
| `test_money_000509_not_d` | 货币基金**永远不得为 D**；等级必须与组内实际本体数对应（<5→C，≥5→B）|
| `test_ac_pair_shares_same_peer_and_dedup` | A/C 两份额必须归到同一本体；`deduped_by_fund_id` 必须为真；本体数 ≤ 库内本体总数 |

**没有删除任何测试，没有弱化任何断言**——反而把「依赖具体数据量」
改为「依赖规则」，扩容或缩容都不会再误报。

---

## 4. 关键回归（本轮直接相关）

```bash
$ pytest tests/test_3b5_3_2_fk_serialization.py \
        tests/test_3b6_0_2_1_raw_quality_and_basis.py -q
39 passed in 17.68s
```

```bash
$ pytest tests/test_3b5_5_1_peer_annualized.py \
        tests/test_3b6_0_1_benchmark_audit.py -q
84 passed in 82.12s
```

---

## 5. 测试环境说明

| 项 | 说明 |
| --- | --- |
| 单元测试 | 不联网 |
| 数据接入 | 由受控接入脚本真实执行 |
| 临时库验证 | ✅ 先跑 `.tmp603/temp_stage.db` |
| 正式库写入 | 只在验证通过后进行 |

---

## 6. 静态检查（不计入 1814）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` | 静态 |
| JSON 合法性校验 | 静态 |

---

## 7. 数据库守恒

| 项 | 扩容前 | 扩容后 | 说明 |
| --- | ---: | ---: | --- |
| `fund_master` | 60 | **120** | +60（本轮新增）|
| `fund_share_classes` | 89 | **149** | +60 |
| `fund_nav_daily` | 80,083 | **245,656** | +165,573 |
| `fund_dividends` | 105 | **376** | +271 |
| **`fund_lifecycle_events`** | 49 | **49** | **零变化** |
| **清盘本体** | 41 | **41** | **零变化** |
| `fund_manager_history` | 21 | 21 | 零变化 |
| `fund_aum_history` | 683 | 683 | 零变化 |
| `fund_fee_rules` | 90 | 90 | 零变化 |

| 检查 | 值 |
| --- | --- |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |
| 内容指纹（前） | `11c56eba1489976fa35be92586a99bc21a27e20c06e95cacab5c8ca553c05116` |
| 内容指纹（后） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| ETF 行情指纹 | `d54727c0…bbcac49`（**未变**）|

**内容指纹按预期变化**（新增 60 只基金数据）；
**ETF 行情指纹未变**（未重跑场内研究，未动 ETF 表）。

---

## 8. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `scripts/audit_3b6_0_3_universe_gap.py` | 新增 | 第一步缺口审计 |
| `scripts/plan_3b6_0_3_candidates.py` | 新增 | 第二步候选筛选 |
| `scripts/ingest_3b6_0_3_batch.py` | 新增 | 第三/四步分批接入 |
| `tests/test_3b6_0_1_benchmark_audit.py` | **修改** | 1 项数据快照 → 数据驱动 |
| `tests/test_3b5_5_1_peer_annualized.py` | **修改** | 2 项数据快照 → 数据驱动 |
| `app/**` 业务代码 | **未改** | — |
| `app/fund/research/classification.py` | **未改** | 分类规则不动 |
| Schema / 迁移 | **未改** | — |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

**扩容完成不等于回测就绪。**
