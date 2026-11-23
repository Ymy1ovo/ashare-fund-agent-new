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

## 8. 验收修正轮（3B-5.4-acceptance-fix）

本轮**只改文档**，不重新采集、不写正式库、不改计算逻辑、不改测试断言。

### 8.1 修正内容

| 文件 | 修正 |
| --- | --- |
| `reports/phase3B5_4_research_validation_report.md` | 第 8 节「收益口径」由「单位净值」改为 **`acc_nav` 累计净值**；新增 2.0 口径声明、2.1 双口径差异实测、8.1 三条硬约束、8.2 货币独立口径、8.3 修正说明 |
| `reports/phase3B5_4_research_validation_report.json` | 新增 `return_caliber` 段，声明 `primary_field=acc_nav`、`unit_nav` 仅作对照、`dividend_repair_used=false` |
| `reports/phase3B5_4_test_report.md` | 新增本节（第 9 节） |

### 8.2 依据（只读核对）

| 依据 | 内容 |
| --- | --- |
| `app/fund/research/engine.py:124` | `compute_nav_indicators(series, field_name="acc_nav")` |
| `app/fund/research/engine.py:126` | `ind_unit = compute_nav_indicators(series, field_name="unit_nav")` → 单独放在 `indicators_unit_nav` |
| `app/fund/research/indicators.py:605` | `compute_nav_indicators(series, *, field_name="acc_nav")` |
| JSON `results.050002.ret_12m.field` | `"acc_nav"` |

### 8.3 双口径差异实测（证明未混用）

| 代码 | `acc_nav` 近1年 | `unit_nav` 近1年 | 差异 |
| --- | --- | --- | --- |
| `050002` | -4.0993% | -8.9623% | 4.8630 个百分点 |

### 8.4 未重跑测试的说明

本轮**零代码改动**（`git diff` 仅 4 个文档 + 1 个 JSON），
计算逻辑与测试断言均未触碰，故**不重跑全量测试**。

上一轮实际执行结果仍然有效：

```
$ pytest -q
1517 passed, 1 warning in 503.03s (0:08:23)
```

如验收方要求重跑，可原样执行上述命令，预期结果不变。


---

## 9. Git 同步证据（本轮）

### 9.1 相对本轮基线 HEAD 的实际变更

| 项 | 值 |
| --- | --- |
| 本轮基线 HEAD | `4bb2d87191e6b070e0881c1ac02cb825a378b2a5` |
| 文档修正提交 | `76db35e04856a3f7323502dc28dd5fb7099b8ca2` |

变更文件清单（`git show --stat`）：

```
 CHANGELOG.md                                       | 42 ++++++++++
 README.md                                          | 20 ++++-
 reports/phase3B5_4_research_validation_report.json | 35 +++++++++
 reports/phase3B5_4_research_validation_report.md   | 89 ++++++++++++++++++++--
 reports/phase3B5_4_test_report.md                  | 46 ++++++++++-
 5 files changed, 222 insertions(+), 10 deletions(-)
```

**全部为文档与 JSON**，无 `.py` 改动、无 Schema 改动、无数据库改动。

### 9.2 推送顺序

```
① Gitee  → 4bb2d87..76db35e  main -> main
② GitHub → 4bb2d87..76db35e  main -> main
```

先 Gitee 主仓，后 GitHub 同步，符合既定流程。

### 9.3 两端 SHA 一致性

| 端 | SHA | 读取方式 |
| --- | --- | --- |
| 本地 | `76db35e04856a3f7323502dc28dd5fb7099b8ca2` | `git rev-parse HEAD` |
| Gitee | `76db35e04856a3f7323502dc28dd5fb7099b8ca2` | `git ls-remote origin refs/heads/main` |
| GitHub | `76db35e04856a3f7323502dc28dd5fb7099b8ca2` | `git ls-remote github refs/heads/main` |

**三者完全一致**，SHA 由远端 `ls-remote` 实际读回，不是本地推断。

### 9.4 禁止 force push

全程使用普通 `git push`，**未使用 `--force` / `--force-with-lease`**。
远端返回均为快进更新 `4bb2d87..76db35e`（非 `+` 强制标记），可佐证为快进推送。

### 9.5 未提交内容

| 项 | 状态 |
| --- | --- |
| 正式数据库 `data/fund_agent.db` | **未提交**（`.gitignore` 覆盖） |
| 数据库备份 `data/backups/*.db` | **未提交** |
| API 密钥 | **无**（本项目不含密钥文件） |

`git ls-files | grep -c '\.db$'` 结果为 **0**。

### 9.6 关于本节所在的补充提交

第 9 节的证据文字本身，是在 `76db35e` **之后**单独提交并推送的。

因此：

- 上文 `76db35e` 是**文档口径修正提交**，已实际推送到两端并读回校验（`ls-remote` 一致）；
- 包含本节内容的最终提交，其 SHA 无法自引用写进本文件；
- 最终两端 HEAD 的 SHA 与一致性，已在**交付说明**中给出，校验方式与本轮相同
  （`git ls-remote <remote> refs/heads/main`），可对照复核。

若需在仓库内自证，直接执行：

```bash
git ls-remote origin refs/heads/main
git ls-remote https://github.com/Ymy1ovo/ashare-fund-agent-new.git refs/heads/main
```

两条命令输出必须相同，且等于 `git rev-parse HEAD`。

---

## 10. 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
