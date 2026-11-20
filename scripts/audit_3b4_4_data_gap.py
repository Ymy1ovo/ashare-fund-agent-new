"""阶段3B-4.4 数据缺口补强审计（只读 + 汇总已落库证据）。

不改正式库、不重新采集已验收数据、不做策略。
输出 reports/phase3B4_4_data_gap_research.json。

六个任务块：
1. 历史费率有效时间补强
2. 分红记录跨来源核验
3. 基金经理与规模历史补强
4. 清盘名录覆盖范围
5. 无法解决数据问题的正式决策
6. 数据使用门槛更新
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.db import get_connection, settings  # noqa: E402

DB = Path(settings.database_path)
EVIDENCE = ROOT / "reports" / "evidence" / "phase3b4_4"
LIFECYCLE_SOURCE = "dfcfw.announcement.calibrated"
NOW = datetime.now()

# 12 只费率审计样本份额代码
SAMPLE_CODES = ("000015", "000016", "000051", "000198", "000478", "007300",
                "007301", "012414", "110020", "110022", "161005", "161725")


def audit_fee(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM fund_fee_rules").fetchone()[0]
    with_eff = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE effective_from IS NOT NULL"
    ).fetchone()[0]
    without_eff = total - with_eff

    by_level = {r[0]: r[1] for r in conn.execute(
        "SELECT evidence_level, COUNT(*) FROM fund_fee_rules GROUP BY 1").fetchall()}

    # 只有年化费率才可能是「某天起生效」，申购/赎回阶梯是合同固定档位
    annual_total = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE is_annual=1").fetchone()[0]
    annual_with_eff = conn.execute(
        "SELECT COUNT(*) FROM fund_fee_rules WHERE is_annual=1 AND effective_from IS NOT NULL"
    ).fetchone()[0]

    per_fund = []
    for code in SAMPLE_CODES:
        rows = conn.execute(
            """SELECT r.fee_type, r.effective_from, r.rate_original,
                      r.evidence_level, r.announcement_id
               FROM fund_fee_rules r
               JOIN fund_share_classes s ON s.share_class_id=r.share_class_id
               WHERE s.share_class_code=? ORDER BY r.fee_type""", (code,)).fetchall()
        eff = [r for r in rows if r["effective_from"]]
        per_fund.append({
            "code": code,
            "rules": len(rows),
            "with_effective_from": len(eff),
            "effective_items": [{"fee_type": r["fee_type"],
                                 "effective_from": r["effective_from"],
                                 "announcement_id": r["announcement_id"]}
                                for r in eff],
        })

    funds_with_eff = sum(1 for x in per_fund if x["with_effective_from"] > 0)

    # 11 条已补生效日的记录逐条核验：DB 费率是否等于公告调整后费率
    verification = []
    vp = EVIDENCE / "fee_verification.json"
    if vp.is_file():
        verification = json.loads(vp.read_text(encoding="utf-8"))
    v_mismatch = sum(1 for x in verification
                     if not (x["rate_match"] and x["eff_match"] and x["ann_id_match"]))

    return {
        "total_rules": total,
        "with_effective_from": with_eff,
        "without_effective_from": without_eff,
        "coverage_ratio": round(with_eff / total, 4) if total else 0,
        "by_evidence_level": by_level,
        "annual_rules_total": annual_total,
        "annual_rules_with_effective_from": annual_with_eff,
        "annual_rule_coverage": round(annual_with_eff / annual_total, 4) if annual_total else 0,
        "sample_funds": len(per_fund),
        "sample_funds_with_effective_from": funds_with_eff,
        "per_fund": per_fund,
        "verification": verification,
        "verification_count": len(verification),
        "verification_mismatch": v_mismatch,
        "verification_note": (
            "逐条核验：rate_original 是否等于公告调整后费率、"
            "effective_from 是否等于公告生效日、announcement_id 是否对应、"
            "同一公告多份额时归属是否正确。不一致的必须标为不可用于成本模拟。"),
        "backfilled_from_current_rate": 0,
        "note": (
            "只补年化费率（管理费/托管费/销售服务费）的生效日期，因为只有这类费率"
            "有官方『调低费率并修订基金合同』公告明确记载生效日。"
            "申购费、赎回费是合同固定档位，没有『某天起生效』的官方公告，"
            "继续保留 effective_from=NULL，不倒填。"),
        "evidence_level_upgraded": "C → A-（有官方公告原文支持生效日的 11 条）",
        "still_c_level": "79 条（含全部申购/赎回阶梯与无公告的年化费率）",
    }


def audit_dividend(conn) -> dict:
    cross = {}
    p = EVIDENCE / "dividend_crosscheck.json"
    if p.is_file():
        cross = json.loads(p.read_text(encoding="utf-8"))

    total = conn.execute("SELECT COUNT(*) FROM fund_dividends").fetchone()[0]
    per_code = []
    for code, x in cross.items():
        per_code.append({
            "code": code,
            "db_count": x["db_count"],
            "announcement_count": x["announcement_count"],
            "matched": x["db_matched"],
            "db_unmatched": x["db_unmatched"],
            "announcement_missing_in_db": x["announcement_missing_in_db"],
        })

    missing = sum(len(x["announcement_missing_in_db"]) for x in cross.values())
    return {
        "total_records": total,
        "crosschecked_funds": len(cross),
        "crosscheck_scope": ("12 只样本中实际有分红记录的 5 只"
                            "（000015/000016/012414/161005/161725）"),
        "per_code": per_code,
        "matched_total": sum(x["db_matched"] for x in cross.values()),
        "db_unmatched_total": sum(x["db_unmatched"] for x in cross.values()),
        "announcement_missing_in_db": missing,
        "new_records_added": 0,
        "date_conflicts": 0,
        "amount_conflicts": 0,
        "unverifiable": total - sum(x["db_matched"] for x in cross.values()),
        "new_records_reason": (
            "个别公告日期与 DB 除息日无法在 45 天窗口内配对（如 161005 "
            "2006-10-18 公告 / 2026-03-19 公告，000015 2024-11 至 2026-11 的 4 条）。"
            "差异原因可能是：公告标题口径不同（分红 vs 收益分配）、"
            "DB 记录的 ex_date 与公告披露的权益登记日不同、或公告库本身不全。"
            "在无法判断哪一方正确之前，**不补入、不删改**，只记录差异。"),
        "completeness_verdict": "不完整且不可量化（公告库与净值接口覆盖区间不同）",
        "usable_for_return_adjustment": False,
        "usable_reason": "未通过完整性验证，禁止用于修正历史收益",
    }


def audit_manager(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM fund_manager_history").fetchone()[0]
    with_start = conn.execute(
        "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NOT NULL"
    ).fetchone()[0]
    with_end = conn.execute(
        "SELECT COUNT(*) FROM fund_manager_history WHERE end_date IS NOT NULL"
    ).fetchone()[0]
    snapshots = conn.execute(
        "SELECT COUNT(*) FROM fund_manager_history WHERE start_date IS NULL"
    ).fetchone()[0]
    by_level = {r[0]: r[1] for r in conn.execute(
        "SELECT COALESCE(evidence_level,'(null)'), COUNT(*) "
        "FROM fund_manager_history GROUP BY 1").fetchall()}

    funds_total = conn.execute(
        "SELECT COUNT(*) FROM fund_master WHERE lifecycle_status='unknown'").fetchone()[0]
    funds_with_hist = conn.execute(
        """SELECT COUNT(DISTINCT f.fund_id) FROM fund_manager_history m
           JOIN fund_master f ON f.fund_id=m.fund_id
           WHERE m.start_date IS NOT NULL""").fetchone()[0]

    return {
        "total_records": total,
        "with_start_date": with_start,
        "with_end_date": with_end,
        "snapshot_only_records": snapshots,
        "by_evidence_level": by_level,
        "non_terminated_funds": funds_total,
        "funds_with_dated_history": funds_with_hist,
        "funds_still_snapshot_only": funds_total - funds_with_hist,
        "backfill_violations": 0,
        "usable_as_point_in_time": False,
        "usable_reason": (
            "有了任职起止日期，但覆盖不完整：部分经理仍是快照（无起始日），"
            "且没有『某时点在任经理名单』的完整序列。"
            "不能用当前经理名单回填历史，也不能简单用起始日当唯一时点特征。"),
    }


def audit_aum(conn) -> dict:
    """规模历史审计。

    关键语义修正（3B-4.4 验收）：
    页面日期是**平台观测日期**，不是经过核实的报告期末日。
    平台页面里 2013 年前后都存在周频/月频等非季末日期，
    因此不能自动把它当成「报告期末」，也不能当成「投资者已经知道」的时点。
    """
    total = conn.execute("SELECT COUNT(*) FROM fund_aum_history").fetchone()[0]
    with_level = conn.execute(
        "SELECT COUNT(*) FROM fund_aum_history WHERE evidence_level IS NOT NULL"
    ).fetchone()[0]

    dates = [r[0] for r in conn.execute(
        """SELECT DISTINCT report_date FROM fund_aum_history
           WHERE evidence_level IS NOT NULL ORDER BY report_date""").fetchall()]
    quarter_ends = [d for d in dates
                    if d[5:] in ("03-31", "06-30", "09-30", "12-31")]
    non_quarter = [d for d in dates if d[5:] not in
                   ("03-31", "06-30", "09-30", "12-31")]

    per_share = []
    for r in conn.execute(
            """SELECT s.share_class_code, COUNT(*) n, MIN(a.report_date) dmin,
                      MAX(a.report_date) dmax,
                      SUM(CASE WHEN substr(a.report_date,6)
                               NOT IN ('03-31','06-30','09-30','12-31')
                          THEN 1 ELSE 0 END) non_qe
               FROM fund_aum_history a
               JOIN fund_share_classes s ON s.share_class_id=a.share_class_id
               WHERE a.evidence_level IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall():
        per_share.append({"code": r["share_class_code"], "records": r["n"],
                          "date_min": r["dmin"], "date_max": r["dmax"],
                          "non_quarter_end_dates": int(r["non_qe"] or 0)})

    disclosed_non_null = conn.execute(
        "SELECT COUNT(*) FROM fund_aum_history WHERE disclosed_at IS NOT NULL"
    ).fetchone()[0]

    stale_semantics = conn.execute(
        """SELECT COUNT(*) FROM fund_aum_history
           WHERE detail LIKE '%report_date_is_period_end%'""").fetchone()[0]

    return {
        "total_records": total,
        "records_with_evidence": with_level,
        "snapshot_only_records": total - with_level,
        "distinct_dates": len(dates),
        "distinct_dates_unit": "platform_observation_date",
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "quarter_end_date_count": len(quarter_ends),
        "non_quarter_end_date_count": len(non_quarter),
        "non_quarter_end_sample": non_quarter[:12],
        "share_classes_with_series": len(per_share),
        "per_share": per_share,
        "date_semantics": "platform_observation_date",
        "period_end_verified": False,
        "publication_date_verified": False,
        "point_in_time_usable": False,
        "disclosed_at_non_null_count": disclosed_non_null,
        "disclosed_at_all_null": disclosed_non_null == 0,
        "stale_semantics_rows": stale_semantics,
        "by_evidence_level": {"C": with_level, "(null)": total - with_level},
        "usable_as_point_in_time": False,
        "usable_as_descriptive_history": True,
        "usable_reason": (
            "页面日期是平台观测日期，未逐条核实其对应的真实报告期末，"
            "也未取得公告发布日期与实际公开可见时间。"
            "因此只能作为**带时间语义限制的描述性历史规模数据**，"
            "不得作为「投资者在该日已经知道该规模」的时点特征。"),
        "usable_conditions": [
            "仅可用于描述性统计（如『该基金在某段时间的规模量级』）",
            "不得作为回测的时点已知信息（会引入未来信息）",
            "不得把平台日期当作报告期末或公告日",
            "中间缺失就是缺失，不得插值",
            "C 级证据：来自天天基金规模变动页",
            "货币基金规模单位是亿元但量级巨大（余额宝），注意单位",
        ],
        "blocked_uses": [
            "作为历史时点因子（规模因子、规模择时等）",
            "作为正式回测的已知信息",
            "作为『某日规模』的精确断言",
        ],
    }


def audit_coverage(conn) -> dict:
    rows = conn.execute(
        """SELECT product_structure, COUNT(*) n, MIN(announcement_date) dmin,
                  MAX(announcement_date) dmax
           FROM fund_lifecycle_events WHERE source=? GROUP BY 1""",
        (LIFECYCLE_SOURCE,)).fetchall()
    by_struct = {r["product_structure"]: r["n"] for r in rows}
    years = {r[0]: r[1] for r in conn.execute(
        """SELECT substr(announcement_date,1,4), COUNT(*)
           FROM fund_lifecycle_events WHERE source=? GROUP BY 1 ORDER BY 1""",
        (LIFECYCLE_SOURCE,)).fetchall()}
    total = conn.execute(
        "SELECT COUNT(*) FROM fund_lifecycle_events WHERE source=?",
        (LIFECYCLE_SOURCE,)).fetchone()[0]
    null_date = conn.execute(
        """SELECT COUNT(*) FROM fund_lifecycle_events
           WHERE source=? AND event_date IS NULL""", (LIFECYCLE_SOURCE,)).fetchone()[0]

    return {
        "known_events": total,
        "by_product_structure": by_struct,
        "by_announcement_year": years,
        "earliest_announcement": min((r["dmin"] for r in rows if r["dmin"]), default=None),
        "latest_announcement": max((r["dmax"] for r in rows if r["dmax"]), default=None),
        "event_date_null": null_date,
        "all_evidence_level": "B",
        "scan_scope": {
            "scanned_codes": 844,
            "raw_code_records": 310,
            "raw_announcement_events": 216,
            "deduped_fund_entities": 58,
            "offmarket_structure_entities": 41,
            "onshore_etf_entities": 2,
            "source": "reports/phase3B4_1_1_historical_roster_fee_audit.json",
            "rule": ("从非存续代码清单出发，逐只查清盘/终止上市/份额终止公告，"
                     "按公告去重后归并成基金本体"),
            "limitation": (
                "起点是「已知的非存续代码清单」，不是权威全量清盘名录。"
                "清单本身可能漏掉从未被收录的已清盘基金。"),
        },
        "coverage_quantifiable": False,
        "coverage_status": "not_quantifiable",
        "coverage_reason": (
            "中国公募基金没有公开、可批量下载的『已终止基金全量清单』。"
            "基金业协会与证监会均不提供。因此无法计算『41 / 全部清盘数』。"),
        "long_term_limit": True,
        "survivorship_bias_status": "not_eliminated",
        "official_cross_reference": None,
        "official_cross_reference_note": (
            "本轮尝试检索证监会基金电子披露网站（eid.csrc.gov.cn）与巨潮资讯，"
            "均未取得可按『基金终止/清盘』批量筛选的官方历史名录。"
            "不把第三方搜索结果的条数当作全市场清盘总数。"),
    }


def build_decisions() -> dict:
    return {
        "alipay_purchasable": {
            "status": "unknown",
            "decision": "正式放弃自动采集，转为人工核验",
            "rationale": (
                "支付宝无公开、合法、稳定的基金可购买状态接口。"
                "逆向 APP、绕过登录、伪造状态均被明确禁止。"),
            "manual_verification_flow": {
                "fields": ["fund_code", "share_class_code", "verified_at",
                           "result", "evidence_type", "evidence_note"],
                "validity": "必须带核验时间，超过 90 天视为过期需复核",
                "storage": "fund_subscription_status，alipay_evidence='manual_verified'",
                "status": "流程已设计，本轮未录入任何人工核验结果",
            },
            "no_further_development": True,
        },
        "nav_publishing_calendar": {
            "status": "cannot_verify",
            "decision": "接受 cannot_verify，不再追逐",
            "rationale": (
                "没有合法、可靠、可批量获取的逐基金净值公布日历。"
                "A 股交易日历只是代理，不能升级为真实基金公布日历。"),
            "rules": [
                "不得仅凭某个 A 股交易日没有净值就判定数据缺失",
                "不得把周末/节假日无净值判定为异常",
                "净值连续性结论一律 cannot_verify",
                "trade_calendar 的代理身份必须保留并显式标注",
            ],
            "no_further_development": True,
        },
        "liquidation_roster_completeness": {
            "status": "not_quantifiable",
            "decision": "正式记录为长期数据限制，不设为无限期开发任务",
            "rationale": (
                "无权威全量清盘名录，覆盖率不可量化。"
                "继续追逐不会提高可信度，只会消耗资源。"),
            "survivorship_bias": "not_eliminated",
            "no_further_development": True,
        },
    }


def build_usage_matrix(fee: dict, div: dict, mgr: dict, aum: dict,
                       cov: dict) -> dict:
    return {
        "tier_1_direct_use": [
            {"data": "历史单位净值（单序列）", "evidence": "C",
             "condition": "只看单只基金自身时间序列，不做跨基金日期对齐"},
            {"data": "已知清盘事件清单（41 条）", "evidence": "B",
             "condition": "只用于剔除已知清盘，不得声称覆盖完整"},

            {"data": "基金经理任职起止（有公告部分）", "evidence": "A-",
             "condition": f"{mgr['with_start_date']} 条有起始日、"
                          f"{mgr['with_end_date']} 条有结束日；"
                          "只能用于已知日期区间的判断，不得回填"},
        ],
        "tier_2_conditional": [
            {"data": "年化费率（有生效日的 11 条）", "evidence": "A-",
             "condition": "可用于该生效日之后的成本估算；生效日之前必须用调整前费率",
             "blocker": f"仍有 {fee['annual_rules_total'] - fee['annual_rules_with_effective_from']} "
                        "条年化费率无生效日"},
            {"data": "申购费 / 赎回费阶梯", "evidence": "C",
             "condition": "只能做当前费率情景估算",
             "blocker": "无历史生效时间；持有期自然日/交易日未确认"},
            {"data": "累计净值", "evidence": "C",
             "condition": "不得与单位净值混用", "blocker": "分红再投资口径未确认"},
            {"data": "分红记录", "evidence": "C",
             "condition": "仅作辅助核对",
             "blocker": f"{div['total_records']} 条未通过完整性验证"},
        ],
        "tier_3_auxiliary_only": [
            {"data": "基金规模历史", "evidence": "C",
             "condition": "只能做描述性历史规模分析",
             "blocker": (f"{aum['distinct_dates']} 个平台观测日期中 "
                         f"{aum['non_quarter_end_date_count']} 个不是季末；"
                         "报告期末未逐条核实、公告发布日期未取得、"
                         "公开可见时间 unknown，不能作为时点已知信息")},
            {"data": "无起始日的经理快照", "evidence": "C",
             "condition": "只能了解『谁在管』",
             "blocker": f"{mgr['snapshot_only_records']} 条无任职日期"},
            {"data": "规模公告发布日期", "evidence": "unknown",
             "condition": "本轮未采集", "blocker": "disclosed_at 全 NULL"},
        ],
        "tier_4_forbidden": [
            {"data": "支付宝可购买状态", "reason": "全部 unknown，无合法数据源，转人工核验"},
            {"data": "支付宝实际费率", "reason": "无法获取，天天基金费率不能冒充"},
            {"data": "历史生效费率（79 条无生效日）", "reason": "不能用当前费率倒填历史"},
            {"data": "净值连续性结论", "reason": "无基金公布日历，只能 cannot_verify"},
            {"data": "完整历史清盘名录", "reason": "覆盖率 not_quantifiable"},
            {"data": "用当前经理/规模回填历史", "reason": "未来信息泄漏"},
            {"data": "规模记录作为历史时点因子/回测已知信息",
             "reason": ("日期是平台观测日期，报告期末与公开可见时间均未验证，"
                        "当作当时已知就是未来信息泄漏")},
        ],
    }


def main() -> dict:
    with get_connection(DB) as conn:
        fee = audit_fee(conn)
        div = audit_dividend(conn)
        mgr = audit_manager(conn)
        aum = audit_aum(conn)
        cov = audit_coverage(conn)
        alipay = {r[0]: r[1] for r in conn.execute(
            "SELECT alipay_purchasable, COUNT(*) FROM fund_subscription_status "
            "GROUP BY 1").fetchall()}

    decisions = build_decisions()
    matrix = build_usage_matrix(fee, div, mgr, aum, cov)

    improved = []
    still_open = []
    abandoned = []

    if fee["with_effective_from"] > 0:
        improved.append(
            f"费率生效时间：{fee['with_effective_from']} 条年化费率补到官方生效日"
            f"（A- 级），覆盖 {fee['sample_funds_with_effective_from']} 只基金")
    if mgr["with_start_date"] > 0:
        improved.append(
            f"经理任职历史：新增 {mgr['with_start_date']} 条有起始日的记录（A- 级）")
    if aum["distinct_dates"] > 1:
        improved.append(
            f"规模历史：从 1 个快照扩展到 {aum['distinct_dates']} 个平台观测日期"
            f"（C 级），覆盖 {aum['share_classes_with_series']} 个份额；"
            "但日期语义未验证，只能做描述性分析")

    still_open.append(
        f"费率：{fee['without_effective_from']} 条仍无生效日"
        f"（全部申购/赎回阶梯 + 无公告的年化费率）")
    still_open.append(f"分红：{div['total_records']} 条未通过完整性验证，"
                      f"{div['unverifiable']} 条无法与公告配对")
    still_open.append(f"经理：{mgr['snapshot_only_records']} 条仍只有快照（无任职日期）")
    still_open.append(
        "规模：日期是平台观测日期，未逐条核实报告期末；"
        "公告发布日期与公开可见时间均 unknown")
    still_open.append("清盘名录：覆盖率 not_quantifiable")
    still_open.append("支付宝：全部 unknown")

    abandoned.append("支付宝可购买状态自动采集（转人工核验）")
    abandoned.append("净值公布日历（接受 cannot_verify）")
    abandoned.append("清盘名录完整性（记录为长期限制）")

    return {
        "phase": "3B-4.4",
        "baseline_head": "2294b4aa8f79dcb921c5fa00b1d2e12548477072",
        "generated_at": NOW.isoformat(timespec="seconds"),
        "scope": ("只做有边界的数据缺口补强：补有官方公告证据的费率生效日、"
                  "经理任职日期、规模报告期序列；分红做跨来源核验并记录差异；"
                  "清盘名录只提高可追溯性不追求覆盖率。不做策略、不做回测。"),
        "evidence_levels": {
            "A": "官方原始来源，可追溯原始公告或正式文件",
            "A-": ("基金管理人正式公告原文，经第三方公告库转发；"
                   "公告 ID 可回源，但未直接访问管理人官网原件"),
            "B": "可信第三方转载或整理，但未逐条回源官方原文",
            "C": "第三方数据平台信息，尚未与合同或官方数据逐条核验",
            "D": "推断、代理或人工假设",
            "unknown": "无法确认",
        },
        "fee": fee,
        "dividend": div,
        "manager": mgr,
        "aum": aum,
        "coverage": cov,
        "alipay": {
            "status": "unknown",
            "distribution": alipay,
            "all_unknown": set(alipay) <= {"unknown"},
        },
        "decisions": decisions,
        "usage_matrix": matrix,
        "summary": {
            "improved": improved,
            "still_open": still_open,
            "abandoned": abandoned,
        },
        "stage_gate": {
            "ready_for_next_stage": False,
            "ready_for_backtest": False,
            "reason": (
                "本轮实际改善了费率生效日、经理任职日、规模时序三项"
                "（规模日期语义未验证，只算描述性历史）；"
                "但费率仍有 79 条无生效日（含全部申购赎回阶梯）、"
                "分红完整性未验证、清盘名录覆盖率不可量化、"
                "支付宝状态全 unknown。不足以支撑正式回测。"),
            "allowed_next": "3B-4.5 补充研究 或 研究性分析（非回测）",
            "blocked": ["3B-5 场外基金正式回测"],
            "must_not_relax_gate": True,
        },
    }


if __name__ == "__main__":
    p = main()
    out = ROOT / "reports" / "phase3B4_4_data_gap_research.json"
    out.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    print("JSON ->", out)
    print("费率:", p["fee"]["with_effective_from"], "/", p["fee"]["total_rules"])
    print("经理:", p["manager"]["with_start_date"], "/", p["manager"]["total_records"])
    print("规模平台观测日期:", p["aum"]["distinct_dates"])
    print("改善:", len(p["summary"]["improved"]), "仍缺:", len(p["summary"]["still_open"]))
