"""阶段3B-5.0 研究性分析框架与数据准入审计（只读）。

不写库、不采集、不计排名、不出信号。
输出：
  reports/phase3B5_0_research_framework.json
  reports/phase3B5_0_data_admission_matrix.json

两块内容：
1. 基金产品类型分类体系（场外 vs 场内、本体 vs 份额、A/C 归并）
2. 数据使用准入矩阵（15 项数据逐项审查）
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection, settings  # noqa: E402

DB = Path(settings.database_path)
NOW = datetime.now()
LIFECYCLE_SOURCE = "dfcfw.announcement.calibrated"
CALIB = ROOT / "reports" / "phase3B4_1_1_types_evidence_calibration.json"

# ---------------------------------------------------------------- 产品类型体系
# 六类场外 + 场内 ETF 隔离
PRODUCT_TAXONOMY = {
    "ordinary_index": {
        "label": "普通开放式指数基金",
        "in_default_pool": True,
        "rationale": "跟踪指数、费率低、长期可持有，是场外核心研究对象",
        "identity_fields": ["is_index_fund", "tracking_index", "benchmark"],
        "subgroups": ["宽基指数", "行业主题指数", "策略指数"],
        "comparison_rule": ("宽基与行业主题必须分开比较；"
                            "不同跟踪指数不得混排"),
    },
    "etf_linked": {
        "label": "ETF 联接基金",
        "in_default_pool": True,
        "rationale": "场外可申购、跟踪场内 ETF，属场外研究对象",
        "identity_fields": ["fund_name 含「ETF联接」", "is_index_fund", "benchmark"],
        "subgroups": ["宽基联接", "行业联接"],
        "comparison_rule": "与直接指数基金可比，但需注明是否含 ETF 折溢价传导",
    },
    "active_equity": {
        "label": "主动权益基金",
        "in_default_pool": True,
        "rationale": "支付宝主销品类之一",
        "identity_fields": ["fund_type_l1 in (股票型, 混合型-偏股)",
                            "is_index_fund != 1"],
        "subgroups": ["普通股票型", "偏股混合型", "灵活配置型"],
        "comparison_rule": "必须按可验证的业绩基准分组，不得与指数基金混排",
    },
    "bond_pure": {
        "label": "普通债券基金",
        "in_default_pool": True,
        "rationale": "低波动配置需求，支付宝场外有售",
        "identity_fields": ["fund_type_l1 含「债券型」", "不含二级债基特征"],
        "subgroups": ["长债", "中短债", "纯债"],
        "comparison_rule": "按久期分组；久期字段缺失则标 unknown",
    },
    "bond_mixed": {
        "label": "混合债券基金",
        "in_default_pool": True,
        "rationale": "含权益或转债暴露，风险特征与纯债不同",
        "identity_fields": ["fund_type_l1 含「债券型」+ 含权特征"],
        "subgroups": ["二级债基", "可转债基金"],
        "comparison_rule": "不得与纯债混排；转债暴露未知时标 unknown",
    },
    "money_market": {
        "label": "货币基金",
        "in_default_pool": True,
        "rationale": "现金管理工具",
        "identity_fields": ["fund_type_l1 含「货币型」"],
        "subgroups": ["普通货币", "理财型货币"],
        "comparison_rule": ("独立收益口径（每万份收益/7日年化），"
                            "**不得**与净值型基金计算同类收益/回撤"),
    },
    "qdii": {
        "label": "QDII 基金",
        "in_default_pool": False,
        "rationale": "跨境投资、汇率与交易时区不同，口径特殊",
        "identity_fields": ["fund_type_l1 含 QDII"],
        "subgroups": [],
        "comparison_rule": "样本为 0，本轮不纳入研究池",
    },
    "lof": {
        "label": "LOF 基金",
        "in_default_pool": True,
        "rationale": "场外可申购（虽也场内交易），属场外研究对象",
        "identity_fields": ["fund_name 含 (LOF)", "或 product_structure='lof'"],
        "subgroups": ["指数型 LOF", "主动型 LOF"],
        "comparison_rule": "按底层是主动还是指数再分组",
    },
    "onshore_etf": {
        "label": "场内 ETF",
        "in_default_pool": False,
        "rationale": ("**仅保留历史研究**。场内 ETF 需证券账户，"
                      "不是支付宝场外产品"),
        "identity_fields": ["product_structure='etf'", "代码 511000/511050"],
        "subgroups": [],
        "comparison_rule": "**禁止**混入场外默认研究池",
    },
}

SHARE_CLASS_RULES = {
    "principle": "A/C/E 是同一基金本体的不同份额，共享同一投资组合",
    "merge_rule": ("比较策略表现时先按 fund_id 归并到基金本体"
                   "（用主份额净值代表组合表现）"),
    "split_rule": ("比较持有成本时再按份额单独比较"
                   "（销售服务费、申购费差异）"),
    "never_merge": [
        "不同 fund_id 的基金不得归并",
        "货币基金份额不得与净值型份额归并",
    ],
    "primary_share_rule": "每个本体恰好一个 is_primary=1 主份额（3B-4.2 已验收）",
}


def audit_taxonomy(conn) -> dict:
    # 现有 12 份额对应本体
    rows = conn.execute(
        """SELECT m.fund_id, m.fund_code_primary, m.fund_name, m.fund_type_l1,
                  m.fund_type_l2, m.is_index_fund, m.benchmark,
                  m.established_date, m.lifecycle_status,
                  COUNT(s.share_class_id) shares,
                  SUM(CASE WHEN s.is_primary=1 THEN 1 ELSE 0 END) primaries
           FROM fund_master m
           JOIN fund_share_classes s ON s.fund_id = m.fund_id
           WHERE m.lifecycle_status = 'unknown'
           GROUP BY m.fund_id ORDER BY m.fund_code_primary""").fetchall()

    classified = []
    for r in rows:
        t = classify_one(r)
        classified.append({
            "fund_id": int(r["fund_id"]),
            "code": r["fund_code_primary"],
            "name": r["fund_name"],
            "fund_type_l1": r["fund_type_l1"],
            "is_index_fund": r["is_index_fund"],
            "share_count": int(r["shares"]),
            "primaries": int(r["primaries"]),
            "product_class": t["product_class"],
            "in_default_pool": t["in_default_pool"],
            "classification_basis": t["basis"],
            "classification_confidence": t["confidence"],
        })

    # 清盘本体：分类靠校准 JSON，库里字段全空
    lifecycle = conn.execute(
        """SELECT product_structure, COUNT(*) n
           FROM fund_lifecycle_events WHERE source=? GROUP BY 1""",
        (LIFECYCLE_SOURCE,)).fetchall()
    term_by_struct = {r["product_structure"]: int(r["n"]) for r in lifecycle}

    # 清盘本体字段覆盖
    cov = conn.execute(
        """SELECT
             SUM(CASE WHEN m.fund_type_l1 IS NULL THEN 1 ELSE 0 END) no_l1,
             SUM(CASE WHEN m.is_index_fund IS NULL THEN 1 ELSE 0 END) no_idx,
             SUM(CASE WHEN m.benchmark IS NULL THEN 1 ELSE 0 END) no_bench,
             SUM(CASE WHEN m.established_date IS NULL THEN 1 ELSE 0 END) no_est,
             COUNT(*) n
           FROM fund_lifecycle_events l
           JOIN fund_master m ON m.fund_id = l.fund_id
           WHERE l.source = ?""", (LIFECYCLE_SOURCE,)).fetchone()

    calibration = {}
    if CALIB.is_file():
        cal = json.loads(CALIB.read_text(encoding="utf-8"))
        by_type = defaultdict(int)
        by_struct = defaultdict(int)
        for x in cal.get("calibration") or []:
            by_type[x.get("investment_type")] += 1
            by_struct[x.get("product_structure")] += 1
        calibration = {"investment_type": dict(by_type),
                       "product_structure": dict(by_struct)}

    return {
        "taxonomy": PRODUCT_TAXONOMY,
        "share_class_rules": SHARE_CLASS_RULES,
        "offmarket_vs_onshore": {
            "default_pool": "场外（ordinary_open_ended / etf_linked / lof）",
            "excluded": ["onshore_etf"],
            "onshore_etf_codes": ["511000", "511050"],
            "rule": ("场内 ETF 仅保留历史研究，**不得**混入场外默认研究池；"
                     "两者费用、交易机制、申赎方式完全不同"),
        },
        "current_sample": {
            "non_terminated_funds": len(classified),
            "share_records": sum(x["share_count"] for x in classified),
            "classification_complete": all(
                x["product_class"] != "unknown" for x in classified),
            "funds": classified,
        },
        "terminated_funds": {
            "count": sum(term_by_struct.values()),
            "by_product_structure": term_by_struct,
            "classification_source": ("清算事件分类来自 3B-4.1.1 校准 JSON"
                                      "（investment_type 字段），"
                                      "**不是**库里 fund_type_l1"),
            "field_coverage": {
                "fund_type_l1_null": int(cov["no_l1"]),
                "is_index_fund_null": int(cov["no_idx"]),
                "benchmark_null": int(cov["no_bench"]),
                "established_date_null": int(cov["no_est"]),
                "total": int(cov["n"]),
            },
            "calibration_type_distribution": calibration,
            "warning": ("41 个清盘本体的 fund_type_l1 / is_index_fund / benchmark / "
                        "established_date **全部为 NULL**，分类只能依赖 3B-4.1.1 校准 JSON；"
                        "不得当作已有完整分类字段"),
        },
    }


def classify_one(r) -> dict:
    """按库内字段做可解释分类，缺字段就 unknown，不猜。"""
    name = r["fund_name"] or ""
    l1 = r["fund_type_l1"] or ""
    l2 = r["fund_type_l2"] or ""
    is_idx = r["is_index_fund"]

    if "货币" in l1:
        return {"product_class": "money_market", "in_default_pool": True,
                "basis": "fund_type_l1 含「货币型」", "confidence": "high"}
    if "QDII" in l1.upper():
        return {"product_class": "qdii", "in_default_pool": False,
                "basis": "fund_type_l1 含 QDII", "confidence": "high"}
    if "ETF联接" in name or "ETF联接" in name.replace(" ", ""):
        return {"product_class": "etf_linked", "in_default_pool": True,
                "basis": "基金名称含「ETF联接」", "confidence": "high"}
    if "(LOF)" in name or "（LOF）" in name:
        if is_idx == 1:
            return {"product_class": "ordinary_index", "in_default_pool": True,
                    "basis": "名称含 (LOF) 且 is_index_fund=1（指数型 LOF）",
                    "confidence": "high"}
        return {"product_class": "lof", "in_default_pool": True,
                "basis": "名称含 (LOF) 且非指数型", "confidence": "high"}
    if is_idx == 1:
        return {"product_class": "ordinary_index", "in_default_pool": True,
                "basis": "is_index_fund=1 且非 ETF 联接/LOF",
                "confidence": "high"}
    if "债券" in l1:
        if "二级" in l2 or "转债" in l2:
            return {"product_class": "bond_mixed", "in_default_pool": True,
                    "basis": "债券型 + l2 含二级/转债", "confidence": "medium"}
        return {"product_class": "bond_pure", "in_default_pool": True,
                "basis": "fund_type_l1 含「债券型」", "confidence": "high"}
    if "股票" in l1 or "混合" in l1:
        return {"product_class": "active_equity", "in_default_pool": True,
                "basis": "fund_type_l1 为股票型/混合型且非指数",
                "confidence": "high"}
    return {"product_class": "unknown", "in_default_pool": False,
            "basis": "库内分类字段不足以判定", "confidence": "none"}


# ---------------------------------------------------------------- 数据准入矩阵
def build_admission(conn) -> dict:
    """15 项数据逐项审查。全部依据 3B-4.3 / 3B-4.4 真实审计结果。"""

    def cnt(sql, *a):
        return conn.execute(sql, a).fetchone()[0]

    nav_net = cnt("SELECT COUNT(*) FROM fund_nav_daily WHERE nav_kind='net_value'")
    nav_money = cnt("SELECT COUNT(*) FROM fund_nav_daily WHERE nav_kind='money_yield'")
    div_total = cnt("SELECT COUNT(*) FROM fund_dividends")
    fee_total = cnt("SELECT COUNT(*) FROM fund_fee_rules")
    fee_eff = cnt("SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NOT NULL")
    fee_annual = cnt("SELECT COUNT(*) FROM fund_fee_rules WHERE is_annual=1")
    mgr_dated = cnt("SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NOT NULL")
    mgr_total = cnt("SELECT COUNT(*) FROM fund_manager_history")
    aum_total = cnt("SELECT COUNT(*) FROM fund_aum_history")
    aum_evi = cnt("SELECT COUNT(*) FROM fund_aum_history WHERE evidence_level IS NOT NULL")
    aum_dates = cnt("SELECT COUNT(DISTINCT report_date) FROM fund_aum_history "
                    "WHERE evidence_level IS NOT NULL")
    established = cnt("SELECT COUNT(*) FROM fund_master WHERE established_date IS NOT NULL")
    term = cnt("SELECT COUNT(*) FROM fund_lifecycle_events WHERE source=?",
               LIFECYCLE_SOURCE)
    alipay_unknown = cnt("SELECT COUNT(*) FROM fund_subscription_status "
                         "WHERE alipay_purchasable='unknown'")
    alipay_all = cnt("SELECT COUNT(*) FROM fund_subscription_status")

    def item(key, name, source, coverage, evidence, window,
             descriptive, point_in_time, cost_sim, forbidden, risks):
        return {
            "key": key, "name": name, "source": source, "coverage": coverage,
            "evidence_level": evidence, "usable_window": window,
            "descriptive_ok": descriptive, "point_in_time_ok": point_in_time,
            "cost_simulation_ok": cost_sim, "forbidden_for_backtest": forbidden,
            "main_risks": risks,
        }

    items = [
        item("unit_nav", "单位净值",
             "akshare.fund_open_fund_info_em（天天基金）",
             f"{nav_net} 行 / 11 个份额",
             "C",
             "各份额自身历史区间（最早 2005-11-16，最新 2026-11-18）",
             True, False, False, False,
             ["无真实净值公布日历，连续性 cannot_verify",
              "只反映单只基金自身序列，跨基金日期不可强制对齐",
              "不能确认某交易日缺净值就是数据缺失"]),

        item("acc_nav", "累计净值",
             "同上", f"{nav_net} 行（acc_nav 列）", "C",
             "同上", True, False, False, False,
             ["与单位净值口径不同（含分红再投资假设），禁止混用",
              "分红完整性未验证，累计净值中隐含的分红部分无法独立核对"]),

        item("per_10k_yield", "货币基金每万份收益",
             "同上", f"{nav_money} 行 / 1 个份额（000198）", "C",
             "2013-05-30 ~ 2026-11-18", True, False, False, False,
             ["**与净值型基金口径完全不同**，不得参与净值收益/回撤计算",
              "单位是「元/万份」，不是收益率"]),

        item("seven_day_annual", "7日年化收益率",
             "同上", f"{nav_money} 行 / 1 个份额", "C",
             "2013-05-30 ~ 2026-11-18", True, False, False, False,
             ["是年化换算后的**参考值**，不是已实现收益",
              "不得与净值型基金的年化收益直接比较"]),

        item("dividend", "分红",
             "akshare.fund_open_fund_info_em", f"{div_total} 条 / 5 个份额", "C",
             "2006-02-17 ~ 2026-11-11（覆盖不全）",
             True, False, False, True,
             ["接口单次返回不完整（3B-3.1 实测同基金不同请求结果不同）",
              "3B-4.4 跨来源核验：44 条中 35 条匹配公告、4 条公告在 DB 缺失",
              "**禁止用于修正历史收益**"]),

        item("management_fee", "管理费",
             "fundf10.eastmoney.com（F10 费率页）",
             f"{fee_annual} 条年化费率中管理费约 12 条", "C（11 条生效日部分 A-）",
             "仅当前费率；11 条有生效日可切分", True, False, True, True,
             ["年化费率从净值中已扣除，**不得在成本模拟里重复计提**",
              "79 条无生效日，不能还原历史费率",
              "生效日之前必须用 detail.rate_before"]),

        item("custody_fee", "托管费",
             "同上", f"约 12 条", "C（部分 A-）",
             "仅当前费率；部分有生效日", True, False, True, True,
             ["同上：已在净值中扣除",
              "与申购赎回费性质不同，不能混算为「交易成本」"]),

        item("sales_service_fee", "销售服务费",
             "同上", "约 12 条（含 1 条 NULL）", "C",
             "仅当前费率，**全部无生效日**", True, False, True, True,
             ["110022 该字段页面为 ---，存 NULL 不当 0",
              "C 类份额特有，A 类通常为 0",
              "已在净值中扣除，不得重复计提"]),

        item("purchase_fee", "申购费",
             "同上", "20 条金额阶梯", "C",
             "仅当前费率，**全部无生效日**", True, False, True, True,
             ["平台优惠费率是天天基金，**不代表支付宝**",
              "阶梯金额边界含推断下界（lower_inferred=1）",
              "**全部无生效日**（effective_from 全 NULL），不能还原历史申购费率"]),

        item("redemption_fee", "赎回费",
             "同上", "34 条持有期阶梯", "C",
             "仅当前费率，**全部无生效日**", True, False, True, True,
             ["持有期按自然日还是交易日**未确认**（holding_days_basis 全 NULL）",
              "区间开闭部分未知，档位可能差一档",
              "**全部无生效日**（effective_from 全 NULL），不能还原历史赎回费率"]),

        item("aum", "基金规模",
             "fundf10.eastmoney.com/gmbd（规模变动页）",
             f"{aum_total} 条（{aum_evi} 条有证据）/ {aum_dates} 个平台观测日期", "C",
             "2005-12-31 ~ 2026-09-30（平台观测日期，非验证报告期末）",
             True, False, False, True,
             ["日期语义是 platform_observation_date，报告期末**未核实**",
              "138 个日期中 54 个不是季末",
              "disclosed_at 全 NULL，公开可见时间 unknown",
              "**禁止作为历史时点因子/回测已知信息**（未来信息泄漏）"]),

        item("manager_history", "基金经理任职历史",
             "基金经理变更公告（东财公告库转发）",
             f"{mgr_total} 条（{mgr_dated} 条有起始日）", "A-（有日期部分）/ C（快照）",
             "仅已知任职区间的基金", True, False, False, True,
             ["部分记录仍是快照（无任职日期）",
              "不能回填历史，不能用当前经理名单反推过去",
              "无「某时点在任经理完整名单」的序列"]),

        item("established_date", "基金成立日期",
             "akshare 基本信息",
             f"{established} / 50 个本体有值（41 个清盘本体全 NULL）", "C",
             "单一时点，无时间序列属性", True, False, False, False,
             ["41 个清盘本体成立日期全 NULL",
              "成立日期可用于过滤「成立不足 N 年」，但不得推断业绩"]),

        item("termination_events", "基金终止/清盘事件",
             "东财公告库（3B-4.1.1 校准）", f"{term} 条已知事件", "B",
             "2015-11-06 ~ 2026-07-31（公告日期）", True, True, False, False,
             ["清盘名录覆盖率 **not_quantifiable**，不是全量名录",
              "幸存者偏差 **未消除**",
              "12 条缺 event_date（只有公告日期）",
              "可用于剔除已知清盘，**不得**声称覆盖完整"]),

        item("alipay_purchasable", "支付宝可购买状态",
             "无公开合法数据源",
             f"{alipay_all} 条记录，**全部 unknown**", "unknown",
             "无有效期（未取得任何证据）", False, False, False, True,
             ["支付宝无公开合法接口，禁止逆向 APP / 绕过登录",
              "天天基金「开放申购」**不代表**支付宝可买",
              "**unknown 不等于 false**，不得当作「不可购买」",
              "转人工核验，核验结果需带 verified_at，90 天过期"]),
    ]

    return {
        "items": items,
        "item_count": len(items),
        "field_semantics": {
            "descriptive_ok": "可用于描述性分析（看历史长什么样）",
            "point_in_time_ok": ("可作为「投资者在该时点已知道」的信息使用；"
                                 "false 表示存在未来信息泄漏风险"),
            "cost_simulation_ok": ("可用于**当前费率情景**下的成本估算；"
                                   "true 不等于可用于历史区间成本还原"),
            "forbidden_for_backtest": ("禁止用于正式历史回测；"
                                       "与 cost_simulation_ok 不矛盾——"
                                       "费率可为当前情景估成本，但无历史生效日故不能回测"),
        },
        "principles": [
            "unknown 不等于 false，NULL 不等于 0",
            "接口能返回不等于证据等级高",
            "已在净值中扣除的费率不得重复计提",
            "平台日期不等于报告期末，报告期末不等于投资者已知",
            "已知清盘清单不等于全量清盘名录",
        ],
        "evidence_levels": {
            "A": "官方原始来源，可追溯原始公告或正式文件",
            "A-": "基金管理人正式公告原文，经第三方公告库转发，公告 ID 可回源",
            "B": "可信第三方转载或整理，但未逐条回源官方原文",
            "C": "第三方数据平台信息，尚未与合同或官方数据逐条核验",
            "D": "推断、代理或人工假设",
            "unknown": "无法确认",
        },
    }


# ---------------------------------------------------------------- 研究指标定义
def build_indicators() -> dict:
    return {
        "return_indicators": [
            {"key": "ret_1m", "name": "近 1 月收益", "window": "21 交易日",
             "requires": ["unit_nav 或 acc_nav"], "risk": "短期噪声大，禁止单独用于排序"},
            {"key": "ret_3m", "name": "近 3 月收益", "window": "63 交易日",
             "requires": ["unit_nav 或 acc_nav"], "risk": "同上"},
            {"key": "ret_6m", "name": "近 6 月收益", "window": "126 交易日",
             "requires": ["unit_nav 或 acc_nav"], "risk": "同上"},
            {"key": "ret_1y", "name": "近 1 年收益", "window": "252 交易日",
             "requires": ["unit_nav 或 acc_nav"], "risk": "单年受市场风格影响大"},
            {"key": "ret_3y", "name": "近 3 年收益", "window": "756 交易日",
             "requires": ["unit_nav 或 acc_nav"],
             "risk": "需至少 3 年数据；不足则 excluded 不插值"},
            {"key": "ret_since_inception", "name": "成立以来收益",
             "window": "成立日至最新",
             "requires": ["established_date", "unit_nav/acc_nav"],
             "risk": "41 个清盘本体无成立日期；不同基金区间不可直接比"},
            {"key": "annualized_return", "name": "年化收益",
             "window": "(1+累计收益)^(1/年数)-1",
             "requires": ["足够长区间"],
             "risk": "短区间年化会放大极端值，样本<1年禁止输出"},
            {"key": "rolling_return_dist", "name": "滚动收益分布",
             "window": "滚动 N 日（如 252 日）",
             "requires": ["连续净值序列"],
             "risk": "净值连续性 cannot_verify，滚动窗口可能跨越缺失期"},
        ],
        "risk_indicators": [
            {"key": "max_drawdown", "name": "最大回撤",
             "formula": "max(1 - NAV_t / max(NAV_0..t))",
             "requires": ["净值序列"], "risk": "依赖净值连续性；缺失期会低估回撤"},
            {"key": "annualized_vol", "name": "年化波动率",
             "formula": "std(日收益) × sqrt(252)",
             "requires": ["日收益序列"], "risk": "252 是假设值；基金实际公布频率不同"},
            {"key": "downside_vol", "name": "下行波动率",
             "formula": "std(min(日收益, 0)) × sqrt(252)",
             "requires": ["日收益序列"], "risk": "同上"},
            {"key": "sharpe", "name": "Sharpe",
             "formula": "(年化收益 - 无风险利率) / 年化波动率",
             "requires": ["年化收益", "年化波动率", "无风险利率"],
             "risk": "无风险利率来源未定；本项目暂无可靠无风险利率序列"},
            {"key": "sortino", "name": "Sortino",
             "formula": "(年化收益 - 无风险利率) / 下行波动率",
             "requires": ["同上 + 下行波动率"], "risk": "同上"},
            {"key": "calmar", "name": "Calmar",
             "formula": "年化收益 / 最大回撤",
             "requires": ["年化收益", "最大回撤"], "risk": "最大回撤为 0 时无定义"},
            {"key": "recovery_days", "name": "回撤修复时间",
             "formula": "从最低点回到前高所需交易日",
             "requires": ["净值序列"], "risk": "未修复则标记「至今未修复」，不填 0"},
        ],
        "stability_indicators": [
            {"key": "positive_ratio", "name": "滚动窗口正收益比例",
             "formula": "滚动 N 日中收益>0 的占比", "requires": ["净值序列"],
             "risk": "窗口长度选择影响结果，必须标注"},
            {"key": "phase_performance", "name": "不同市场阶段表现",
             "formula": "按预设市场阶段切分（牛/熊/震荡）",
             "requires": ["市场阶段划分依据"],
             "risk": "**阶段划分本身是人为选择**，必须有明确规则并披露"},
            {"key": "return_concentration", "name": "收益集中度",
             "formula": "Top-N 月份收益占总收益比例", "requires": ["月度收益"],
             "risk": "总收益为负时该指标无意义，需标注"},
            {"key": "extreme_month_contribution", "name": "极端月份贡献",
             "formula": "最大单月正/负收益", "requires": ["月度收益"],
             "risk": "单月数据可能受分红/拆分影响"},
            {"key": "benchmark_deviation", "name": "与基准偏离",
             "formula": "基金收益 - 基准收益",
             "requires": ["benchmark 字段", "基准收益序列"],
             "risk": "**基准收益序列本项目尚未采集**；benchmark 文本也需解析"},
        ],
        "active_equity_specific": [
            {"key": "excess_return", "name": "相对基准超额收益",
             "requires": ["可验证业绩基准 + 基准收益序列"], "status": "blocked",
             "blocker": "基准收益序列未采集，benchmark 为自由文本"},
            {"key": "manager_tenure_performance", "name": "经理任职区间表现",
             "requires": ["任职起止日期 + 净值"], "status": "partial",
             "blocker": "仅 12 条有日期，其余为快照"},
            {"key": "style_stability", "name": "风格稳定性",
             "requires": ["持仓数据（行业/个股权重）"], "status": "blocked",
             "blocker": "本项目未采集持仓数据"},
            {"key": "scale_change", "name": "规模变化",
             "requires": ["规模时间序列"], "status": "descriptive_only",
             "blocker": "日期是平台观测日期，不是验证报告期末"},
        ],
        "forbidden_treatments": [
            "把基金经理快照当历史时点特征",
            "把规模平台观测日期当报告期末或时点已知信息",
            "用不完整分红修正历史收益",
            "把当前费率倒填历史区间",
            "把支付宝 unknown 当作可买或不可买",
            "把 41 条清盘记录说成全量名录",
            "用单一短期收益排序选基",
        ],
    }


# ---------------------------------------------------------------- 比较规则与评分
def build_comparison_rules() -> dict:
    return {
        "same_class_only": True,
        "rules": [
            {"group": "指数基金", "rule": "宽基指数与行业主题指数**必须分开**",
             "reason": "波动率与收益分布差异极大，混排会得出错误结论"},
            {"group": "主动权益", "rule": "必须按可验证的业绩基准分组",
             "reason": "无基准则无法判断是能力还是风格暴露"},
            {"group": "债券基金", "rule": "按久期、信用风险、转债暴露分层",
             "reason": "这些字段当前**多数缺失**，缺失标 unknown 不猜"},
            {"group": "货币基金", "rule": "独立收益与风险口径",
             "reason": "每万份收益/7日年化与净值型不可比"},
            {"group": "A/C 份额", "rule": "先按 fund_id 归并比较策略表现，再单独比较份额成本",
             "reason": "同一组合、只有费率差"},
            {"group": "成立时间", "rule": "成立不足 N 年不得与完整周期基金直接比较",
             "reason": "样本长度不同，统计量不可比"},
        ],
        "unknown_handling": ("没有可靠分类字段时标记 `unknown`，"
                             "**不猜测、不按名称臆断**"),
        "field_availability_warning": {
            "fund_type_l1": "仅 12 个非清盘本体有值，41 个清盘本体全 NULL",
            "is_index_fund": "仅 5 个非清盘本体为 1，41 个清盘本体全 NULL",
            "benchmark": "9 个非清盘本体有文本，41 个清盘本体全 NULL",
            "established_date": "12 个非清盘本体有值，41 个清盘本体全 NULL",
            "consequence": ("清盘本体无法用库字段分类，只能依赖 3B-4.1.1 校准 JSON；"
                            "研究池若纳入清盘样本，必须显式声明分类来源"),
        },
    }


def build_scoring() -> dict:
    return {
        "status": "design_only",
        "generates_ranking": False,
        "generates_signals": False,
        "principles": [
            "不使用未来数据（所有指标只用截至 t 日已公布的数据）",
            "不用单一短期收益排序",
            "先做同类比较，跨类不排名",
            "风险指标必须参与，不能只看收益",
            "样本长度和数据质量必须参与评分",
            "历史收益高不等于推荐",
            "缺失数据降级或排除，不静默填补",
            "所有评分项可追溯到来源与计算过程",
        ],
        "dimensions": [
            {"key": "return", "name": "收益", "weight": 0.30,
             "components": ["ret_1y", "ret_3y", "annualized_return"],
             "rationale": "中长期收益为主，1 月/3 月只作参考不进主分"},
            {"key": "risk", "name": "风险", "weight": 0.30,
             "components": ["max_drawdown", "annualized_vol", "downside_vol"],
             "rationale": "风险与收益同权重，防止纯收益排序"},
            {"key": "risk_adjusted", "name": "风险调整收益", "weight": 0.20,
             "components": ["sharpe", "sortino", "calmar"],
             "rationale": "单位风险回报，需无风险利率（当前缺失→降级）"},
            {"key": "stability", "name": "稳定性", "weight": 0.15,
             "components": ["positive_ratio", "return_concentration"],
             "rationale": "防止靠单月暴涨刷高收益"},
            {"key": "data_quality", "name": "数据质量", "weight": 0.05,
             "components": ["样本长度", "缺失率", "证据等级"],
             "rationale": "数据差的基金即使指标好看也要降权"},
        ],
        "weight_rationale": ("收益与风险等权（各 30%）体现「不唯收益」；"
                             "风险调整收益 20% 是收益/风险的二次确认；"
                             "稳定性 15% 抑制极端值；"
                             "数据质量 5% 是门槛而非主导，避免数据好的基金被过度加分"),
        "missing_value_rules": [
            "关键指标缺失（如净值序列不足）→ 该基金**排除出排名**，不补零",
            "非关键指标缺失（如 Sharpe 缺无风险利率）→ 该维度降权并标注",
            "数据质量分低于阈值 → 整只基金标 C 档，仅供观察",
            "任何插值必须在输出中显式标注方法与影响",
        ],
        "applicable_when": [
            "同一产品类别内比较",
            "样本期长度相近",
            "数据完整性达到 B 档以上",
        ],
        "forbidden_when": [
            "跨产品类别排名（指数 vs 主动 vs 债券 vs 货币）",
            "样本期差异过大（1 年 vs 10 年）",
            "把规模/经理快照当因子",
            "把该评分当作买入建议",
        ],
    }


def build_pool_tiers() -> dict:
    return {
        "principle": ("同一基金的不同**数据字段**可以有不同等级，"
                      "**不得**给整只基金打一个笼统可信度标签"),
        "tiers": {
            "A": {
                "label": "可直接用于研究",
                "meaning": "数据来源明确、覆盖完整、口径已确认",
                "examples_now": [
                    "历史单位净值（单序列描述性分析）",
                    "已知清盘事件清单（用于剔除，不声称完整）",
                ],
            },
            "B": {
                "label": "有条件用于研究",
                "meaning": "数据可用但存在已知限制，使用必须带条件",
                "examples_now": [
                    "累计净值（需明确与单位净值不混用）",
                    "11 条有公告生效日的年化费率（仅生效日后）",
                    "有公告任职日期的 12 条经理记录（仅已知区间）",
                    "基金成立日期（仅用于过滤，不推断业绩）",
                ],
            },
            "C": {
                "label": "仅辅助观察",
                "meaning": "存在明显完整性或语义缺陷，不能支撑结论",
                "examples_now": [
                    "基金规模历史（平台观测日期，非验证报告期末）",
                    "分红记录（完整性未验证）",
                    "无生效日的 79 条费率",
                    "无任职日期的经理快照",
                ],
            },
            "D": {
                "label": "禁止用于相应研究用途",
                "meaning": "数据本身不可靠或语义不成立，任何正式使用都禁止",
                "examples_now": [
                    "支付宝可购买状态（unknown）",
                    "支付宝实际费率（无数据源）",
                    "规模记录作为历史时点因子/回测已知信息",
                    "把 41 条清盘记录当全量名录",
                    "净值连续性结论（cannot_verify）",
                ],
            },
        },
        "field_level_example": {
            "fund": "110022 易方达消费行业股票",
            "note": "同一基金不同字段等级不同",
            "fields": {
                "unit_nav": "A（单序列）",
                "acc_nav": "B（不混用）",
                "management_fee": "B（有 2023-07-10 生效日）",
                "custody_fee": "B（有 2023-07-10 生效日）",
                "sales_service_fee": "C（NULL，页面 ---）",
                "purchase_fee": "C（无生效日）",
                "redemption_fee": "C（无生效日、持有期口径未定）",
                "aum": "C（平台观测日期）",
                "manager": "B（王元春 2021-01-16~2025-04-12 有公告）",
                "alipay": "D（unknown）",
            },
        },
    }


def main() -> dict:
    with get_connection(DB) as conn:
        taxonomy = audit_taxonomy(conn)
        admission = build_admission(conn)
        pool = {
            "non_terminated_fund_count": conn.execute(
                "SELECT COUNT(*) FROM fund_master WHERE lifecycle_status='unknown'"
            ).fetchone()[0],
            "non_terminated_share_count": conn.execute(
                """SELECT COUNT(*) FROM fund_share_classes s
                   JOIN fund_master m ON m.fund_id=s.fund_id
                   WHERE m.lifecycle_status='unknown'""").fetchone()[0],
            "known_terminated_fund_count": conn.execute(
                """SELECT COUNT(*) FROM fund_master
                   WHERE lifecycle_status='terminated'""").fetchone()[0],
        }

    indicators = build_indicators()
    comparison = build_comparison_rules()
    scoring = build_scoring()
    tiers = build_pool_tiers()

    return {
        "phase": "3B-5.0",
        "baseline_head": "8b78b6fbcd292d5530e923c4678b0bc605f37e44",
        "generated_at": NOW.isoformat(timespec="seconds"),
        "scope": ("只做研究性分析框架设计与数据准入审计；"
                  "不写库、不采集、不计排名、不出信号、不开回测门禁。"),
        "product_taxonomy": taxonomy,
        "data_admission": admission,
        "indicators": indicators,
        "comparison_rules": comparison,
        "scoring": scoring,
        "pool_tiers": tiers,
        "pool_summary": pool,
        "gate": {
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "ready_for_research_analysis": True,
            "reason": ("研究性描述分析可用（净值序列、清盘剔除、"
                       "部分费率与经理区间）；"
                       "正式回测与真实排名仍不具备条件"),
            "blocked": [
                "3B-5 正式回测",
                "生成真实基金排名",
                "生成买入/卖出信号",
            ],
        },
    }


if __name__ == "__main__":
    p = main()
    out = ROOT / "reports" / "phase3B5_0_research_framework.json"
    out.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    adm = {
        "phase": "3B-5.0",
        "generated_at": p["generated_at"],
        "items": p["data_admission"]["items"],
        "field_semantics": p["data_admission"]["field_semantics"],
        "principles": p["data_admission"]["principles"],
        "evidence_levels": p["data_admission"]["evidence_levels"],
    }
    out2 = ROOT / "reports" / "phase3B5_0_data_admission_matrix.json"
    out2.write_text(json.dumps(adm, ensure_ascii=False, indent=1), encoding="utf-8")
    print("JSON ->", out)
    print("JSON ->", out2)
    print("分类:", p["product_taxonomy"]["current_sample"]["non_terminated_funds"], "本体")
    print("准入项:", p["data_admission"]["item_count"])
    print("指标组:", len(p["indicators"]["return_indicators"]),
          len(p["indicators"]["risk_indicators"]),
          len(p["indicators"]["stability_indicators"]))
    print("门禁:", p["gate"]["ready_for_backtest"], p["gate"]["ready_for_formal_ranking"])
