# 阶段3B-6.0.4 测试报告

- 基线 HEAD：`f64b7e554d7303c523bb6ba9ee84550b2e0a7a9d`
- 执行时间：2026-11-24 13:46

> **严格区分**：真实执行的 pytest / 静态检查 / 数据源调用 / 报告生成。

---

## 1. 全量 pytest（真实执行）

```bash
$ pytest -q
1864 passed, 1 warning in 739.96s (0:12:19)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1864** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 739.96 秒 |

**演进**：1814（3B-6.0.3）→ **1864**（+50 本轮新增）

---

## 2. 专项测试（真实执行）

```bash
$ pytest tests/test_3b6_0_4_peer_comparison.py \
        tests/test_3b6_0_4_share_cost_and_groups.py -q
50 passed in 5.30s
```

---

## 3. 历史回归（真实执行）

```bash
$ pytest tests/test_3b6_0_1_benchmark_audit.py \
        tests/test_3b6_0_1_1_index_verify.py \
        tests/test_3b6_0_2_index_layer.py \
        tests/test_3b6_0_2_1_raw_quality_and_basis.py \
        tests/test_3b6_0_2_2_effective_observations.py \
        tests/test_3b6_0_2_3_finite_positive_close.py -q
185 passed in 91.54s
```

---

## 4. 新增测试覆盖（50 项）

### 4.1 `test_3b6_0_4_peer_comparison.py`（32 项）

| 类别 | 覆盖点 |
| --- | --- |
| 区间收益 | 端点精确命中、起点/终点缺失 → insufficient_data |
| 缺口处理 | 跨缺口拒绝计算、无缺口正常计算 |
| 年化 | 不足 365 天不年化、2 年正常年化、None 收益拒绝 |
| 共同区间 | 正常交集、空交集、单基金不足、不同成立时间 |
| 滚动窗口 | 短序列不足、长序列正常、跨缺口跳过 |
| 稳定性 | 单窗口依赖标记、剔除最佳窗口后反转、不足透传 |
| 超额阻断 | price/unknown 阻断、total/net 通过、无基准阻断 |
| 复合基准 | 缺权重、缺成分、单成分、完整可复现 |
| 命名边界 | peer_relative_is_not_alpha 恒真、无未来保证声明 |
| 最终闸门 | 口径核实但无序列仍阻断 |

### 4.2 `test_3b6_0_4_share_cost_and_groups.py`（18 项）

| 类别 | 覆盖点 |
| --- | --- |
| 组可用性 | 货币可验证、债券 unknown 不可验证、指数族判定 |
| 组隔离 | <2 排除、<5 仅描述、≥5 可比、unknown 永不比 |
| 组键隔离 | 不同指数组键不同 |
| 赎回费阶梯 | 命中档位、无阶梯 unknown、无匹配不插值、重叠冲突拒绝 |
| 成本框架 | 缺销售服务费不给结论、齐全可算、永不输出建议 |
| 支付宝费率 | 恒 unknown |
| 空输入 | no_shares |

### 4.3 覆盖任务书的 14 项要求

| # | 要求 | 覆盖测试 |
| ---: | --- | --- |
| 1 | A/C 归并与独立份额成本 | `test_ac_pair...`、成本框架 5 项 |
| 2 | 不同成立时间共同区间 | `test_different_inception_dates_use_common_window` |
| 3 | 净值缺口处理 | `test_gap_blocks_window_return` 等 3 项 |
| 4 | 累计净值 vs 单位净值口径 | 口径策略断言 |
| 5 | 分红不完整处理 | 分红修复关闭的断言 |
| 6 | 货币基金独立口径 | 组可用性 + 引擎 money 分支 |
| 7 | 不同同类组隔离 | `test_group_isolation_...` 2 项 |
| 8 | 基准口径 unknown 阻断 | `test_unknown_basis_blocks_excess_return` |
| 9 | 复合基准不完整阻断 | 4 项复合基准测试 |
| 10 | 滚动窗口不足样本 | `test_rolling_windows_insufficient...` |
| 11 | 超额收益不可计算状态 | 4 项 excess_return 测试 |
| 12 | 质量评级与可追溯性 | `group_usability` 全套 |
| 13 | 正式数据库只读保护 | `conftest.production_db_guard`（session 级） |
| 14 | 历史回归 | 185 项 3B-6.0.x 回归 |

---

## 5. 静态检查（**不计入** 1864）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | 静态 |
| JSON 合法性校验 | 静态 |

**这些不是测试，不描述为「测试通过」。**

---

## 6. 数据源调用

| 项 | 本轮 |
| --- | --- |
| 外部数据源调用 | **0 次** |
| 说明 | 本阶段纯离线研究，不重新采集 |

---

## 7. 报告生成（真实执行）

| 脚本 | 产物 |
| --- | --- |
| `analyze_all_groups()` | 26 组结果，耗时 133 秒 |
| `analyze_share_cost()` × 9 | 9 个本体成本框架 |
| `evaluate_excess_return()` | 逐指数阻断判定 |

---

## 8. 正式数据库只读验证

| 项 | 数值 |
| --- | ---: |
| 内容指纹（本轮前） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| 内容指纹（本轮后） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| **是否变化** | **✅ 未变化** |
| ETF 指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

| 表 | 行数 | 与 3B-6.0.3 对比 |
| --- | ---: | --- |
| `fund_master` | 120 | 未变 |
| `fund_share_classes` | 149 | 未变 |
| `fund_nav_daily` | 245,656 | 未变 |
| `fund_dividends` | 376 | 未变 |
| `fund_lifecycle_events` | 49 | 未变 |
| `fund_manager_history` | 21 | 未变 |
| `fund_aum_history` | 683 | 未变 |
| `fund_fee_rules` | 90 | 未变 |

**正式数据库本轮零写入。**

---

## 9. 代码改动清单

| 文件 | 类型 | 行数量级 |
| --- | --- | ---: |
| `app/fund/research/peer_comparison.py` | **新增** | ~280 |
| `app/fund/research/excess_return.py` | **新增** | ~180 |
| `app/fund/research/share_cost.py` | **新增** | ~200 |
| `app/fund/research/peer_engine.py` | **新增** | ~250 |
| `tests/test_3b6_0_4_peer_comparison.py` | **新增** | 32 项 |
| `tests/test_3b6_0_4_share_cost_and_groups.py` | **新增** | 18 项 |
| `app/**` 既有模块 | **未改** | — |
| Schema / 迁移 | **未改** | — |

**既有测试文件零修改，零删除，零弱化。**

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
| `excess_return_status` | **`not_available`** |

**门禁三值保持不变，未强行打开。**
