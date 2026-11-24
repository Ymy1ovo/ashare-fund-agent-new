# 阶段3B-6.0.4.1 LOF 分类修正说明

- 本轮基线 HEAD：`a31270683f1417813ad8ac650fc5ebd9be32b79f`
- 上阶段基线：`f64b7e554d7303c523bb6ba9ee84550b2e0a7a9d`
- 执行时间：2026-11-24 14:15
- 数据指纹：`115ac91eee7c26424952e6df23ddeeafe2435974fe5e81a8ba6bbcabfe387dd4`（**未变**）

---

## 0. 结论先行

| 项 | 修正前 | 修正后 |
| --- | ---: | ---: |
| LOF 本体数 | **3** | **8** |
| active_equity 本体 | 16 | **13** |
| bond_pure 本体 | 14 | **12** |
| 同类组 | 26 | **28** |
| 可比较组 | 4 | **3** |
| `active_equity\|中证800` 本体 | 5（comparable） | **3（descriptive_only）** |

---

## 1. 问题定位

`classify_fund()` 原来只检查 `fund_name` 是否含 `(LOF)`：

```python
if "(LOF)" in name or "（LOF）" in name:
```

但库内 **5 只**基金的简称被截断，全称才含 LOF：

| 代码 | 简称 | 全称 |
| --- | --- | --- |
| `001883` | 中欧新动力混合 | 中欧新动力混合型证券投资基金(LOF) |
| `001886` | 中欧成长 | 中欧行业成长混合型证券投资基金(LOF) |
| `001888` | 中欧盛世成长 | 中欧盛世成长混合型证券投资基金(LOF) |
| `001889` | 中欧增强回报债券 | 中欧增强回报债券型证券投资基金(LOF) |
| `002592` | 中欧纯债 | 中欧纯债债券型证券投资基金(LOF) |

---

## 2. 字段审查（任务要求第 1 项）

| 项 | 结果 |
| --- | --- |
| 全称列名 | **`fund_full_name`** |
| 来源 | `akshare.fund_individual_basic_info_xq`（78 条）/ `dfcfw.announcement.calibrated`（41 条） |
| 覆盖率 | **119 / 120** 本体有全称 |
| 唯一缺失 | `000198` 天弘余额宝货币（货币基金，不影响 LOF 判定） |
| 可靠性 | 来自基金合同级全称，**不是**模糊字符串 |

---

## 3. 修正方案

### 3.1 新增证据判定函数

```python
def detect_lof(name, full_name) -> dict:
    # 只认明确的 LOF 标记，不做模糊匹配
    name_hit = any(t in n for t in ("(LOF)", "（LOF）"))
    full_hit = any(t in f for t in ("(LOF)", "（LOF）", "LOF)"))
    # both / short_name / full_name / none
```

### 3.2 三条铁律保持不变

| 铁律 | 实现 |
| --- | --- |
| LOF 产品结构优先于投资子类型 | LOF 判定在 `is_idx` 分支之前 |
| 指数型 LOF → `lof/index` | `is_index_fund=1` |
| 主动型 LOF → `lof/active` | `is_index_fund!=1` |

### 3.3 数据通路修正

| 文件 | 修正 |
| --- | --- |
| `data_access.py` | `load_universe()` SELECT 增加 `m.fund_full_name` |
| `lookup.py` | `_SELECT` 增加 `m.fund_full_name` |
| `ingest_user_funds/_impl.py` | `_existing_fund()` SELECT 与 `classify_fund()` 调用带全称 |

**若不改数据通路，只改 `classify_fund()` 是无效的**——
全称根本传不到分类器。这是本轮的关键发现。

---

## 4. 5 只基金分类前后对照

| 代码 | 简称 | 修正前 | 修正后 | 识别依据 | 证据字段 |
| --- | --- | --- | --- | --- | --- |
| `001883` | 中欧新动力混合 | **active_equity** | **lof** | 全称含 LOF | `fund_full_name` |
| `001886` | 中欧成长 | **active_equity** | **lof** | 全称含 LOF | `fund_full_name` |
| `001888` | 中欧盛世成长 | **active_equity** | **lof** | 全称含 LOF | `fund_full_name` |
| `001889` | 中欧增强回报债券 | **bond_pure** | **lof** | 全称含 LOF | `fund_full_name` |
| `002592` | 中欧纯债 | **bond_pure** | **lof** | 全称含 LOF | `fund_full_name` |

**全部 5 只已正确归入 LOF，无一遗漏，无一误改。**

---

## 5. 79 个研究池本体分类复核

### 5.1 简称/全称 LOF 一致性审计

| 情形 | 数量 | 处理 |
| --- | ---: | --- |
| 简称+全称均含 LOF | 2 | 识别为 LOF |
| 仅简称含 LOF | 1 | 识别为 LOF（全称缺 LOF 标记，已标注） |
| **仅全称含 LOF** | **5** | **本轮修正为 LOF** |
| 均不含 | 71 | 非 LOF |

**未发现其他简称/全称不一致情况。**

### 5.2 修正前后分类分布

| 产品类型 | 修正前 | 修正后 | 变化 |
| --- | ---: | ---: | --- |
| ordinary_index | 16 | **16** | +0 |
| etf_linked | 21 | **21** | +0 |
| active_equity | 16 | **13** | -3 |
| bond_pure | 14 | **12** | -2 |
| bond_mixed | 2 | **2** | +0 |
| money_market | 7 | **7** | +0 |
| lof | 3 | **8** | +5 |
| **合计** | **79** | **79** | — |

### 5.3 全 8 只 LOF 明细

| 代码 | 简称 | 子类型 | 组键 | 证据 |
| --- | --- | --- | --- | --- |
| `161725` | 招商中证白酒指数(LOF) | index | `lof|index|sector|中证白酒` | short_name |
| `161005` | 富国天惠成长混合(LOF) | active | `lof|active|unknown` | both |
| `000673` | 融通四季添利债(LOF) | active | `lof|active|中债综合` | both |
| `001883` | 中欧新动力混合 | active | `lof|active|中证800` | full_name |
| `001886` | 中欧成长 | active | `lof|active|中证800` | full_name |
| `001888` | 中欧盛世成长 | active | `lof|active|沪深300` | full_name |
| `001889` | 中欧增强回报债券 | active | `lof|active|unknown` | full_name |
| `002592` | 中欧纯债 | active | `lof|active|unknown` | full_name |

### 5.4 待核实项

| 项 | 状态 |
| --- | --- |
| `161725` 招商中证白酒指数(LOF) | 简称含 LOF、全称不含。**按简称识别**，
  该基金确为 LOF（深交所上市），全称缺标记属数据源写法差异，已标注 |
| `000198` 天弘余额宝货币 | 无全称。货币基金，**不涉及 LOF 判定** |

**两者均不是猜测，证据链完整。**

---

## 6. 对同类分组的影响

| 项 | 修正前 | 修正后 |
| --- | ---: | ---: |
| 同类组 | 26 | **28** |
| 可比较 | 4 | **3** |
| 仅描述性 | 12 | **15** |
| 排除 | 10 | **10** |

### 6.1 `active_equity\|中证800` 组

| 项 | 修正前 | 修正后 |
| --- | ---: | ---: |
| 本体数 | 5 | **3** |
| 状态 | `comparable` | **`descriptive_only`** |
| 质量等级 | B | **C** |

**该组不再因 LOF 误分类而虚增样本。**

---

## 7. 工程边界

| 项 | 值 |
| --- | --- |
| 修改数据库 Schema | **否** |
| 修改正式数据库内容 | **否**（指纹未变） |
| 重新采集数据 | **否** |
| 修改指数数据层 | **否** |
| 修改超额收益阻断规则 | **否** |
| 修改既有指标公式 | **否** |
| 修改场内 ETF 回测 | **否** |
| 开放正式排名 / 回测 | **否** |
| 生成买卖建议 | **否** |
| 删除/跳过/弱化原有测试 | **否** |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
