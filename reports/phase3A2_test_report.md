# 阶段3A.2 测试报告

- 执行时间：2026-11-11
- 执行环境：Windows / Python 3.11.2 / `.venv` / SQLite
- 执行命令：

```powershell
cd D:\ymy\jj-agent
PYTHONUTF8=1 .venv\Scripts\python.exe -m pytest -q
```

## 1. 总体结果

| 项目 | 数值 |
| --- | ---: |
| 测试总数 | 209 |
| 通过 | 209 |
| 失败 | 0 |
| 警告 | 1（Starlette/httpx 弃用提示，非失败） |
| 耗时 | 26.36s |
| 日志 | `logs/pytest_phase3a2.log` |

## 2. 与上一阶段对比

| 阶段 | 测试数 | 本阶段结果 |
| --- | ---: | --- |
| 阶段3A.1.1 | 154 | 全部通过，无回退 |
| 阶段3A.2 新增 | 55 | 全部通过 |
| 合计 | 209 | 209 passed |

未删除任何原有测试，未降低任何断言标准。

## 3. 新增测试明细（`tests/test_validation.py`）

### 配置校验（6 项）

| 测试 | 验证内容 |
| --- | --- |
| `test_config_rejects_overlapping_is_and_oos` | 样本内外重叠必须报错 |
| `test_config_rejects_inverted_range` | 区间倒置必须报错 |
| `test_config_rejects_negative_costs` | 负成本必须报错 |
| `test_config_params_hash_is_reproducible` | 配置哈希可复现且对参数敏感 |
| `test_config_default_grid_comes_from_real_indicator_columns` | 参数网格取自真实指标列 |
| `test_coverage_ok_threshold` | 覆盖阈值边界 |

### 时间切分（11 项）

包括无重叠、IS 全部早于 OOS、保持日历顺序、样本不足拒绝、空日历拒绝、重复日期拒绝、
配置日期落在非交易日时使用真实交易日、预热期说明、覆盖过滤。

### Walk-Forward（8 项）

包括窗口前进、窗口不重叠、数据边界截断、样本不足标记、步长不一致拒绝、空日历拒绝、
选参优先级、选参函数签名只能接收训练结果。

### 市场环境（4 项）

包括修改 T 日之后价格不改变 T 日分类（无未来函数）、样本不足标记 unclassified、
空序列报错、样本不足统计标记。

### 参数敏感性（6 项）

包括展示全部组合、少数组合盈利时提示过拟合、无稳定相邻档位时提示、结果可复现、
空网格拒绝、样本外结果不影响选参。

### 基准（5 项）

包括必需基准齐备、缺代理标的不伪造、空池拒绝、数据不全标记、公共区间取交集。

### 压力测试（5 项）

包括必需场景齐备、成本倍数只改配置、滑点倍数正确、未知场景拒绝、行情变更检测。

### 存储与可复现（9 项）

包括迁移幂等、历史记录不覆盖、同 id 只更新自身、子记录持久化、失败状态记录、
`input_hash` 可复现、行情指纹可检测变化、结论只有三类、样本外为负不给通过。

## 4. 关键约束的测试证据

| 约束 | 测试 | 结果 |
| --- | --- | --- |
| 样本内外无重叠 | `test_split_produces_disjoint_ranges` | 通过 |
| 不打乱交易日 | `test_split_preserves_calendar_order` | 通过 |
| 预热期不计收益 | `test_warmup_note_excludes_warmup_returns` | 通过 |
| WF 无未来泄漏 | `test_walkforward_windows_advance_and_do_not_overlap` | 通过 |
| 选参不读样本外 | `test_select_best_param_signature_only_accepts_train_results` | 通过 |
| 环境分类无未来函数 | `test_regime_classification_has_no_lookahead` | 通过 |
| 网格可复现 | `test_sensitivity_reproducible` | 通过 |
| 基准区间对齐 | `test_benchmark_common_range_is_intersection` | 通过 |
| 压力测试不改行情 | `test_stress_detects_data_mutation` | 通过 |
| 失败有状态与原因 | `test_validation_failed_status_recorded` | 通过 |
| `input_hash` 可复现 | `test_input_hash_reproducible_and_sensitive` | 通过 |
| 历史记录不覆盖 | `test_validation_history_not_overwritten` | 通过 |

## 5. 冒烟测试

### API

```
python scripts\smoke_validation_api.py
```

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations?limit=5` | 200 |
| `GET /api/validations/{id}` | 200 |
| `GET /api/validations/not_exist` | 404（期望） |

### Streamlit

`dashboard/pages/4_策略验证.py` AppTest：**0 异常**，5 个标签页正常渲染。

## 6. 数据库检查

| 项目 | 结果 |
| --- | --- |
| `PRAGMA integrity_check` | ok |
| 行情行数 | 116,609（验证前后一致） |
| 指标行数 | 350,292（未变） |
| 复权快照 | 139（未变） |
| 历史回测 run | 11（未变） |
| 新增验证 run | 5 |
| 新增验证窗口 | 16 |
| 新增参数网格 | 16 |
| 新增压力场景 | 14 |
| 行情指纹（行数/收盘和/量和） | 验证前后完全一致 |

## 7. 测试环境说明

- 全部新增测试使用 `tmp_path` 临时 SQLite，或纯内存数据构造，不污染正式库。
- `tests/conftest.py` 的 session 级正式库守卫在测试结束时校验 mtime/size，
  若测试改动正式库会直接失败。
- 本次未出现守卫失败。

## 8. 未验证项说明

- `sparse_data` / `insufficient` 两个数据类压力场景在实跑中标记 `skipped`，
  其效果由覆盖过滤与区间校验覆盖，未单独构造回测用例。
- 全池 MA5 组合在实跑中失败（引擎现金精度边界），未在测试中构造该精确场景。
- 未测试并发运行两个验证任务的场景。
