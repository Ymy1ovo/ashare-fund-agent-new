# 阶段3B-5.4 测试报告

- 基线 HEAD：`a94325080a449a4a84e40b8a1bc4bbabcb0bab03`
- 执行日期：2026-11-23
- Python 3.11.2 / pytest / SQLite

> 以下全部为**实际执行**结果，含真实命令、数量、耗时。
> 静态检查单独标注，不冒充测试通过。

---

## 1. 新增专项测试

```bash
$ pytest tests/test_3b5_4_multi_type.py -q
35 passed in 32.65s
```

| 分组 | 用例数 |
| --- | ---: |
| 六类产品接入 | 8 |
| A/C 归组 | 4 |
| 幂等与指纹 | 2 |
| 证据边界 | 7 |
| 研究口径 | 9 |
| 货币库隔离 | 2 |
| 正式库只读 | 3 |
| **合计** | **35** |

全部使用**临时 SQLite + 注入式假抓取器**，不联网、不写正式库。

---

## 2. 回归测试

### 2.1 3B-5.3 系列

```bash
$ pytest tests/test_3b5_3_2_fk_serialization.py \
        tests/test_3b5_3_1_atomic.py \
        tests/test_3b5_3_user_ingest.py -q
64 passed
```

### 2.2 3B-5.1 / 3B-5.2 研究引擎

```bash
$ pytest tests/test_3b5_1_fund_research.py \
        tests/test_3b5_2_code_lookup.py -q
135 passed
```

### 2.3 合并回归（一次性）

```bash
$ pytest tests/test_3b5_4_multi_type.py \
        tests/test_3b5_3_2_fk_serialization.py \
        tests/test_3b5_3_1_atomic.py \
        tests/test_3b5_3_user_ingest.py \
        tests/test_3b5_1_fund_research.py \
        tests/test_3b5_2_code_lookup.py -q
234 passed in 279.89s (0:04:39)
```

（35 + 20 + 27 + 17 + 103 + 32 = 234，与上面分组一致）

---

## 3. 全量测试

```bash
$ pytest -q
1517 passed, 1 warning in 503.03s (0:08:23)
```

| 项 | 数值 |
| --- | ---: |
| 通过 | **1517** |
| 失败 | **0** |
| 错误 | **0** |
| 耗时 | **503.03 秒** |

### 3.1 数量演进

| 阶段 | 全量通过数 |
| --- | ---: |
| 3B-5.2 | 1418 |
| 3B-5.3 | 1445 |
| 3B-5.3.1 | 1465 |
| 3B-5.3.2 | 1482 |
| **3B-5.4** | **1517** |

1482 + 35 = 1517，增量与新增用例数一致。

---

## 4. 真实接入执行记录

### 4.1 临时库（先行验证）

```bash
$ python .tmp54/tmp_ingest.py
```

| 代码 | 状态 | 分类 | 净值行 |
| --- | --- | --- | ---: |
| `050002` | `ingested` | `ordinary_index` | 5644 |
| `001052` | `ingested` | `etf_linked` | 2802 |
| `001938` | `ingested` | `active_equity` | 2678 |
| `519066` | `ingested` | `active_equity` | 4461 |
| `000032` | `ingested` | `bond_pure` | 3288 |
| `000033` | `ingested` | `bond_pure` | 3288 |
| `000509` | `ingested` | `money_market` | 4676 |
| `001548` | `ingested` | `etf_linked` | 2764 |
| `001549` | `ingested` | `etf_linked` | 2764 |

### 4.2 正式库（验证通过后）

```bash
$ python -m app.fund.ingest_user_funds --codes-file codes54.txt
# 或等价脚本调用（含备份 + 指纹记录）
```

| 代码 | 状态 | 分类 | fund_id | 份额数 | 净值行 |
| --- | --- | --- | ---: | ---: | ---: |
| `050002` | `ingested` | `ordinary_index` | 69 | 1 | 5644 |
| `001052` | `ingested` | `etf_linked` | 70 | 1 | 2802 |
| `001938` | `ingested` | `active_equity` | 71 | 1 | 2678 |
| `519066` | `ingested` | `active_equity` | 72 | 1 | 4461 |
| `000032` | `ingested` | `bond_pure` | 73 | 1 | 3288 |
| `000033` | `ingested` | `bond_pure` | 73 | 1 | 3288 |
| `000509` | `ingested` | `money_market` | 74 | 1 | 4676 |
| `001548` | `ingested` | `etf_linked` | 75 | 1 | 2764 |
| `001549` | `ingested` | `etf_linked` | 75 | 1 | 2764 |

---

## 5. 研究引擎执行记录

```bash
$ python .tmp54/research_prod.py
```

| 代码 | 分类 | 近1年收益 | 最大回撤 | 年化收益 |
| --- | --- | --- | --- | --- |
| `050002` | `ordinary_index` | -4.0993% | 33.4992% | 不可计算 |
| `001052` | `etf_linked` | -12.5516% | 62.7810% | -2.5595% |
| `001938` | `active_equity` | -6.5170% | 29.2096% | 10.2562% |
| `519066` | `active_equity` | -8.5714% | 42.2377% | 7.7922% |
| `000032` | `bond_pure` | 2.3151% | 4.9652% | 3.8121% |
| `000509` | `money_market` | 不可计算 | 不可计算 | 不可计算 |
| `001548` | `etf_linked` | -3.3548% | 39.1939% | 3.2862% |

---

## 6. 静态检查（不计入测试通过）

| 项 | 性质 |
| --- | --- |
| `ast.parse` 语法检查 | **静态** |
| 报告数据与库查询比对 | **静态核对** |

**不计入 1517**。

---

## 7. 测试环境说明

| 项 | 说明 |
| --- | --- |
| 临时库 | `tempfile.mkdtemp()` 下的独立 SQLite |
| 正式库 | 仅在真实接入与研究验证时使用 |
| 网络 | 真实接入调用 AKShare；单元测试**不联网** |
| 故障注入 | 全部在临时库，正式库未参与 |

---

## 8. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
