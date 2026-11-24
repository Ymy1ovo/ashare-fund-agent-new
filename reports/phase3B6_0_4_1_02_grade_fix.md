# 阶段3B-6.0.4.1 组级质量等级修正说明

- 本轮基线 HEAD：`a31270683f1417813ad8ac650fc5ebd9be32b79f`  数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`
- 执行：2026-11-24 14:15

---

## 0. 问题定位

3B-6.0.4 的 `phase3B6_0_4_09_data_quality.json` 把 `bond_pure|unknown` 标为 **C**，
但 3B-5.5.1 既定规则要求 **D**。

### 0.1 根因

报告生成时**自建了一张映射表**，绕过了权威函数：

```python
grade = {"comparable": "B", "descriptive_only": "C", "excluded": "D"}
```

`bond_pure|unknown` 的可用性状态是 `descriptive_only`（样本≥2 但不满足可比较条件），
于是被这张表无差别映射成 **C**——**完全忽略了「基准族 unknown → D」这条铁律**。

| 层 | 3B-6.0.4 的做法 | 问题 |
| --- | --- | --- |
| `quality.grade_peer_comparison` | 正确判 D | 无（逻辑本身对） |
| 报告生成脚本 | 自建状态→等级映射 | **绕过了权威函数** |

**即：规则没错，是报告没调用规则。**

---

## 1. 修正方案

### 1.1 单一权威来源

在 `peer_engine.py` 新增 `group_quality_grade()`，**只做参数组装**，
判定完全委托给 `quality.grade_peer_comparison()`：

```python
def group_quality_grade(peer_key, member_count, peer_ctx=None) -> dict:
    ctx = {'peer_key': peer_key, 'member_count': member_count}
    if peer_ctx: ctx.update({...grouping_source, verifiable_group...})
    return grade_peer_comparison(ctx)   # 唯一权威
```

### 1.2 引擎输出质量等级

`analyze_group()` 现在每组都带 `quality_grade`，
报告**直接读这个字段**，不再自行映射。

### 1.3 没有修改评分规则

| 文件 | 是否修改评分规则 |
| --- | --- |
| `quality.py` | **否**，一行未改 |
| `peer_engine.py` | 只新增调用入口，不改判定逻辑 |

---

## 2. 修正后 28 组等级

| 组键 | 本体数 | 可用性 | 等级 | 状态 |
| --- | ---: | --- | --- | --- |
| `bond_pure|unknown` | 12 | descriptive_only | **D** | no_verifiable_group |
| `money_market` | 7 | comparable | **B** | usable |
| `etf_linked|broad|沪深300` | 5 | comparable | **B** | usable |
| `ordinary_index|broad|中证500` | 5 | comparable | **B** | usable |
| `active_equity|unknown` | 4 | descriptive_only | **D** | no_verifiable_group |
| `ordinary_index|broad|沪深300` | 4 | descriptive_only | **C** | small_sample |
| `active_equity|中证800` | 3 | descriptive_only | **C** | small_sample |
| `active_equity|沪深300` | 3 | descriptive_only | **C** | small_sample |
| `etf_linked|broad|上证50` | 3 | descriptive_only | **C** | small_sample |
| `etf_linked|broad|中证500` | 3 | descriptive_only | **C** | small_sample |
| `etf_linked|broad|中证A500` | 3 | descriptive_only | **C** | small_sample |
| `etf_linked|broad|创业板指` | 3 | descriptive_only | **C** | small_sample |
| `lof|active|unknown` | 3 | descriptive_only | **D** | no_verifiable_group |
| `ordinary_index|broad|中证A500` | 3 | descriptive_only | **C** | small_sample |
| `active_equity|中证500` | 2 | descriptive_only | **C** | small_sample |
| `bond_mixed|unknown` | 2 | descriptive_only | **D** | no_verifiable_group |
| `etf_linked|unknown|unknown` | 2 | descriptive_only | **D** | no_verifiable_group |
| `lof|active|中证800` | 2 | descriptive_only | **C** | small_sample |
| `active_equity|中证A500` | 1 | excluded | **D** | insufficient_peer_sample |
| `etf_linked|broad|unknown` | 1 | excluded | **D** | no_verifiable_group |
| `etf_linked|sector|中证全指半导体` | 1 | excluded | **D** | insufficient_peer_sample |
| `lof|active|中债综合` | 1 | excluded | **D** | insufficient_peer_sample |
| `lof|active|沪深300` | 1 | excluded | **D** | insufficient_peer_sample |
| `lof|index|sector|中证白酒` | 1 | excluded | **D** | insufficient_peer_sample |
| `ordinary_index|broad|上证50` | 1 | excluded | **D** | insufficient_peer_sample |
| `ordinary_index|broad|创业板指` | 1 | excluded | **D** | insufficient_peer_sample |
| `ordinary_index|unknown|unknown` | 1 | excluded | **D** | no_verifiable_group |
| `ordinary_index|unknown|上证50` | 1 | excluded | **D** | insufficient_peer_sample |

| 等级 | 组数 |
| --- | ---: |
| **A** | 0 |
| **B** | 3 |
| **C** | 10 |
| **D** | 15 |

**没有 A 级组**（基准证据全 unknown）。

---

## 3. 关键修正项

| 组键 | 本体数 | 3B-6.0.4 | 本轮 | 依据 |
| --- | ---: | --- | --- | --- |
| `bond_pure|unknown` | 12 | **C**（错） | **D** | 基准族 unknown → D |
| `bond_mixed|unknown` | 2 | **C**（错） | **D** | 基准族 unknown → D |
| `active_equity|unknown` | 4 | **C**（错） | **D** | 基准族 unknown → D |
| `lof|active|unknown` | 3 | **C**（错） | **D** | 基准族 unknown → D |
| `etf_linked|unknown|unknown` | 2 | **C**（错） | **D** | 基准族 unknown → D |

### 3.1 为什么 14 个纯债也必须 D

| 理由 | 说明 |
| --- | --- |
| 组键 `bond_pure\|unknown` | 基准族不可识别 |
| 久期/信用/转债字段全 NULL | 无法证明风险可比 |
| 3B-5.5.1 铁律 | 分组依据不可验证 → D，**与样本量无关** |

**数量达标 ≠ 可比较。**

---

## 4. 货币基金特例（保持不变）

| 项 | 值 |
| --- | --- |
| 组键 | `money_market` |
| 本体数 | 7 |
| 等级 | **B** |
| 依据 | 按产品类型独立分组，不要求指数/业绩基准；≥5 本体 → B |

**`money_market` 不适用「基准族 unknown → D」规则**，
因为它本来就没有基准族，靠产品类型隔离。这条特例是 3B-5.5.1 明确规定的。

---

## 5. Markdown 与 JSON 一致性

修正后两者**读同一个数据源**（`analyze_group()` 返回的 `quality_grade`）：

| 项 | 实现 |
| --- | --- |
| JSON | 直接序列化 `quality_grade` 字段 |
| Markdown | 从同一字段渲染表格 |
| 一致性测试 | `test_report_markdown_and_json_grades_consistent` |

**不存在两套口径。**

---

## 6. 边界

| 项 | 值 |
| --- | --- |
| 修改质量评级规则 | **否**（`quality.py` 零改动） |
| 因样本大而放行 | **否** |
| Markdown/JSON 口径不一致 | **否** |
| 修改正式数据库 | **否** |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
