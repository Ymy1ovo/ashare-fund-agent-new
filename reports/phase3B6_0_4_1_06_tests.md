# 阶段3B-6.0.4.1 测试报告

- 本轮基线 HEAD：`a31270683f1417813ad8ac650fc5ebd9be32b79f`
- 执行时间：2026-11-24 14:32

> 严格区分：真实执行 pytest / 静态检查 / 数据源调用 / 报告生成。

---

## 1. 全量 pytest（真实执行）

```bash
$ pytest -q
1902 passed, 1 warning in 797.75s (0:13:17)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1902** |
| 失败 | 0 |
| 错误 | 0 |
| 耗时 | 797.75 秒 |

**演进**：1864（3B-6.0.4）→ **1902**（+38 本轮新增）

---

## 2. 新增专项测试（38 项）

```bash
$ pytest tests/test_3b6_0_4_1_lof_and_grade.py -q
38 passed in 1.09s
```

### 2.1 LOF 识别测试（任务要求全覆盖）

| 测试 | 覆盖要求 |
| --- | --- |
| `test_detect_lof_short_name_only` | 简称含 LOF |
| `test_detect_lof_full_name_only` | **全称含 LOF** |
| `test_detect_lof_both` | 两者均含 |
| `test_detect_lof_neither` | 均不含 |
| `test_detect_lof_chinese_paren` | 中文括号 |
| `test_detect_lof_no_false_positive_from_substring` | **不得误识别** |
| `test_truncated_lof_funds_classified_as_lof` ×5 | **5 只全部正确识别** |
| `test_truncated_lof_not_in_active_equity_or_bond` ×5 | **不得归入其他类** |
| `test_lof_without_full_name_still_flagged` | 全称缺失标注 |
| `test_non_lof_without_full_name_not_guessed` | 缺失时不猜测 |
| `test_lof_index_subtype` | 指数型 → lof/index |
| `test_lof_active_subtype` | 主动型 → lof/active |
| `test_lof_index_peer_key_starts_with_lof` | 组键 lof\|index\| |
| `test_lof_active_peer_key_starts_with_lof` | 组键 lof\|active\| |

### 2.2 质量等级测试

| 测试 | 覆盖要求 |
| --- | --- |
| `test_bond_pure_unknown_14_is_d` | **bond_pure 14 本体 → D** |
| `test_bond_pure_unknown_50_still_d` | **50 本体仍 D** |
| `test_bond_mixed_unknown_is_d` | **bond_mixed → D** |
| `test_active_equity_unknown_is_d` | **active_equity|unknown → D** |
| `test_unknown_family_index_group_is_d_even_with_many_members` | 指数 unknown 组大样本仍 D |
| `test_money_market_7_is_b` | **money_market 7 → B** |
| `test_money_market_3_is_c` / `_1_is_d` | 货币样本量规则 |
| `test_engine_grade_matches_authoritative_rule` | 引擎与权威函数一致 |

### 2.3 报告一致性测试

| 测试 | 覆盖要求 |
| --- | --- |
| `test_report_markdown_and_json_grades_consistent` | **MD 与 JSON 等级一致** |
| `test_bond_keys_must_be_d_in_both_formats` | bond_* 两格式均 D |

### 2.4 真实库验证

| 测试 | 覆盖要求 |
| --- | --- |
| `test_live_bond_pure_unknown_is_d` | 正式库实际数据为 D |
| `test_live_lof_members_all_have_lof_class` | 5 只均为 LOF |
| `test_live_active_equity_800_excludes_truncated_lof` | **中证800 组不含 LOF** |
| `test_live_group_counts_are_data_driven` | 组数不写死 |
| `test_live_no_duplicate_fund_id` | 79 本体按 fund_id 去重 |

---

## 3. 相关回归（真实执行）

```bash
$ pytest tests/ -q -k 'classif or lof or group or peer'
202 passed, 1700 deselected in 118.38s
```

```bash
$ pytest tests/test_3b6_0_4_1_lof_and_grade.py \
        tests/test_3b6_0_4_peer_comparison.py \
        tests/test_3b6_0_4_share_cost_and_groups.py -q
88 passed in 6.16s
```

---

## 4. 既有测试保全

| 项 | 数量 |
| --- | ---: |
| 删除的测试 | **0** |
| 跳过的测试 | **0** |
| 弱化的断言 | **0** |
| 修改的既有测试文件 | **0** |

**3B-5.x 分类回归、3B-6.0.x 全部回归保持原样通过。**

---

## 5. 静态检查（不计入 1902）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` | 静态 |
| JSON 合法性校验 | 静态 |

**不是测试，不描述为「测试通过」。**

---

## 6. 数据源调用

| 项 | 本轮 |
| --- | --- |
| 外部数据源调用 | **0 次** |

---

## 7. 正式数据库只读验证

| 项 | 值 |
| --- | --- |
| 内容指纹（本轮前） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| 内容指纹（本轮后） | `115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4` |
| **是否变化** | **✅ 未变** |
| ETF 指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49` |
| `integrity_check` | **ok** |
| `foreign_key_check` | **0** |

| 表 | 行数 | 与上轮对比 |
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

## 8. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/research/classification.py` | **修改** | 新增 `detect_lof()`，LOF 判定综合全称 |
| `app/fund/research/data_access.py` | **修改** | `load_universe()` SELECT 增加 `fund_full_name` |
| `app/fund/research/lookup.py` | **修改** | `_SELECT` 增加 `fund_full_name` |
| `app/fund/ingest_user_funds/_impl.py` | **修改** | 幂等查询与分类调用带全称 |
| `app/fund/research/peer_engine.py` | **修改** | 新增 `group_quality_grade()`，接权威评级 |
| `app/fund/research/quality.py` | **未改** | 评分规则一行未动 |
| `tests/test_3b6_0_4_1_lof_and_grade.py` | **新增** | 38 项测试 |
| Schema / 迁移 | **未改** | — |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
| `excess_return_status` | **`not_available`** |
