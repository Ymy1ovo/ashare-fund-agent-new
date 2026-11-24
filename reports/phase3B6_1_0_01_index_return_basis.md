# 阶段3B-6.1.0.1 修正版：10 个指数收益口径审计

- 本轮基线 HEAD：`6b0dbafd1466c9def6f11b3c89fbe21122294dda`
- 修订执行时间：2026-11-24 16:07
- 数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`（**未变**）
- **本文件是 3B-6.1.0 任务1 的修正版**，修正 000012 语义字段错误 并补齐其余 9 个指数的官方编制方案证据。

---

## 0. 本轮修正的两处实质错误

### 0.1 `000012` 上证国债指数：净价被错填为净收益

| 项 | 3B-6.1.0（错误） | 3B-6.1.0.1（修正） |
| --- | --- | --- |
| `net_total_return_index_code` | `H00012`（**净价**） | **`null`** |
| `clean_price_index_code` | 不存在该字段 | **`H00012`** |
| `price_or_full_price_index_code` | 无 | **`000012`** |
| `total_return_index_code` | `N00012` | `N00012`（保留，附 caveat） |

**净价指数 ≠ 净收益指数。** 把 `H00012` 填进 `net_total_return` 是语义错误。

### 0.2 三个指数被误判「无全收益序列」

3B-6.1.0 按「`H` + 后 5 位」的**股票指数命名惯例**猜代码：

| 指数 | 猜测代码 | 结果 | **官方真实代码** | 结果 |
| --- | --- | --- | --- | --- |
| `399997` 中证白酒 | `H39997` | ❌ 空 | **`H20539`** | ✅ 非空 |
| `H30184` 半导体 | — | — | **`H20184`** | ✅ 非空 |
| `930930` 港股通 | `H930930` | ❌ 空 | **`H20930`** | ✅ 非空 |
| `000922` 中证红利（净收益） | `N00922` | ❌ 空 | **`000922CNY020`** | ✅ 非空 |

**教训：不得按代码前缀惯例推断官方衍生指数代码，必须以官方文件为准。**

上述真实代码来自中证官方 **factsheet 的「衍生指数」栏**，且已逐一实测验证。

---

## 1. 修正后的结论总览

| 类别 | 数量 | 指数 |
| --- | ---: | --- |
| 价格 / 全收益 / 净收益三套齐全 | **6** | `000300` `000905` `000906` `000016` `399997` `000922` |
| 价格 + 全收益（无净收益） | **2** | `H30184` `930930` |
| 价格 + 全收益（净收益不可得） | **1** | `000942` |
| 语义特殊（债券指数） | **1** | `000012` |

> **仍不升级任何 `return_basis`。** 全部保持 `unknown`。

---

## 2. 官方证据：8/9 编制方案 + 10/10 factsheet

### 2.1 取得的官方文件

| 指数 | 编制方案 | factsheet | 方案页数 | 方案 sha256(16) |
| --- | --- | --- | ---: | --- |
| `000300` | ✅ | ❌ | 16 | `de6491e03e5d57ec` |
| `000905` | ✅ | ❌ | 3 | `6109ad8390fdad70` |
| `000906` | ✅ | ❌ | 3 | `6109ad8390fdad70` |
| `000016` | ✅ | ❌ | 2 | `e8f1ce6045b7f913` |
| `399997` | ✅ | ❌ | 2 | `62450948684c2930` |
| `H30184` | ✅ | ❌ | 2 | `8b7de8a81c93e5f7` |
| `000942` | ✅ | ❌ | 3 | `e2893e60254074f9` |
| `000012` | ❌ **未取得** | ✅ | — | `—` |
| `000922` | ✅ | ❌ | 3 | `6b8053f02ca87a0e` |
| `930930` | ❌ **未取得** | ✅ | — | `—` |

**未取得的 2 份编制方案**：`000012`（上交所指数，csindex 直链 404）、
`930930`（csindex 直链 404）。两者均已取得 factsheet。

### 2.2 证据等级逐指数

| 指数 | 等级 | 依据 |
| --- | --- | --- |
| `000300` | **L2_document_verified** | None |
| `000905` | **L2_document_verified** | 方案正文未提及全收益/净收益；辅指数信息仅见于 factsheet |
| `000906` | **L2_document_verified** | 与 000905 同一份方案文件（中证规模指数合集） |
| `000016` | **L2_document_verified** | 方案正文未提及辅指数 |
| `399997` | **L2_document_verified** | 方案正文 752 字符，未提及辅指数；factsheet 衍生指数栏披露 H20539 / 399997CNY02 |
| `H30184` | **L2_document_verified** | factsheet 净收益指数栏为 --，即无净收益辅指数 |
| `000942` | **L2_document_verified** | factsheet 披露 H00942；净收益代码未在 factheet 中给出可验证值 |
| `000012` | **L3_factsheet_only** | **未取得官方编制方案**。已检索 csindex 官网 PDF 直链（{code}_Index_Methodology_cn.pdf / factsheet / methodology_cn）与 sse.com.cn 指数页，均 404 或仅返回导航页。factsheet 无「衍生指数」栏，只列出 H00012/N00012 两个代码，**不解释其经济含义**。语义结论来自接口返回名称，属 L3。 |
| `000922` | **L2_document_verified** | 方案正文 1,130 字符，未提及辅指数 |
| `930930` | **L3_factsheet_only** | **未取得官方编制方案**（csindex PDF 直链全部 404）。factsheet 有「衍生指数」栏，披露全收益 H20930，净收益栏为 --。 |

---

## 3. 逐指数审计（10 个，无遗漏）

### `000300` 沪深300指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000300` |
| total_return_index_code | `H00300` |
| **net_total_return_index_code** | `N00300` |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,559 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 13 天 |
| 非正收盘 | 0 |
| quality_grade | **A** |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益三套序列**均已实测可取得**（H00300/N00300，2004-01-01 起，各 5,318 行）；官方编制方案已验证。但**口径仍为 unknown**——本轮是审计，不执行口径升级。

### `000905` 中证小盘500指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000905` |
| total_return_index_code | `H00905` |
| **net_total_return_index_code** | `N00905` |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,318 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 365 天 |
| 非正收盘 | 0 |
| quality_grade | **A** |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益均实测可取得（H00905/N00905）。官方方案未单独下载核验（沪深300 方案已证明中证体系存在该类辅指数）。

### `000906` 中证800指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000906` |
| total_return_index_code | `H00906` |
| **net_total_return_index_code** | `N00906` |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,318 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 365 天 |
| 非正收盘 | 0 |
| quality_grade | **A** |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益均实测可取得（H00906/N00906）。同上。

### `000016` 上证50指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000016` |
| total_return_index_code | `H00016` |
| **net_total_return_index_code** | `N00016` |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,560 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 13 天 |
| 非正收盘 | 0 |
| quality_grade | **A** |
| usable_for_excess_return | **False** |

**限制**：价格/全收益/净收益均实测可取得（H00016/N00016，5,560 行，覆盖更长）。

### `399997` 中证白酒指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `399997` |
| total_return_index_code | `H20539` |
| **net_total_return_index_code** | `399997CNY02` |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 4,346 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 1831 天 |
| 非正收盘 | 0 |
| quality_grade | **C** |
| usable_for_excess_return | **False** |

**限制**：**全收益/净收益序列存在且可取**（H20539 / 399997CNY02），但 3B-6.1.0 曾误判为「不存在」。编制方案正文未提及辅指数，代码来自 factsheet；`return_basis` 仍保持 unknown（本轮为审计，不做口径升级）。

**本轮修正**：3B-6.1.0 用「H+后5位」猜测 H39997 返回空，据此误判无全收益。官方 factsheet「衍生指数」栏披露 H20539（全收益）/ 399997CNY02（净收益），均已实测返回非空序列。

### `H30184` 中证全指半导体产品与设备指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `H30184` |
| total_return_index_code | `H20184` |
| **net_total_return_index_code** | **NULL** |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,317 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 369 天 |
| 非正收盘 | 1 |
| quality_grade | **C** |
| usable_for_excess_return | **False** |

**限制**：**全收益可取（H20184）**，**净收益确实不存在**（factsheet 为 --）。`return_basis` 保持 unknown。

**本轮修正**：3B-6.1.0 误判「无全收益」。官方 factsheet 披露 H20184（全收益），已实测返回非空；净收益栏为 --，即确实没有。

### `000942` 中证内地消费主题指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000942` |
| total_return_index_code | `H00942` |
| **net_total_return_index_code** | **NULL** |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,318 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 365 天 |
| 非正收盘 | 0 |
| quality_grade | **A** |
| usable_for_excess_return | **False** |

**限制**：价格 + 全收益（H00942）可取；**净收益不可得**。`return_basis` 保持 unknown。

**本轮修正**：净收益代码在 factsheet 中未给出可验证值（CNY020 变体实测返回空）。

### `000012` 上证国债指数

| 字段 | 值 |
| --- | --- |
| provider | 上海证券交易所 |
| price_index_code | `000012` |
| price_or_full_price_index_code | `000012` |
| **clean_price_index_code** | **`H00012`** |
| total_return_index_code | `N00012` |
| **net_total_return_index_code** | **NULL** |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ❌ 未取得 |
| 官方 factsheet | ✅ |
| 价格历史 | 5,559 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 13 天 |
| 非正收盘 | 0 |
| quality_grade | **B** |
| usable_for_excess_return | **False** |

**限制**：**三套序列语义特殊**：000012=全价，H00012=**净价**，N00012=利息及再投资。**H 前缀在此不是全收益、更不是净收益**，命名规则与股票指数不同。三套数值差异极大（206.07 / 104.65 / 145.71）。**未取得官方编制方案**，语义结论来自接口返回名称（L3）。

> ⚠️ **命名惯例警告**：上证国债指数的代码前缀**不能套用股票指数的 H/N 命名惯例**：H00012 = 净价（股票指数里 H 常代表全收益），N00012 = 利息及再投资。若按惯例映射会把净价指数当成全收益/净收益使用，属严重语义错误。

### `000922` 中证红利指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `000922` |
| total_return_index_code | `H00922` |
| **net_total_return_index_code** | `000922CNY020` |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ✅ 已下载解析 |
| 官方 factsheet | ❌ |
| 价格历史 | 5,318 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 365 天 |
| 非正收盘 | 0 |
| quality_grade | **A** |
| usable_for_excess_return | **False** |

**限制**：价格 + 全收益（H00922）+ 净收益（000922CNY020）均可取；`return_basis` 保持 unknown。

**本轮修正**：3B-6.1.0 的 N00922 猜测失败。官方 factsheet 披露净收益代码 000922CNY020，已实测。

### `930930` 中证港股通综合指数

| 字段 | 值 |
| --- | --- |
| provider | 中证指数有限公司 |
| price_index_code | `930930` |
| total_return_index_code | `H20930` |
| **net_total_return_index_code** | **NULL** |
| **return_basis** | **`unknown`** |
| 官方编制方案 | ❌ 未取得 |
| 官方 factsheet | ✅ |
| 价格历史 | 3,000 行 / 2004-01-01 ~ 2026-11-23 |
| 最大间隔 | 3970 天 |
| 非正收盘 | 0 |
| quality_grade | **C** |
| usable_for_excess_return | **False** |

**限制**：**全收益可取（H20930）**，**净收益不存在**。港股通人民币计价与汇率处理规则未查证。`return_basis` 保持 unknown。

**本轮修正**：3B-6.1.0 用 H930930 猜测返回空，误判无全收益。官方 factsheet 披露 H20930，已实测返回非空；净收益栏为 --。

---

## 4. `000012` 三序列语义对照（修正后）

| 代码 | 接口名称 | 语义 | 2024-01-02 收盘 |
| --- | --- | --- | ---: |
| `000012` | 上证国债指数 | 全价 | 206.07 |
| `H00012` | 上证国债指数(**净价**) | **净价指数，不是净收益** | 104.65 |
| `N00012` | 上证国债指数(利息及再投资) | 总收益口径 | 145.71 |

**`N00012` 的 caveat**：接口名称为「利息及再投资」，官方定义**未取得编制方案核验**；
严格意义上它是债券指数的总收益口径，但不等同于股票指数的 `total_return` 定义。
保留该代码仅作记录，**不构成口径升级依据**。

---

## 5. 官方证据搜索记录（任务3要求可追溯）

| 项 | 记录 |
| --- | --- |
| 搜索执行时间 | 2026-11-24 15:52 ~ 16:05 |
| 搜索入口 | csindex 官网 PDF 直链 + web 搜索 + sse.com.cn |
| URL 基址 | `https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/` |

**尝试的文件名模式**：

```
{c}_Index_Methodology_cn.pdf
{c}factsheet.pdf
{c}_Index_Methodology.pdf
{c}_methodology_cn.pdf
```

**搜索关键词**：

- `中证白酒指数 399997 编制方案 csindex 官方`
- `上证国债指数 000012 编制方案 上海证券交易所 官方`
- `site:sse.com.cn 上证国债指数 000012 编制`

**未取得编制方案的 2 个指数**：

| 指数 | 原因 |
| --- | --- |
| `000012` | csindex 直链 404；上交所 sse.com.cn 指数页 404；仅有 factsheet |
| `930930` | csindex 直链 404；仅有 factsheet |

**未采用伪造或无关文件凑数。** 缺失即如实标记。

---

## 6. 本轮**没有**做的事

| 项 | 状态 |
| --- | --- |
| 升级任何指数 `return_basis` | **否**（仍全部 unknown） |
| 写入指数行情 | **否** |
| 修改 `index_master` | **否** |
| 把净价当净收益 | **否**（已修正为 null） |
| 用接口字段名冒充官方口径证明 | **否**（已区分 L2 文件 / L3 factsheet） |
| 凑齐 10 份文件 | **否**（缺 2 份如实标记） |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
