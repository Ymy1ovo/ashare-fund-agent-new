# 阶段3A.3.2.1 证据质量报告

- 生成时间：2026-11-13
- 数据：`corporate_actions` 166 条
- 结论：**上一阶段把 166 条全部标成 `confirmed` 属于过度声称，本阶段已纠正**

## 1. 上一阶段的问题

3A.3.2 的核查报告明确写了「165/166 条只有单一第三方来源（天天基金）」，
但数据库里 166 条**全部** `status='confirmed'`，并且全部进入了回测。

这违反了原始任务书「不得将第三方推断标为官方确认」的要求。

## 2. 本阶段的证据规则

新增 `evidence_status` 字段（与 `status` 并存，不破坏现有接口）：

| 等级 | 定义 | 能否进回测 |
| --- | --- | :---: |
| `official_confirmed` | 能定位到**基金管理人公告原文**（独立公告 ID + 正文），且正文可核对出与数据库一致的除息日 / 比例 / 金额 | ✅ |
| `secondary_confirmed` | 有公告原文，但部分要素无法从正文核对；至少有 1 项关键要素一致 | ✅ |
| `unverified` | 找不到公告，或正文无法核对任何关键要素 | ❌ |
| `rejected` | 已确认属于错误数据或错误事件 | ❌ |

### 2.1 证据来源

**东方财富基金公告接口**（转载基金管理人公告全文，不是产品页面）：

| 用途 | 接口 |
| --- | --- |
| 公告列表 | `https://api.fund.eastmoney.com/f10/JJGG?fundCode={code}&type=2` |
| 公告正文 | `https://np-cnotice-fund.eastmoney.com/api/content/ann?art_code={art}` |
| 公告页面 | `https://fund.eastmoney.com/gonggao/{code},{art}.html` |

抓取结果：**34 只标的、343 条相关公告、323 条可解析**。

**每条事件保存独立的 `announcement_url`**（带具体 `art_code`），
不是统一的网页模板。

### 2.2 核对要素

分红事件核对 4 项：`cash_per_share`、`record_date`、`ex_date`、`pay_date`
拆分事件核对 2 项：`share_ratio`、`ex_date` 或 `record_date`

## 3. 分级结果

| 等级 | 数量 | 占比 |
| --- | ---: | ---: |
| `official_confirmed` | **144** | 86.7% |
| `secondary_confirmed` | **12** | 7.2% |
| `unverified` | **10** | 6.0% |
| `rejected` | **0** | 0% |
| **合计** | **166** | 100% |

### 3.1 上一阶段 vs 本阶段

| 等级 | 3A.3.2 | 3A.3.2.1 |
| --- | ---: | ---: |
| 声称 confirmed | **166** | 156（144 official + 12 secondary） |
| unverified | 0 | **10** |

**降级 10 条**，这是必须的纠正，不是为了维持结果而强行确认。

## 4. 未确认事件明细（10 条）

**全部位于回测区间之外**，对 2021-01-04 ~ 2026-11-09 的回测无影响。

| # | 代码 | 类型 | 除息日 | 比例/金额 | 未确认原因 |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `510050` | split | 2005-02-04 | 1.1838 | 公告库最早只到 2006 年 |
| 2 | `159901` | reverse_split | 2006-04-14 | 0.9495 | 公告库无该年记录 |
| 3 | `510880` | reverse_split | 2007-01-10 | 0.6553 | 公告库无该年记录 |
| 4 | `159901` | split | 2010-11-19 | 5.0 | 公告库无该年记录 |
| 5 | `510150` | reverse_split | 2011-02-11 | 0.3296 | 公告库无该年记录 |
| 6 | `159915` | split | 2011-11-30 | 1.1456 | 公告库无该年记录 |
| 7 | `510300` | reverse_split | 2012-05-11 | 0.3709 | 公告库无该年记录 |
| 8 | `511010` | reverse_split | 2013-03-05 | 0.01 | 有公告但正文只写「折算日」，无比例 |
| 9 | `159901` | reverse_split | 2014-08-29 | 0.2 | 公告库无该年记录 |
| 10 | `510880` | cash_distribution | 2016-01-20 | 0.05 | 有公告但金额写法无法解析 |

### 4.1 为什么不能强行确认

| 诱惑 | 为什么不这么做 |
| --- | --- |
| 用价格跳变反推比例 | 任务书明令禁止；且 8 条中已有 1 条（`511010` 0.01）与价格跳变吻合，但「吻合」不等于「有公告」 |
| 用天天基金页面数字 | 天天基金的分红送配页是**产品页面**，不是公告原文，不满足「能定位到实际基金管理人公告内容」 |
| 保持全部 confirmed | 会重犯上一阶段的错误 |

**如实保留未确认状态。**

## 5. secondary_confirmed 的 12 条

这些事件**有公告原文**，但公告正文的部分要素被表格拍平、无法精确解析：

| # | 代码 | 类型 | 除息日 | 已核对 | 缺失 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `518800` | reverse_split | 2013-07-24 | 日期 | 比例 |
| 2 | `518880` | reverse_split | 2013-07-24 | 日期 | 比例 |
| 3 | `159934` | reverse_split | 2013-12-11 | 日期 | 比例 |
| 4 | `159937` | reverse_split | 2014-08-27 | 日期 | 比例 |
| 5 | `511220` | reverse_split | 2014-12-03 | 日期 | 比例 |
| 6 | `511220` | cash_distribution | 2015-06-18 | 日期 | 金额 |
| 7 | `511220` | cash_distribution | 2015-09-21 | 日期 | 金额 |
| 8 | `511260` | reverse_split | 2017-08-04 | 日期 | 比例 |
| 9 | `511030` | reverse_split | 2019-02-20 | 日期 | 比例 |
| 10 | `511380` | reverse_split | 2020-03-27 | 日期 | 比例 |
| 11 | `511360` | reverse_split | 2020-08-24 | 日期 | 比例 |
| 12 | `588000` | reverse_split | 2020-11-09 | 日期 | 比例 |

**同样全部位于回测区间之外。**

## 6. 回测区间的证据覆盖

| 区间 | official_confirmed | secondary_confirmed | unverified |
| --- | ---: | ---: | ---: |
| 样本内（2021-01-04 ~ 2024-12-31） | **49** | 0 | 0 |
| 样本外（2025-01-02 ~ 2026-11-09） | **32** | 0 | 0 |
| 区间外 | 63 | 12 | 10 |

**回测区间内 81 条事件 100% 为 `official_confirmed`。**

这意味着本次重放的结论**不受证据等级不足的影响**，
但报告仍必须披露：库内另有 22 条 non-official 事件，只是它们全部在区间外。

## 7. 引擎如何对待证据等级

```python
# app/backtest/corporate_actions.py
APPLICABLE_EVIDENCE = (EVIDENCE_OFFICIAL, EVIDENCE_SECONDARY)

@property
def is_confirmed(self) -> bool:
    return (self.status == STATUS_CONFIRMED
            and self.evidence_status in APPLICABLE_EVIDENCE)
```

两道关：
- `status`：保留兼容（`confirmed` / `unverified` / `rejected`）
- `evidence_status`：证据等级

**必须同时通过。**

未通过的事件：
- 引擎完全不应用（不调数量、不加现金、不加应收）
- 写入 `result.notes`：`公司行为：N 条未确认事件因证据等级不足未应用（unverified_corporate_action）；涉及标的 X,Y`
- 记入 `engine.excluded_actions`，可由报告读取

## 8. 公告元数据

每条事件现保存：

| 字段 | 内容 | 示例 |
| --- | --- | --- |
| `announcement_title` | 公告标题 | 「华泰柏瑞沪深300交易型开放式指数证券投资基金分红公告」 |
| `announcement_date` | 公告日期 | 2021-01-11 |
| `announcement_url` | 独立公告页 | `https://fund.eastmoney.com/gonggao/510300,AN202101111449474410.html` |
| `manager_name` | 基金管理人 | 华泰柏瑞基金管理有限公司 |

**每条事件的 URL 都不同**（带独立 `art_code`），可逐条复核。

## 9. 复现方式

```bash
# 1. 抓取公告（只读，约 8 分钟）
python scripts/fetch_ca_announcements.py

# 2. 匹配并分级
python scripts/match_ca_evidence.py

# 3. 回写数据库（版本化，不覆盖历史）
python scripts/apply_evidence_status.py
```

三个脚本的输出可逐条核对，报告中的每个数字都能从
`data/ca_ann_match.json` 与数据库查询重新计算。

## 10. 局限

| # | 局限 | 说明 |
| ---: | --- | --- |
| 1 | 公告来源仍是转载站 | 东方财富转载基金管理人公告全文，含公告编号；但不是基金公司官网原始 PDF |
| 2 | 2013 年之前公告覆盖不全 | 10 条 unverified 全部在此范围 |
| 3 | 正文解析用正则 | 表格被拍平时可能误判，因此设了 `secondary_confirmed` 中间档 |
| 4 | 未做人工逐条复核 | 144 条 official 靠程序核对 4 项要素，未人工读完全部正文 |
| 5 | `rejected` 目前为 0 | 本阶段未发现确认错误的事件 |
