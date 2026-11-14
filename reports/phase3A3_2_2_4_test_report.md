# 阶段3A.3.2.2.4 测试报告

- 生成时间：2026-11-14
- 环境：Python 3.11.2 / pytest / Windows
- 基线：496 项（1A ~ 3A.3.2.2.3）

## 1. 总数拆分

| 类别 | 数量 | 通过 | 失败 | 跳过 | xfail |
| --- | ---: | ---: | ---: | ---: | ---: |
| **历史测试**（1A ~ 3A.3.2.2.3） | **496** | 496 | 0 | 0 | 0 |
| **3A.3.2.2.4** 新增 | **22** | 22 | 0 | 0 | 0 |
| **合计** | **518** | **518** | **0** | **0** | **0** |

`--collect-only`：**518 tests collected**

## 2. 本轮新增的 22 项

新增文件 `tests/test_phase3a3_2_2_4.py`，全部**直接调用 `_require_formal()`**，
不经回测，验证闸门自身的判定行为。

### 2.1 允许通过（1 项）

| # | 测试 | 构造 |
| ---: | --- | --- |
| 1 | `test_formal_basis_with_true_passes` | `formal_receivable` + `True` |

### 2.2 必须拒绝（9 项，含 14 个参数化用例）

| # | 测试 | 构造 | 旧闸门 |
| ---: | --- | --- | --- |
| 2 | `test_disabled_basis_with_false_rejected` | `disabled_non_official` + `False` | 拒绝 |
| 3 | `test_disabled_basis_with_true_rejected` | `disabled_non_official` + `True` | **放行** |
| 4 | `test_formal_basis_with_false_rejected` | `formal_receivable` + `False` | 拒绝 |
| 5 | `test_unknown_legacy_with_true_rejected` | `unknown_legacy` + `True` | **放行** |
| 6 | `test_missing_accounting_basis_rejected` | 属性缺失 / `None` | **放行** |
| 7 | `test_missing_formal_valuation_rejected` | 属性缺失 / `None` | 拒绝 |
| 8 | `test_non_boolean_formal_valuation_rejected` | `1` `0` `"yes"` `"True"` `[1]` `(1,)` `{"a":1}` `1.0` | **放行** |
| 9 | `test_non_whitelisted_accounting_basis_rejected` | `None` `""` `"FORMAL_RECEIVABLE"` `"formal"` `0` `["formal_receivable"]` | 部分放行 |
| 10 | `test_error_message_names_both_fields` | 错误信息必须点出两字段 | — |

用户要求的 8 类场景对应第 1~8 项；第 9、10 项是补充。

### 2.3 修复的实际收益

旧闸门下会被放行的 5 类：

| 类别 | 例子 |
| --- | --- |
| 口径非正式但布尔为真 | `disabled_non_official` + `True` |
| 未知口径但布尔为真 | `unknown_legacy` + `True` |
| 缺 `accounting_basis` | 属性不存在 → `getattr` 返回默认值，只看布尔 |
| 非布尔真值 | `1` / `"yes"` / `[1]` / `{"a":1}` |
| 大小写变体 | `"FORMAL_RECEIVABLE"` 在真值语境下被当作非空串 |

## 3. 旧测试保留情况

- 496 项基线测试**全部保留**，未删除、未跳过。
- 期间 `test_non_formal_backtest_rejected_by_validation` 一度失败，
  原因是新实现的错误文案不再包含「非正式会计口径」。
- 处理方式：**修改实现文案**让其包含该短语，旧测试正则原样通过。
  没有改旧测试的断言——旧断言符合既定契约，应当由实现迁就。

## 4. 其他验证

### 4.1 API 冒烟

| 请求 | 结果 |
| --- | --- |
| `GET /api/validations` | 200 |
| `GET /api/validations/0df22f3810974bea` | 200（windows=8 grid=8 stress=7） |
| `GET /api/validations/not_exist` | 404（期望 404） |

`SMOKE_FAILED: 无`

### 4.2 Streamlit AppTest

| 页面 | 异常 | 错误元素 | 数据表 | 指标 |
| --- | ---: | ---: | ---: | ---: |
| `dashboard/pages/3_回测.py` | 0 | 0 | 5 | 5 |
| `dashboard/pages/4_策略验证.py` | 0 | 0 | 5 | 4 |

### 4.3 SQLite integrity_check

```
PRAGMA integrity_check -> ok
```

### 4.4 数据库与历史数据

| 项 | 本轮 |
| --- | --- |
| schema 变更 | **无** |
| 数据库行数变化 | **0** |
| 历史 `backtest_runs` | 11 条，未删未改 |
| 历史 `validation_runs` | 44 条，未删未改 |
| `corporate_action_versions` | 704 条，全部保留 |
| 公司行为核心逻辑 | 未修改 |
| 行情指纹 | 未变（116,609 行） |

## 5. 结论

- 基线 496 项全部保留且通过
- 本轮新增 22 项全部通过
- 最终 **518 passed / 0 failed / 0 skipped / 0 xfail**
- 测试结果是本会话本地执行结果，**不是外部独立测试**
