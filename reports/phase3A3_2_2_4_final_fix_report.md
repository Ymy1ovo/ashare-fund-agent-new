# 阶段3A.3.2.2.4 正式口径验证闸门一致性修复

- 生成时间：2026-11-14
- 基线 HEAD：`3b19361a11a1444231d08d3b8c81fe3bd7b0f381`（阶段3A.3.2.2.3）
- 阶段性质：单一缺陷修复，不扩大范围

---

## 1. 缺陷

`app/validation/runner.py::_require_formal()` 在 3A.3.2.2.3 引入时只做了一件事：

```python
if not getattr(result, "formal_valuation", False):
    raise ValidationError(...)
```

`accounting_basis` 虽然写进了错误信息，却**完全没有参与判断**。

后果是闸门可以被三类记录穿过：

| 记录 | `formal_valuation` | `accounting_basis` | 旧闸门 | 应当 |
| --- | --- | --- | --- | --- |
| 自相矛盾 | `True` | `disabled_non_official` | **放行** | 拒绝 |
| 自相矛盾 | `True` | `unknown_legacy` | **放行** | 拒绝 |
| 类型污染 | `1` / `"yes"` / `[1]` | 任意 | **放行**（真值判断） | 拒绝 |

第一行最危险：3A.3.2.2.3 在 `save_result()` 里对落盘做了强制纠正
（口径非正式 → `formal_valuation` 强制 `False`），但**内存中的对象没有这层保护**。
验证流程拿到的正是内存对象，因此只要有任何路径把 `formal_valuation` 置为真、
而 `accounting_basis` 仍是非正式，闸门就会放行一条本不该进入正式评价的结果。

第三行是同一问题的另一面：`not getattr(...)` 对 `1`、`"yes"`、`[1]`、
非空字典都判为「真」，于是把一个不是 `True` 的值当成正式布尔标记。

### 根因

闸门把「正式性」压缩成了**单一布尔字段的真值判断**，
但正式性实际由两个字段共同定义。只要两字段可以独立出现，
任何只检查其中一个的实现都存在绕过口。

---

## 2. 修复

改为**严格白名单**，两个字段必须同时精确命中：

```python
FORMAL_ACCOUNTING_BASIS = "formal_receivable"

basis = getattr(result, "accounting_basis", None)
formal = getattr(result, "formal_valuation", None)

problems = []
if not isinstance(basis, str) or basis != FORMAL_ACCOUNTING_BASIS:
    problems.append(f"accounting_basis={basis!r}")
if not isinstance(formal, bool) or formal is not True:
    problems.append(f"formal_valuation={formal!r}")
if not problems:
    return
raise ValidationError(...)
```

三处刻意的严格：

1. **`isinstance(basis, str)`**：`accounting_basis` 只接受字符串，
   不接受 `["formal_receivable"]` 这类容器。
2. **`basis != FORMAL_ACCOUNTING_BASIS`**：精确等值，不做大小写归一、
   不做前缀匹配。`"FORMAL_RECEIVABLE"`、`"formal"` 一律拒绝。
3. **`formal is not True`**：必须是 `bool` 且**就是** `True`。
   `1 == True` 成立，但 `1 is not True`，所以 `1`、`1.0`、`"yes"` 全部拒绝。

错误信息同时列出两个字段的实际值，便于定位是哪一边不满足。

---

## 3. 影响面

`_require_formal()` 的调用点未变，因此修复自动覆盖：

| 调用点 | 覆盖环节 |
| --- | --- |
| `_run_backtest()` | 样本内参数网格、样本外、Walk-Forward、基准、压力测试、稀疏数据副本 |
| `_build_regime_payload()` 内的直接引擎调用 | 市场环境分组统计 |

未修改：

- `app/backtest/engine.py`：口径标记的产生逻辑
- `app/backtest/corporate_actions.py`：公司行为核心逻辑
- 数据库：零变化（无 schema 变更、无行数变化、无字段改写）

---

## 4. 新增测试（22 项）

新增文件 `tests/test_phase3a3_2_2_4.py`，**直接调用 `_require_formal()`**，
不经过回测引擎，验证闸门自身的判定行为。

### 4.1 允许通过（1 项）

| # | 测试 | 构造 |
| ---: | --- | --- |
| 1 | `test_formal_basis_with_true_passes` | `formal_receivable` + `True` |

### 4.2 必须拒绝（8 类场景 + 参数化）

| # | 测试 | 构造 | 旧闸门 |
| ---: | --- | --- | --- |
| 2 | `test_disabled_basis_with_false_rejected` | `disabled_non_official` + `False` | 拒绝 |
| 3 | `test_disabled_basis_with_true_rejected` | `disabled_non_official` + `True` | **放行** |
| 4 | `test_formal_basis_with_false_rejected` | `formal_receivable` + `False` | 拒绝 |
| 5 | `test_unknown_legacy_with_true_rejected` | `unknown_legacy` + `True` | **放行** |
| 6 | `test_missing_accounting_basis_rejected` | 属性缺失 / `None` | **放行** |
| 7 | `test_missing_formal_valuation_rejected` | 属性缺失 / `None` | 拒绝 |
| 8 | `test_non_boolean_formal_valuation_rejected` | 8 种非布尔值参数化 | **放行** |
| 9 | `test_non_whitelisted_accounting_basis_rejected` | 6 种非白名单字符串参数化 | 部分放行 |
| 10 | `test_error_message_names_both_fields` | 错误信息必须点出两字段 | — |

第 8 项参数化覆盖：`1`、`0`、`"yes"`、`"True"`、`[1]`、`(1,)`、`{"a": 1}`、`1.0`。
第 9 项参数化覆盖：`None`、`""`、`"FORMAL_RECEIVABLE"`、`"formal"`、
`0`、`["formal_receivable"]`。

其中 5 类（第 3、5、6、8、9 项）在旧闸门下会放行，是本次修复的实际收益。

---

## 5. 回归结果

| 项 | 结果 |
| --- | --- |
| 基线测试 | **496** |
| 本轮新增 | **22** |
| 最终总数 | **518** |
| 通过 | **518** |
| 失败 | 0 |
| 跳过 | 0 |
| xfail | 0 |

旧 496 项全部保留通过，未删除、未跳过、未弱化断言。

### 一个必要的行为变更

`test_non_formal_backtest_rejected_by_validation`（3A.3.2.2.3 的测试）
原来用 `match="非正式会计口径"` 匹配错误文案。新实现的文案一度改成
「不满足正式会计口径」，导致该测试失败。

处理方式：**把错误文案改回包含「非正式会计口径」**，让旧测试原样通过，
而不是去改旧测试的正则。理由是旧测试的断言本身是正确的
（它要匹配的就是「非正式口径被拒」这件事），文案应当迁就既定契约。

---

## 6. 其他验证

| 项 | 结果 |
| --- | --- |
| API 冒烟 | 通过（`/api/validations` 200 / 详情 200 / 不存在 404） |
| Streamlit AppTest | 2 页 0 异常 0 错误元素 |
| `integrity_check` | ok |
| 数据库行数 | 零变化 |
| schema | **无变更** |
| 公司行为核心逻辑 | 未修改 |
| 历史记录 | 未删除、未覆盖 |

---

## 7. 局限

1. 本轮的「两字段矛盾」在真实数据中不会自然出现——
   `save_result()` 会强制纠正落盘值。这是**内存对象的防御性校验**，
   只有构造测试能覆盖，属于典型的纵深防御而非已观测缺陷。
2. `formal_valuation` 存于 `summary_json`，无独立列，无法用 SQL 快速筛选
3. 测试结果是本会话本地执行结果，不是外部独立测试
