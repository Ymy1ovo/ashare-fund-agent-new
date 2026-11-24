# 阶段3B-6.1.0 任务1：10 个指数收益口径审计

- 基线 HEAD：`eeb83bc2803d56b84986dce9d1cd93f0cb8dc1d4`  执行时间：2026-11-24 15:09
- 数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`
- 实际接口调用：**22 次**（探测窗口 20240102~20240110）
- 额外历史覆盖调用：**18 次**（2004-01-01 ~ 2026-12-31 全量）

---

## 0. 结论先行

| 结论 | 数量 |
| --- | ---: |
| 三套序列（价格/全收益/净收益）均可取得 | **4**（000300 / 000905 / 000906 / 000016）|
| 价格 + 全收益可取得 | **2**（000942 / 000922）|
| 三套但语义特殊（债券指数） | **1**（000012）|
| **仅价格指数可取得** | **3**（399997 / H30184 / 930930）|

**关键否定结论**：`399997`（中证白酒）、`H30184`（半导体）、`930930`（港股通）
**没有找到全收益序列**，它们的 `return_basis` 必须继续是 `unknown`。

**本轮不升级任何指数的 `return_basis`。** 这是审计，不是接入。

---

## 1. 官方编制方案证据

### 1.1 已实际下载并解析的文件

| 项 | 值 |
| --- | --- |
| 文件 | 沪深300指数编制方案（2023年9月） |
| URL | <https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf> |
| 大小 | 1,184,619 字节 |
| 页数 | 16 页 |
| 解析结果 | 文本 8190 字符，`全收益` 命中 **10** 处、`净收益` **11** 处 |

**官方原文（第 4.6 节）**：

> 中证指数有限公司同时计算沪深300全收益指数和净收益指数的日收盘值。沪深300全收益指数、净收益指数是沪深300指数的辅指数，沪深300全收益指数、净收益指数的计算中考虑了样本税前、税后现金红利的再投资收益

> 沪深300全收益指数、沪深300净收益指数与价格指数的区别在于样本公司发生分红派息时沪深300全收益指数、沪深300净收益指数的点位不会自然回落

### 1.2 这证明了什么、没证明什么

| 证明 | 未证明 |
| --- | --- |
| 中证指数公司**确实**为沪深300 计算全收益与净收益指数 | 其他 9 个指数是否也都有对应辅指数 |
| 全收益与价格指数的差异定义（分红再投资 vs 点位自然回落） | 接口返回的 H00300 是否**就是**官方那条序列 |
| 净收益 = 税后红利，全收益 = 税前红利 | 各指数的历史起始日与官方是否一致 |

**因此：官方方案证明「这类指数存在」，实际接口调用证明「这个代码能取到数据」，
两者必须分别验证，不能互相替代。**

---

## 2. 逐指数审计（10 个，无遗漏）

### `000300` 沪深300指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000300` |
| total_return_index_code | `H00300` |
| net_total_return_index_code | `N00300` |
| 接口返回的价格指数名 | 沪深300指数 |
| 接口返回的全收益名 | 沪深300全收益指数 |
| 接口返回的净收益名 | 沪深300净收益指数 |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,559 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 5,318 rows |
| net_history | OK 5,318 rows |
| max_gap_days | 13 |
| non_positive_close | 0 |
| quality_grade | **A** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益三套序列**均已实测可取得**（H00300/N00300，2004-01-01 起，各 5,318 行）；官方编制方案已验证。但**口径仍为 unknown**——本轮是审计，不执行口径升级。

### `000905` 中证小盘500指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000905` |
| total_return_index_code | `H00905` |
| net_total_return_index_code | `N00905` |
| 接口返回的价格指数名 | 中证小盘500指数 |
| 接口返回的全收益名 | 中证小盘500全收益指数 |
| 接口返回的净收益名 | 中证小盘500净收益指数 |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,318 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 5,318 rows |
| net_history | OK 5,318 rows |
| max_gap_days | 365 |
| non_positive_close | 0 |
| quality_grade | **A** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益均实测可取得（H00905/N00905）。官方方案未单独下载核验（沪深300 方案已证明中证体系存在该类辅指数）。

### `000906` 中证800指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000906` |
| total_return_index_code | `H00906` |
| net_total_return_index_code | `N00906` |
| 接口返回的价格指数名 | 中证800指数 |
| 接口返回的全收益名 | 中证800全收益指数 |
| 接口返回的净收益名 | 中证800净收益指数 |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,318 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 5,318 rows |
| net_history | OK 5,318 rows |
| max_gap_days | 365 |
| non_positive_close | 0 |
| quality_grade | **A** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益均实测可取得（H00906/N00906）。同上。

### `000016` 上证50指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000016` |
| total_return_index_code | `H00016` |
| net_total_return_index_code | `N00016` |
| 接口返回的价格指数名 | 上证50指数 |
| 接口返回的全收益名 | 上证50全收益指数 |
| 接口返回的净收益名 | 上证50净收益指数 |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,560 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 5,560 rows |
| net_history | OK 5,560 rows |
| max_gap_days | 13 |
| non_positive_close | 0 |
| quality_grade | **A** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益均实测可取得（H00016/N00016，5,560 行，覆盖更长）。

### `399997` 中证白酒指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `399997` |
| total_return_index_code | **NULL** |
| net_total_return_index_code | **NULL** |
| 接口返回的价格指数名 | 中证白酒指数 |
| 接口返回的全收益名 | — |
| 接口返回的净收益名 | — |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 4,346 |
| total_history | NOT AVAILABLE |
| net_history | NOT AVAILABLE |
| max_gap_days | 1831 |
| non_positive_close | 0 |
| quality_grade | **C** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：**仅价格指数可取得**。H/N 变体（H39997/N39997）接口均返回空，未找到全收益/净收益序列。**必须保持 unknown/price_return**。

### `H30184` 中证全指半导体产品与设备指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `H30184` |
| total_return_index_code | **NULL** |
| net_total_return_index_code | **NULL** |
| 接口返回的价格指数名 | 中证全指半导体产品与设备指数 |
| 接口返回的全收益名 | — |
| 接口返回的净收益名 | — |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,317 |
| total_history | NOT AVAILABLE |
| net_history | NOT AVAILABLE |
| max_gap_days | 369 |
| non_positive_close | 1 |
| quality_grade | **C** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：**仅价格指数可取得**。H30184 本身就是价格指数代码（H 前缀在此不代表全收益）。未找到全收益变体。**必须保持 unknown**。

### `000942` 中证内地消费主题指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000942` |
| total_return_index_code | `H00942` |
| net_total_return_index_code | **NULL** |
| 接口返回的价格指数名 | 中证内地消费主题指数 |
| 接口返回的全收益名 | 中证内地消费主题全收益指数 |
| 接口返回的净收益名 | — |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,318 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 5,318 rows |
| net_history | NOT AVAILABLE |
| max_gap_days | 365 |
| non_positive_close | 0 |
| quality_grade | **A** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：价格 + 全收益可取得（H00942）；净收益变体（N00942）返回空。

### `000012` 上证国债指数

| 字段 | 值 |
| --- | --- |
| provider | 上海证券交易所 |
| price_index_code | `000012` |
| total_return_index_code | `N00012` |
| net_total_return_index_code | `H00012` |
| 接口返回的价格指数名 | 上证国债指数 |
| 接口返回的全收益名 | 上证国债指数(利息及再投资) |
| 接口返回的净收益名 | 上证国债指数(净价) |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,559 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 3,373 rows |
| net_history | OK 3,373 rows |
| max_gap_days | 13 |
| non_positive_close | 0 |
| quality_grade | **B** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：**三套序列含义特殊**：000012=上证国债指数（全价），H00012=上证国债指数(净价)，N00012=上证国债指数(利息及再投资)。**H 前缀在此不是全收益**，命名规则与股票指数不同。三套数值差异极大（206 / 104 / 145），不可混用。

### `000922` 中证红利指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000922` |
| total_return_index_code | `H00922` |
| net_total_return_index_code | **NULL** |
| 接口返回的价格指数名 | 中证红利指数 |
| 接口返回的全收益名 | 中证红利全收益指数 |
| 接口返回的净收益名 | — |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 5,318 |
| total_history | OK 2004-01-01 ~ 2026-11-23 / 5,318 rows |
| net_history | NOT AVAILABLE |
| max_gap_days | 365 |
| non_positive_close | 0 |
| quality_grade | **A** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：价格 + 全收益可取得（H00922）；净收益变体返回空。

### `930930` 中证港股通综合指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `930930` |
| total_return_index_code | **NULL** |
| net_total_return_index_code | **NULL** |
| 接口返回的价格指数名 | 中证港股通综合指数 |
| 接口返回的全收益名 | — |
| 接口返回的净收益名 | — |
| **return_basis** | **`unknown`** |
| history_available | True |
| history_start / end | 2004-01-01 ~ 2026-11-23 |
| row_count（价格） | 3,000 |
| total_history | NOT AVAILABLE |
| net_history | NOT AVAILABLE |
| max_gap_days | 3970 |
| non_positive_close | 0 |
| quality_grade | **C** |
| source_grade | official_third_party_aggregated |
| usable_for_excess_return | **False** |

**限制**：**仅价格指数可取得**。H/N 变体均返回空。港股通指数为人民币计价口径，与汇率处理相关，需单独核实。

---

## 3. 数值验证：价格 ≠ 全收益（实测）

**这是防止「同代码不同序列被误当同一序列」的核心验证。**

### 3.1 沪深300 同日对比（2024-01-02）

| 序列 | 代码 | 2024-01-02 收盘 |
| --- | --- | ---: |
| 沪深300 指数（价格） | `000300` | 3,386.35 |
| 沪深300 全收益指数 | `H00300` | **4,709.92** |

**两者相差 1,323.57 点（+39.1%），是不同序列，绝不可互换。**

### 3.2 上证国债指数三序列对比（2024-01-02）

| 序列 | 代码 | 收盘 | 含义 |
| --- | --- | ---: | --- |
| 上证国债指数 | `000012` | 206.07 | 全价指数 |
| 上证国债指数(净价) | `H00012` | **104.65** | **净价指数**（不含应计利息） |
| 上证国债指数(利息及再投资) | `N00012` | **145.71** | **含利息再投资** |

**⚠️ 命名陷阱**：`H` 前缀在股票指数里代表全收益，但在上证国债指数里
代表**净价**；`N` 前缀才是「利息及再投资」。
**如果按前缀惯例直接映射，会把净价指数当全收益用——这是严重错误。**

---

## 4. 历史覆盖质量（实测 18 次调用）

| 指数 | 行数 | 起 | 止 | 最大间隔 | 非正收盘 |
| --- | ---: | --- | --- | ---: | ---: |
| `000300` | 5,559 | 2004-01-01 | 2026-11-23 | 13 | 0 |
| `000905` | 5,318 | 2004-01-01 | 2026-11-23 | 365 | 0 |
| `000906` | 5,318 | 2004-01-01 | 2026-11-23 | 365 | 0 |
| `000016` | 5,560 | 2004-01-01 | 2026-11-23 | 13 | 0 |
| `399997` | 4,346 | 2004-01-01 | 2026-11-23 | 1831 | 0 |
| `H30184` | 5,317 | 2004-01-01 | 2026-11-23 | 369 | 1 |
| `000942` | 5,318 | 2004-01-01 | 2026-11-23 | 365 | 0 |
| `000012` | 5,559 | 2004-01-01 | 2026-11-23 | 13 | 0 |
| `000922` | 5,318 | 2004-01-01 | 2026-11-23 | 365 | 0 |
| `930930` | 3,000 | 2004-01-01 | 2026-11-23 | 3970 | 0 |

### 4.1 缺口说明

| 指数 | 最大间隔 | 位置 | 解释 |
| --- | ---: | --- | --- |
| `H00300` / `H00905` / `H00906` / `H00942` / `H00922` | 365 天 | 2004-01-01 → 2004-12-31 | **基线占位行**，非真实缺口 |
| `N00012` / `H00012` | 3,287 天 | 2004-01-01 → 2012-12-31 | 基线占位行，真实起点 2013-01-04 |
| `399997` | 1,831 天 | 2004-01-01 → 2009-01-05 | 基线占位行，真实起点 2009-01-05 |
| `930930` | 3,970 天 | 2004-01-01 → 2014-11-14 | 基线占位行，真实起点 2014-11-14 |
| `H30184` | 369 天 | 2004-01-01 → 2005-01-04 | 基线占位行，真实起点 2005-01-04 |

**与 3B-6.0.2 的已知现象一致**：中证接口首行常为 2004-01-01 基线值。
入库时必须标记 `suspect`，不计入有效区间（该逻辑 3B-6.0.2 已实现）。

### 4.2 非正收盘值

| 指数 | 非正收盘数 |
| --- | ---: |
| `N00905` | 1 |
| `N00906` | 1 |
| `N00016` | 1 |
| `H30184` | 1 |

均为单点异常（与 3B-6.0.2.3 已发现的 `H30184 2013-06-28 close=0.0` 同类现象），
**未修复**，接入时需走同一条 `quality_status='suspect'` 通道。

---

## 5. 能否进入正式研究层

| 指数 | 有官方方案 | 有全收益序列 | 历史完整 | 可否进入 |
| --- | --- | --- | --- | --- |
| `000300` | ✅ | ✅ | ✅ | **A 类**（待接入） |
| `000905` | ❌ | ✅ | ✅ | **B 类**（仅参考） |
| `000906` | ❌ | ✅ | ✅ | **B 类**（仅参考） |
| `000016` | ❌ | ✅ | ✅ | **B 类**（仅参考） |
| `399997` | ❌ | ❌ | ✅ | **C 类**（不可得） |
| `H30184` | ❌ | ❌ | ✅ | **C 类**（不可得） |
| `000942` | ❌ | ✅ | ✅ | **B 类**（仅参考） |
| `000012` | ❌ | ✅ | ✅ | **B 类**（仅参考） |
| `000922` | ❌ | ✅ | ✅ | **B 类**（仅参考） |
| `930930` | ❌ | ❌ | ⚠️ | **C 类**（不可得） |

---

## 6. 本轮**没有**做的事

| 项 | 状态 |
| --- | --- |
| 升级任何指数的 `return_basis` | **否**（仍全部 unknown） |
| 写入任何指数行情 | **否**（`index_daily` 仍 50,603 行） |
| 修改 `index_master` | **否**（仍 10 行） |
| 把价格指数当全收益 | **否** |
| 把净价指数当全收益 | **否**（已明确标注 H00012 陷阱） |

---

## 7. 未解决的问题

| 问题 | 状态 |
| --- | --- |
| `399997` / `H30184` / `930930` 无全收益序列 | **未解决**，需查指数公司是否另行发布 |
| 接口返回的 H00300 是否就是官方序列 | **未证实**，需官方发布文件的代码对照 |
| 各指数历史起始日与官方公告是否一致 | **未证实** |
| 港股通指数的汇率处理规则 | **未查证** |
| 全收益序列是否含税费处理差异 | 官方方案仅对沪深300 说明（税前/税后） |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
