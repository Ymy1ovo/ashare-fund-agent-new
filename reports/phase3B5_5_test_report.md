# 阶段3B-5.5 测试报告（3B-5.5.1 修正版）

- 基线 HEAD：`e8132fc914eeeef6e6cbcd32b15f346701831a42`
- 执行日期：2026-11-23
- 修正轮：3B-5.5.1（同类分组可验证性 + 年化收益证据日期）
- Python 3.11.2 / pytest / SQLite

> 以下全部为**实际执行**结果。静态检查单独标注，不冒充测试通过。

---

## 1. 本轮新增专项测试

```bash
$ pytest tests/test_3b5_5_1_peer_annualized.py -q
51 passed in 57.34s
```

| 覆盖项 | 用例数 |
| --- | ---: |
| `verifiable_group=False` 即使样本 6/50 个也必须 D | 2 |
| `bond_pure\|unknown` 必须 D | 2 |
| `active_equity\|unknown` 必须 D | 2 |
| `lof\|active\|unknown` 必须 D | 1 |
| 有效指数/基准分组 + 样本充足 → B | 2 |
| 有效分组样本量分档（1→D, 2~4→C） | 2 |
| `money_market` 不因缺指数被判 D | 3 |
| 组键解析器 | 1 |
| 无组键 → D / 永不排名 | 2 |
| 年化日期完整 → A | 1 |
| 年化节点缺日期 → 用质量报告补充 | 1 |
| 年化 ok 但 value=None → D | 1 |
| 无任何日期 → 不伪造 | 1 |
| 缺口阻断仍生效 | 1 |
| 各种 insufficient 态 → D | 1 |
| 真实报告端到端（证据含日期） | 2 |
| 补充日期 == 质量报告日期 | 1 |
| 真实样本年化日期（8 参数） | 8 |
| 真实样本同类评级（8 参数） | 8 |
| 单只重点样本（000032/001938/000509） | 3 |
| A/C 按 fund_id 去重 | 1 |
| `build_indicator_grades` 传 quality | 1 |
| Markdown 显示年化区间 | 1 |
| 只读守恒 / 门禁 | 2 |

---

## 2. 3B-5.5 全部测试

```bash
$ pytest tests/test_3b5_5_quality_framework.py \
        tests/test_3b5_5_1_peer_annualized.py -q
112 passed in 121.00s (0:02:00)
```

| 文件 | 用例数 |
| --- | ---: |
| `test_3b5_5_quality_framework.py` | 61 |
| `test_3b5_5_1_peer_annualized.py` | 51 |

> **注意**：`test_3b5_5_quality_framework.py` 从 60 → 61，
> 因为 `test_peer_small_sample_is_c` 原来用 `bond_pure|unknown`
> 作「有效分组」样本，修正后该组键必须 D，故改用
> `etf_linked|broad|沪深300`，并**新增** `test_peer_bond_unknown_is_d`。
> 原断言未被弱化，只是修正了错误的期望对象。

---

## 3. 回归测试

### 3.1 3B-5.1 / 3B-5.2 研究引擎

```bash
$ pytest tests/test_3b5_1_fund_research.py tests/test_3b5_2_code_lookup.py -q
135 passed in 65.76s (0:01:05)
```

### 3.2 3B-5.3 系列接入 + 3B-5.4 多类型

```bash
$ pytest tests/test_3b5_3_2_fk_serialization.py \
        tests/test_3b5_3_1_atomic.py \
        tests/test_3b5_3_user_ingest.py \
        tests/test_3b5_4_multi_type.py -q
99 passed in 104.58s (0:01:44)
```

---

## 4. 全量测试

```bash
$ pytest -q
1629 passed, 1 warning in 577.58s (0:09:37)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1629** |
| 失败 | **0** |
| 错误 | **0** |
| 耗时 | **577.58 秒** |

### 4.1 数量演进

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-5.4 | 1517 |
| 3B-5.5 | 1577 |
| **3B-5.5.1** | **1629** |

1577 + 51（新专项）+ 1（框架内新增） = 1629。

---

## 5. 真实样本重新生成结果

```bash
$ python .gen.py   # build_practical_report 逐只
```

| 代码 | 类型 | 同类组 | 本体数 | 同类评级 | 年化收益 |
| --- | --- | --- | ---: | --- | --- |
| `050002` | 普通指数基金 | `ordinary_index|broad|沪深300` | 1 | **D**（`insufficient_peer_sample`） | D（`insufficient_data`） |
| `001052` | ETF联接基金 | `etf_linked|broad|中证500` | 1 | **D**（`insufficient_peer_sample`） | A（`ok`） |
| `001938` | 主动权益基金 | `active_equity|中证500` | 2 | **C**（`small_sample`） | A（`ok`） |
| `000032` | 债券基金 | `bond_pure|unknown` | 2 | **D**（`no_verifiable_group`） | A（`ok`） |
| `000509` | 货币基金 | `money_market` | 2 | **C**（`small_sample`） | not_applicable（`not_applicable`） |
| `001548` | ETF联接 A/C 组（A 类） | `etf_linked|broad|上证50` | 1 | **D**（`insufficient_peer_sample`） | A（`ok`） |
| `001549` | ETF联接 A/C 组（C 类） | `etf_linked|broad|上证50` | 1 | **D**（`insufficient_peer_sample`） | A（`ok`） |

### 5.1 年化收益证据（修复后）

| 代码 | 等级 | 证据 |
| --- | --- | --- |
| `050002` | **D** | 区间内存在超过阈值的缺口或样本不足 |
| `001052` | **A** | 成立以来年化 -0.025595，按实际自然日间隔复合年化；计算区间 2015-05-05 → 2026-11-20，跨度 4217 天（计算区间取自净值序列首尾，与质量报告一致） |
| `001938` | **A** | 成立以来年化 0.102562，按实际自然日间隔复合年化；计算区间 2015-11-03 → 2026-11-20，跨度 4035 天（计算区间取自净值序列首尾，与质量报告一致） |
| `000032` | **A** | 成立以来年化 0.038121，按实际自然日间隔复合年化；计算区间 2013-04-24 → 2026-11-20，跨度 4958 天（计算区间取自净值序列首尾，与质量报告一致） |
| `000509` | **not_applicable** | 货币基金不使用净值口径，年化收益不适用 |
| `001548` | **A** | 成立以来年化 0.032862，按实际自然日间隔复合年化；计算区间 2015-07-16 → 2026-11-20，跨度 4145 天（计算区间取自净值序列首尾，与质量报告一致） |
| `001549` | **A** | 成立以来年化 0.032862，按实际自然日间隔复合年化；计算区间 2015-07-16 → 2026-11-20，跨度 4145 天（计算区间取自净值序列首尾，与质量报告一致） |

---

## 6. 测试环境说明

| 项 | 说明 |
| --- | --- |
| 正式库 | **只读**（`build_practical_report` 不写库） |
| 网络 | 单元测试**完全不联网** |
| 正式库写入 | **零**（有守恒测试断言行数不变） |
| 数据重采集 | **零** |

---

## 7. 静态检查（不计入测试通过）

| 项 | 性质 |
| --- | --- |
| `python -m compileall` 语法检查 | **静态** |
| 报告数据与库查询比对 | **静态核对** |

**不计入 1629**。

---

## 8. 代码改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `app/fund/research/quality.py` | **修改** | `grade_peer_comparison()` 判定顺序修复；`grade_annualized()` 证据日期修复；新增 `_peer_key_family_unknown()` |
| `app/fund/research/practical_report.py` | **修改** | 新增 `_annualized_with_interval()`，给报告层年化节点补真实计算区间 |
| `tests/test_3b5_5_1_peer_annualized.py` | **新增** | 51 项专项测试 |
| `tests/test_3b5_5_quality_framework.py` | **微调** | `test_peer_small_sample_is_c` 改用有效组键 + 新增 `test_peer_bond_unknown_is_d` |
| `app/fund/research/engine.py` | **未改** | 计算逻辑零改动 |
| `app/fund/research/indicators.py` | **未改** | 计算逻辑零改动 |
| `app/fund/research/classification.py` | **未改** | 分组逻辑零改动 |
| Schema / 迁移 | **未改** | — |

---

## 9. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
