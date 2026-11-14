# 阶段3A.3.2.2.3 非正式口径持久化与异常测试补齐 — 最终修复报告

- 生成时间：2026-11-14
- 基线 HEAD：`70fcb4edb009d2c6b9b64fc05602f076179e0ebe`（阶段3A.3.2.2.2）
- 阶段性质：**最后定向收尾**。不重做 3A.3.2.2.2，不扩大范围。
- 不进入 3A.3.3 / 3B；不开发策略；不修改 MA 参数。

---

## 1. 问题根因

### 1.1 口径标记只在内存里，落盘即丢失

`BacktestResult` 自 3A.3.2.2.2 起携带两个字段：

| 字段 | 正式回测 | `apply_corporate_actions=False` |
| --- | --- | --- |
| `accounting_basis` | `formal_receivable` | `disabled_non_official` |
| `formal_valuation` | `True` | `False` |

但 `app/backtest/storage.py::save_result()` 构造 `summary_json` 时**没有写入这两个字段**。
于是：

```
引擎内存里有标记  →  save_result 丢掉  →  数据库里只有净值，没有口径
                                       →  API / Streamlit 读回来无从判断
                                       →  非正式结果与正式结果不可区分
```

`get_run()` 只是把 `summary_json` 反序列化，所以历史记录和新的非正式记录在
读取端完全同形——这正是「非正式口径被当作正式结果」的实际路径。

### 1.2 验证层存在两处绕过口

| 位置 | 原行为 | 后果 |
| --- | --- | --- |
| `runner._events_digest_for()` | `except Exception: return "unavailable"` | 事件加载失败时输入指纹退化成常量，验证继续跑 |
| `runner._run_backtest()` | 只取 `result.daily/trades/orders`，不看口径 | 非正式口径的回测指标直接进入验证结论 |

第二处更关键：`_run_backtest()` 是验证流程里所有样本内、样本外、Walk-Forward、
基准、压力测试回测的唯一入口。只要它不检查标记，任何拿到非正式结果的路径
都能把数字塞进「通过 / 有条件通过 / 不通过」的结论里。

---

## 2. 修改内容

### 2.1 `app/backtest/storage.py`

`save_result()` 落盘时新增两个 summary 键，并**不允许缺省为正式**：

```python
accounting_basis = getattr(result, "accounting_basis", None)
if not isinstance(accounting_basis, str) or not accounting_basis:
    accounting_basis = "unknown_legacy"      # 不默认 formal_receivable
formal = getattr(result, "formal_valuation", None)
formal = bool(formal) if isinstance(formal, bool) else False
if accounting_basis != "formal_receivable":
    formal = False                            # 口径非正式 → 标记强制为 False
```

返回字典同时带上两字段，调用方不必回查数据库。

注意这个方向：**默认值全部朝向「不正式」**。旧实现如果缺字段就当作正式，
等于把无法证明的口径当成已证明；新实现缺字段 → `unknown_legacy` + `False`。

### 2.2 `app/backtest/api.py`

新增三个常量与三个判定函数：

| 名称 | 值 / 语义 |
| --- | --- |
| `ACCOUNTING_FORMAL` | `formal_receivable` |
| `ACCOUNTING_DISABLED` | `disabled_non_official` |
| `ACCOUNTING_UNKNOWN` | `unknown_legacy`（本字段落盘之前的历史记录） |
| `accounting_basis_of(summary)` | 读口径；缺失 → `unknown_legacy` |
| `formal_valuation_of(summary)` | 读正式性；缺失 → `False` |
| `is_formal_run(summary)` | 两字段必须**同时**满足才为 `True` |

`get_run()` 与 `list_runs()` 都把两字段提到**顶层**返回，
`list_runs()` 额外从 `summary_json` 里提取后丢弃原始串，避免列表接口变胖。

### 2.3 `app/validation/runner.py`

| 改动 | 说明 |
| --- | --- |
| 新增 `_require_formal(result, where)` | 非正式口径 → 抛 `ValidationError` |
| `_run_backtest()` 调用 `_require_formal` | 覆盖样本内网格、样本外、Walk-Forward、基准、压力测试、稀疏数据副本 |
| `_build_regime_payload()` 内的直接引擎调用也加检查 | 该函数绕过 `_run_backtest()`，是独立入口 |
| `_events_digest_for()` 改为抛 `ValidationError` | 事件加载失败不再退化成 `"unavailable"` 继续跑 |
| 三处 `except Exception` 前置 `except ValidationError: raise` | 防止 `_require_formal` 的异常被上层「单格失败不终止整体」吞掉 |

最后一条是必须的：基准行与压力测试行的 `except Exception` 会把任何异常
转成一行 `status=failed` 记录然后继续。若不透传，`ValidationError` 会变成
「某个基准失败」而不是「整次验证中止」，非正式结果仍会以部分形式留在结论里。

### 2.4 `dashboard/pages/3_回测.py`

- 记录下拉框对非正式记录追加「| 非正式口径」后缀；
- 详情区显示会计口径；非正式时给出醒目提示（`st.warning`，不算页面错误）。

### 2.5 未改动

- `app/backtest/engine.py`：口径标记的产生逻辑（3A.3.2.2.2 已验收）一字未改。
- `app/backtest/corporate_actions.py`：公司行为核心逻辑一字未改。
- 表结构：**无 schema 变更**（两字段走 `summary_json`，不新增列）。

---

## 3. 正式 / 非正式边界

```
apply_corporate_actions=True（默认）
  └─ 加载失败 → CorporateActionLoadError → 回测中止，不产生任何记录
  └─ 正常     → accounting_basis=formal_receivable, formal_valuation=True
                 → save_result 落盘 → is_formal_run=True → 可进入验证

apply_corporate_actions=False（唯一关闭入口）
  └─ 事件集为空 → accounting_basis=disabled_non_official, formal_valuation=False
                 → save_result 落盘（两字段强制非正式）
                 → is_formal_run=False
                 → _run_backtest 抛 ValidationError，无法进入任何验证环节
```

历史记录（本字段落盘之前写入的 11 条 `backtest_runs`）读取为
`unknown_legacy` + `formal_valuation=False`。**这不改变任何历史数据**，
只是拒绝把无法证明的口径当成正式口径。

---

## 4. 新增测试（12 项）

| # | 测试 | 覆盖 |
| ---: | --- | --- |
| 1 | `test_sql_execution_error_raises_load_error` | `load_actions` 执行 SQL 抛 `OperationalError` → `CorporateActionLoadError` |
| 2 | `test_deserialization_error_raises_load_error` | 事件行日期非法 → 反序列化异常 → `CorporateActionLoadError` |
| 3 | `test_load_failure_leaves_no_successful_record` | 异常后 `backtest_runs` / `backtest_daily_nav` / `corporate_action_applications` 全 0 行 |
| 4 | `test_validation_digest_load_failure_raises` | 验证层事件加载失败 → `ValidationError`（不再是 `"unavailable"`） |
| 5 | `test_non_formal_result_persists_both_fields` | 非正式结果保存 → summary / 顶层 / list_runs 三处字段完整 |
| 6 | `test_formal_result_persists_formal_basis` | 正式结果持久化不变，`performance` 与内存一致 |
| 7 | `test_legacy_record_without_fields_is_not_formal` | 无字段历史记录 → `unknown_legacy` + `False` |
| 8 | `test_accounting_basis_helpers_fail_closed` | 三个判定函数的 fail closed 语义 |
| 9 | `test_non_formal_backtest_rejected_by_validation` | 非正式回测 → 验证层拒绝 |
| 10 | `test_validation_config_keeps_corporate_actions_on` | 验证配置默认 `apply_corporate_actions=True` |
| 11 | `test_missing_basis_is_persisted_as_unknown_not_formal` | 结果缺口径字段 → `unknown_legacy`，不默认为正式 |
| 12 | `test_disabled_basis_forces_non_formal_even_if_flag_true` | 口径非正式时 `formal_valuation` 强制为 `False` |

新增文件：`tests/test_phase3a3_2_2_3.py`（266 行）。

第 2 项特别说明：它**不 monkeypatch**，直接往库里插一条 `ex_date='not-a-date'`
的事件，走真实的 `load_actions → action_from_row → date.fromisoformat` 路径，
再被引擎的 `except Exception` 转成 `CorporateActionLoadError`。
这验证的是真实反序列化链路，不是模拟抛出。

---

## 5. 回归结果

| 项 | 结果 |
| --- | --- |
| 基线测试 | **484** |
| 本轮新增 | **12** |
| 最终总数 | **496** |
| 通过 | **496** |
| 失败 | 0 |
| 跳过 | 0 |
| xfail | 0 |

详见 `reports/phase3A3_2_2_3_test_report.md`。

---

## 6. 数据库

| 项 | 值 |
| --- | --- |
| schema 变更 | **无** |
| `etf_daily_prices` | 116,609（无变化，连续第五阶段） |
| 行情指纹 | `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`（未变） |
| `backtest_runs` | 11（未删未改） |
| `validation_runs` | 44（未删未改） |
| `corporate_actions` | 166（未改） |
| `corporate_action_versions` | 704（保留全部历史版本） |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次 `init_db()` 前后行数一致 |
| 事件对账 | 14 项校验，失败 0 |

**本轮数据库零变化**：无 schema 变更、无新增/删除行、无字段改写。
`scripts/replay_3a3_2.py` 只做内存回测并写 `data/replay_3a3_2_2_3.json`，
不写 `backtest_runs`，因此 11 条历史回测记录保持原样。
快照报告见 `reports/phase3A3_2_2_3_data_snapshot.md`。

---

## 7. 样本外重放

`PYTHONUTF8=1 .venv/Scripts/python.exe scripts/replay_3a3_2.py --out data/replay_3a3_2_2_3.json`

源记录 `32aead3291734f91`：样本内 2021-01-04~2024-12-31，样本外 2025-01-02~2026-11-09，
MA250，41 只。输出 `data/replay_3a3_2_2_3.json`。

| 区间 | 口径 | 总收益 | 最大回撤 | Sharpe | 交易 |
| --- | --- | ---: | ---: | ---: | ---: |
| 样本外 | 正式（ca=True） | **+20.1146%** | −18.2881% | 0.7210 | 419 |
| 样本外 | 旧口径（ca=False） | +31.7931% | −25.1232% | 0.7818 | 425 |
| 样本外 | B&H 正式 | +19.3094% | −19.0295% | 0.7225 | 41 |
| 样本外 | B&H 旧口径 | +31.9693% | −18.5847% | 0.8805 | 41 |
| 样本内 | 正式（ca=True） | **+13.6776%** | −13.8537% | 0.2522 | 1270 |
| 样本内 | 旧口径（ca=False） | −15.7078% | −32.8792% | 0.1343 | 1206 |

与 3A.3.2.2.2 完全一致（样本外 +20.1146% / Sharpe 0.7210 / 回撤 −18.2881% /
419 笔；样本内 +13.6776%）。

**这一致性是正确结果**：本轮只改持久化与验证闸门，不动会计逻辑，
指标本就不该变。若这里出现差异，说明改动越界了。

数据指纹前后一致：`data_fingerprint_before == data_fingerprint_after`。

---

## 8. 未解决限制

1. 39 条历史验证记录仍未重放（单次约 24 分钟，全量约 16 小时）
2. 11 条历史 `backtest_runs` 现读为 `unknown_legacy` + 非正式；
   若要恢复其正式身份，需要重跑而非回填字段（回填等于伪造证据）
3. `formal_valuation` 走 `summary_json`，没有独立列，
   因此无法用 SQL 索引快速筛选正式记录；需要时再考虑加列
4. 测试结果是本会话本地执行结果，不是外部独立测试
