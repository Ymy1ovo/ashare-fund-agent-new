"""阶段3B-5.5 实用研究报告组装层（只读，不排名、不推荐、不出信号）。

把 3B-5.1 引擎的原始指标 + 3B-5.5 的质量分级，组装成
**能直接看懂「这份报告的证据有多强」** 的研究报告。

设计前提
--------
1. 结论永远分成三类，绝不混写：
   - 数据支持的事实（fact）
   - 有条件的描述性判断（conditional）
   - 目前无法证明的事项（cannot_prove）
2. 任何指标算不出来就如实标 D / not_available，不填数。
3. 不因为收益低就降低质量等级，不因为收益高就提高质量等级。
4. 不生成买入/卖出/推荐，不预测未来收益。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.fund.research.data_access import load_universe
from app.fund.research.engine import analyze_by_code
from app.fund.research.quality import (
    LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D, LEVEL_NA, LEVEL_MEANING,
    build_indicator_grades, grade_fund, grade_peer_comparison,
    grade_share_cost, worst_level,
)

GATE = {
    "ready_for_research_analysis": True,
    "ready_for_backtest": False,
    "ready_for_formal_ranking": False,
    "reason": "质量分级可用；正式回测与真实排名仍不具备条件",
}

# 结论三条硬边界（每份报告都带）
CONCLUSION_BOUNDARY = {
    "is_forecast": False,
    "is_investment_advice": False,
    "can_be_used_as": "描述性历史观察",
    "cannot_be_used_as": [
        "未来收益预测",
        "买入或卖出建议",
        "跨类别正式排名依据",
        "单一年度收益推导长期结论",
    ],
}


def _peer_context(peer_key: str | None, universe: list[dict] | None = None) -> dict:
    """统计同类组的**本体数**（A/C 按 fund_id 去重）。"""
    u = universe if universe is not None else load_universe()
    members = [e for e in u
               if (e.get("peer_group") or {}).get("peer_key") == peer_key]
    fund_ids = sorted({e["fund_id"] for e in members})
    head = members[0]["peer_group"] if members else {}
    return {
        "peer_key": peer_key,
        "member_count": len(fund_ids),
        "fund_ids": fund_ids,
        "grouping_source": head.get("grouping_source"),
        "benchmark_confidence": head.get("benchmark_confidence"),
        "verifiable_group": head.get("verifiable_group"),
        "index_scope": head.get("index_scope"),
        "benchmark_family": head.get("benchmark_family"),
        "deduped_by_fund_id": True,
    }


def _money_section(report: dict) -> dict:
    """货币基金专属描述段。口径与净值型完全隔离。"""
    ind = report.get("indicators") or {}
    st = ind.get("stats") or {}
    p10 = st.get("per_10k_yield") or {}
    s7 = st.get("seven_day_annual") or {}
    return {
        "caliber": "money_market",
        "uses_unit_nav": False,
        "uses_acc_nav": False,
        "comparable_with_net_value_funds": False,
        "per_10k_yield": {
            "status": p10.get("status"),
            "sample_days": p10.get("sample_days"),
            "cumulative_per_10k": p10.get("cumulative_per_10k"),
            "cumulative_as_return_pct": p10.get("cumulative_as_return_pct"),
            "unit": "元/万份/日",
            "definition": p10.get("definition"),
            "warning": "每万份收益是金额累加，不是收益率、不是净值",
        },
        "seven_day_annual": {
            "status": s7.get("status"),
            "latest": s7.get("latest"),
            "latest_date": s7.get("latest_date"),
            "mean": s7.get("mean"),
            "min": s7.get("min"),
            "max": s7.get("max"),
            "unit": "%",
            "warning": "7 日年化是滚动换算的参考值，不是已实现收益",
        },
        "nav_based_indicators": ind.get("nav_based_indicators"),
    }


def _annualized_with_interval(ind: dict, report: dict) -> dict:
    """给年化收益补上**真实计算区间**。

    ``indicators._annualized()`` 只返回 span_days/years/method，
    不带 start_date/end_date。这里用质量报告里的真实净值起止日期补充。

    依据：``_annualized()`` 取的是 ``series.points[0].nav_date`` 与
    ``series.points[-1].nav_date``，而 ``QualityReport.date_min/date_max``
    正是这两个值（data_access 里 q.date_min = points[0].nav_date）。

    不构造任何日期：拿不到就是 None，并标记来源。
    """
    node = dict(ind.get("annualized_return") or {})
    if not node:
        return node

    q = report.get("quality") or {}
    start = node.get("start_date") or q.get("date_min")
    end = node.get("end_date") or q.get("date_max")
    node["start_date"] = start
    node["end_date"] = end
    node["interval_source"] = (
        "node" if (node.get("start_date") and node.get("end_date")
                   and node.get("start_date") != q.get("date_min"))
        else ("quality_report" if (start and end) else "none"))
    node["interval_note"] = (
        "计算区间取自净值序列首尾，与质量报告 date_min/date_max 一致；"
        "未构造日期"
        if (start and end) else
        "缺少可验证的计算起止日期，不构造日期")
    return node


def _conclusions(report: dict, fund_grade: dict, grades: dict,
                 peer_ctx: dict) -> dict:
    """生成三类结论。严禁把推断写成事实。"""
    ind = report.get("indicators") or {}
    is_money = bool(report.get("is_money_fund"))
    q = report.get("quality") or {}
    ig = grades["indicators"]

    facts: list[str] = []
    conditional: list[str] = []
    cannot: list[str] = []

    # ---- 事实（全部可直接从库中读出）----
    facts.append(f"数据覆盖 {q.get('date_min')} ~ {q.get('date_max')}，"
                 f"共 {q.get('rows')} 条记录")
    facts.append(f"净值连续性为 {q.get('continuity_verification', 'cannot_verify')}"
                 "（无真实基金公布日历，无法验证每个交易日是否都该有净值）")
    if not is_money:
        rf = ind.get("return_field")
        facts.append(f"主要收益口径为 {rf}（累计净值，含分红再投资代理）")
        facts.append(f"分红修复未使用（dividend_repair_used="
                     f"{ind.get('dividend_repair_used')}）")
    else:
        facts.append("该基金为货币基金，不使用净值口径，只披露每万份收益与 7 日年化")

    # ---- 有条件判断（必须点名限制）----
    if not is_money:
        rets = ind.get("returns") or {}
        for key, label in (("ret_12m", "近1年"), ("ret_36m", "近3年")):
            cell = ig.get(key) or {}
            if cell.get("status") == "ok":
                conditional.append(
                    f"{label}收益 {cell['value']:.4%}：窗口端点精确命中、"
                    f"窗口内无超阈值缺口，可作**描述性**事实；"
                    f"但不能据此推断未来")
            else:
                cannot.append(f"{label}收益不可计算：{cell.get('reason')}")
        mdd = ig.get("max_drawdown") or {}
        if mdd.get("status") == "degraded":
            conditional.append(
                f"最大回撤 {mdd['value']:.4%} 只能覆盖可观测连续段，"
                f"**可能低估**，不得当作全区间完整回撤")
        elif mdd.get("status") == "ok":
            conditional.append(
                f"最大回撤 {mdd['value']:.4%} 覆盖全区间，"
                f"但净值连续性仍未验证")
        else:
            cannot.append(f"最大回撤不可计算：{mdd.get('reason')}")
    else:
        ms = _money_section(report)
        if ms["seven_day_annual"]["status"] == "ok":
            conditional.append(
                f"7 日年化最新 {ms['seven_day_annual']['latest']}%，"
                f"区间 {ms['seven_day_annual']['min']}% ~ "
                f"{ms['seven_day_annual']['max']}%，属参考值不是已实现收益")
        if ms["per_10k_yield"]["status"] == "ok":
            conditional.append(
                f"累计万份收益 {ms['per_10k_yield']['cumulative_per_10k']} 元/万份，"
                f"是金额累加，不是收益率")

    # ---- 无法证明 ----
    cannot.extend([
        "未来收益：本项目不做任何收益预测",
        "支付宝可购买状态：无公开合法数据源，恒 unknown",
        "支付宝实际费率：不可验证，不用天天基金费率冒充",
        "真实净值公布日历：不可得，连续性恒 cannot_verify",
    ])
    if (ig.get("sharpe") or {}).get("status") != "ok":
        cannot.append("Sharpe / Sortino：无可靠无风险利率，拒绝计算（不把 0 当利率）")
    if (ig.get("excess_return") or {}).get("status") != "computable":
        cannot.append("超额收益 / 信息比率 / Beta：库内无基准收益序列")
    peer_cell = ig.get("peer_comparison") or {}
    if peer_cell.get("status") == "insufficient_peer_sample":
        cannot.append(f"同类比较：{peer_cell.get('reason')}（拒绝强行构造同类排名）")
    elif peer_cell.get("status") == "no_verifiable_group":
        cannot.append(f"同类比较：{peer_cell.get('reason')}")
    cost_cell = ig.get("share_cost_comparison") or {}
    if cost_cell.get("status") == "insufficient_fee_evidence":
        cannot.append("A/C 成本优劣结论：费率字段不完整，标 insufficient_fee_evidence")
    elif cost_cell.get("status") == "partial_evidence":
        cannot.append("A/C 成本优劣结论：即使字段齐全，持有期口径与支付宝费率仍不可验证")

    return {
        "facts_supported_by_data": facts,
        "conditional_descriptive_judgements": conditional,
        "cannot_prove_yet": cannot,
        "fund_quality_level": fund_grade["overall_level"],
        "fund_quality_meaning": fund_grade["level_meaning"],
        "peer_group": peer_ctx.get("peer_key"),
        "peer_member_count": peer_ctx.get("member_count"),
        "boundary": CONCLUSION_BOUNDARY,
    }


def build_practical_report(code: str, db_path: Path | None = None, *,
                           universe: list[dict] | None = None) -> dict:
    """生成一份完整的实用研究报告（12 节）。"""
    base = analyze_by_code(code, db_path)
    if base.get("status") != "found":
        return {
            "phase": "3B-5.5",
            "query": code,
            "status": base.get("status"),
            "reason": base.get("reason"),
            "report": None,
            "gate": GATE,
        }

    report = base["reports"][0]
    merged = base.get("merged") or {}
    entry = base.get("fund_entity") or {}

    # fund_entity 不带成立日/基准/跟踪指数，从研究池补全（同一份额行）
    u = universe if universe is not None else load_universe(db_path)
    share_row = next((e for e in u
                      if e.get("share_code") == report.get("share_code")), None) or {}
    basic = dict(entry)
    for k in ("established_date", "benchmark", "tracking_index",
              "fund_company", "fund_name", "fund_code"):
        if basic.get(k) is None and share_row.get(k) is not None:
            basic[k] = share_row[k]

    peer_ctx = _peer_context((merged.get("peer_group") or {}).get("peer_key"),
                            u)
    cost = merged.get("cost_comparison")

    fund_grade = grade_fund(report.get("quality"),
                            is_money=bool(report.get("is_money_fund")),
                            source=report.get("data_source"))
    grades = build_indicator_grades(report, peer_ctx=peer_ctx, cost=cost)
    conclusions = _conclusions(report, fund_grade, grades, peer_ctx)

    ind = report.get("indicators") or {}
    up = report.get("indicators_unit_nav") or {}

    # 指标级最差等级：用来提示「整份报告的证据强度受哪个指标拖累」
    real_levels = [v["quality_level"] for v in grades["indicators"].values()
                   if v["quality_level"] in (LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D)]
    weakest = worst_level(*real_levels) if real_levels else LEVEL_NA

    doc = {
        "phase": "3B-5.5",
        "query": code,
        "status": "found",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        # 1 基金基本信息
        "1_basic_info": {
            "fund_id": basic.get("fund_id"),
            "fund_code": basic.get("fund_code"),
            "fund_name": basic.get("fund_name"),
            "share_code": report.get("share_code"),
            "share_name": report.get("share_name"),
            "fund_company": basic.get("fund_company"),
            "established_date": basic.get("established_date"),
            "benchmark": basic.get("benchmark"),
            "tracking_index": basic.get("tracking_index"),
            "lifecycle_status": basic.get("lifecycle_status"),
            "share_count": len(base.get("reports") or []),
        },
        # 2 产品分类
        "2_product_classification": {
            "product_class": report.get("product_class"),
            "investment_subtype": report.get("investment_subtype"),
            "basis": report.get("classification_basis"),
            "confidence": report.get("classification_confidence"),
            "is_money_fund": bool(report.get("is_money_fund")),
            "peer_group": merged.get("peer_group"),
        },
        # 3 数据来源与时间范围
        "3_data_source": {
            "source": report.get("data_source"),
            "date_min": (report.get("quality") or {}).get("date_min"),
            "date_max": (report.get("quality") or {}).get("date_max"),
            "rows": (report.get("quality") or {}).get("rows"),
            "nav_kind": (report.get("quality") or {}).get("nav_kind"),
            "return_field": ind.get("return_field"),
            "unit_nav_reference": {
                "note": up.get("note"),
                "available": bool(up),
            },
        },
        # 4 数据质量总等级
        "4_data_quality_level": fund_grade,
        # 5 各项指标及各自质量等级
        "5_indicator_grades": grades,
        "5_indicator_grades_summary": {
            "weakest_indicator_level": weakest,
            "weakest_level_meaning": LEVEL_MEANING.get(weakest, weakest),
            "level_counts": grades["level_counts"],
        },
        # 6 数据缺口与异常
        "6_gaps_and_anomalies": {
            "max_gap_days": (report.get("quality") or {}).get("max_gap_days"),
            "max_gap_at": (report.get("quality") or {}).get("max_gap_at"),
            "gap_count_over_threshold":
                (report.get("quality") or {}).get("gap_count_over_threshold"),
            "gaps_sample": (report.get("quality") or {}).get("gaps_sample"),
            "null_unit_nav": (report.get("quality") or {}).get("null_unit_nav"),
            "null_acc_nav": (report.get("quality") or {}).get("null_acc_nav"),
            "duplicate_dates": (report.get("quality") or {}).get("duplicate_dates"),
            "nonpositive_unit_nav":
                (report.get("quality") or {}).get("nonpositive_unit_nav"),
            "quality_flags": (report.get("quality") or {}).get("quality_flags"),
            "continuity_verification":
                (report.get("quality") or {}).get("continuity_verification"),
            "note": "缺口与空值不填 0、不跨越、不插值",
        },
        # 7 收益风险描述
        "7_return_risk": (
            _money_section(report) if report.get("is_money_fund") else {
                "caliber": "acc_nav",
                "returns": ind.get("returns"),
                "annualized_return": _annualized_with_interval(ind, report),
                "risk": ind.get("risk"),
                "risk_adjusted": ind.get("risk_adjusted"),
                "stability": ind.get("stability"),
                "unit_nav_reference_returns": (up.get("returns") or {}),
                "unit_nav_note": "unit_nav 不含分红，仅供对照，不是总回报",
            }),
        # 8 同类可比性
        "8_peer_comparability": {
            "peer_group": peer_ctx,
            "grade": grades["indicators"]["peer_comparison"],
            "cross_group_comparison_allowed": False,
            "ranking_generated": False,
            "rules": [
                "分组依据必须是可验证的跟踪指数或基准，不由名称相似判定",
                "A/C/E 按 fund_id 去重，只算一个本体",
                "货币基金独立分组，不与净值型同榜",
                "样本不足输出 insufficient_peer_sample，拒绝比较",
                "本阶段不开放正式排名",
            ],
        },
        # 9 A/C 份额成本证据
        "9_share_cost_evidence": {
            "cost_comparison": cost,
            "grade": grades["indicators"]["share_cost_comparison"],
            "buy_sell_conclusion": None,
            "reason": ("费率字段不完整、持有期口径 unknown、"
                       "支付宝实际费率不可验证 → 不给出 A/C 优劣结论"),
        },
        # 10 不可计算指标
        "10_not_computable": {
            "items": {k: v for k, v in grades["indicators"].items()
                      if v.get("value") is None},
            "count": grades["not_computable_count"],
            "engine_not_computed": ind.get("not_computed"),
        },
        # 11 研究结论
        "11_conclusions": conclusions,
        # 12 结论限制
        "12_limitations": {
            "engine_limitations": report.get("limitations"),
            "report_limitations": [
                "净值连续性 cannot_verify（无真实公布日历）",
                "分红记录不完整，未用其修复历史收益",
                "规模与经理只有当前快照，不能作历史时点因子",
                "支付宝可购买状态与实际费率均不可验证",
                "同类样本量小，只能描述性对照",
                "不构成投资建议，不预测未来收益",
            ],
            "boundary": CONCLUSION_BOUNDARY,
        },
        "gate": GATE,
    }
    return doc


def report_to_markdown(doc: dict) -> str:
    """把 JSON 报告渲染成 Markdown（字段与 JSON 一一对应，不新增数值）。"""
    if doc.get("status") != "found":
        return (f"# 研究报告 {doc.get('query')}\n\n"
                f"状态：`{doc.get('status')}`\n\n原因：{doc.get('reason')}\n")

    L: list[str] = []
    b = doc["1_basic_info"]
    L.append(f"# 研究报告：{b.get('fund_name')}（{b.get('share_code')}）")
    L.append("")
    L.append(f"> 生成时间 {doc['generated_at']}　阶段 3B-5.5")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 1. 基金基本信息")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    for k, cn in (("fund_id", "本体 ID"), ("fund_code", "本体代码"),
                  ("fund_name", "基金名称"), ("share_code", "份额代码"),
                  ("share_name", "份额名称"), ("fund_company", "基金公司"),
                  ("established_date", "成立日"), ("benchmark", "业绩基准"),
                  ("tracking_index", "跟踪指数"), ("share_count", "份额数")):
        L.append(f"| {cn} | {b.get(k)} |")
    L.append("")

    c = doc["2_product_classification"]
    L.append("## 2. 产品分类")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    L.append(f"| 产品分类 | `{c.get('product_class')}` |")
    L.append(f"| 子类型 | `{c.get('investment_subtype')}` |")
    L.append(f"| 判定依据 | {c.get('basis')} |")
    L.append(f"| 置信度 | {c.get('confidence')} |")
    L.append(f"| 是否货币基金 | {c.get('is_money_fund')} |")
    L.append("")

    d = doc["3_data_source"]
    L.append("## 3. 数据来源与时间范围")
    L.append("")
    L.append(f"- 来源：{d.get('source')}")
    L.append(f"- 覆盖：{d.get('date_min')} ~ {d.get('date_max')}（{d.get('rows')} 条）")
    L.append(f"- 净值类型：`{d.get('nav_kind')}`")
    L.append(f"- 主要收益口径：**`{d.get('return_field')}`**（累计净值）")
    L.append(f"- `unit_nav` 位置：{d['unit_nav_reference'].get('note')}")
    L.append("")

    q = doc["4_data_quality_level"]
    L.append("## 4. 数据质量总等级")
    L.append("")
    L.append(f"### **{q['overall_level']}** — {q['level_meaning']}")
    L.append("")
    L.append(f"> {q['statement']}")
    L.append("")
    L.append("| 组成 | 等级 | 状态 | 证据 | 限制 |")
    L.append("| --- | --- | --- | --- | --- |")
    for name, c2 in q["components"].items():
        L.append(f"| {name} | **{c2['quality_level']}** | `{c2['status']}` | "
                 f"{c2['evidence']} | {c2.get('limitation')} |")
    L.append("")

    g = doc["5_indicator_grades"]
    L.append("## 5. 各指标及质量等级")
    L.append("")
    L.append("| 指标 | 值 | 状态 | 等级 | 证据 | 限制 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for key, cell in g["indicators"].items():
        v = cell.get("value")
        vs = "—" if v is None else (f"{v:.6f}" if isinstance(v, float) else str(v))
        L.append(f"| {key} | {vs} | `{cell['status']}` | "
                 f"**{cell['quality_level']}** | {cell.get('evidence')} | "
                 f"{cell.get('limitation') or '—'} |")
    L.append("")
    L.append(f"等级分布：{g['level_counts']}　"
             f"可计算 {g['computable_count']} 项 / "
             f"不可计算 {g['not_computable_count']} 项")
    L.append("")

    a = doc["6_gaps_and_anomalies"]
    L.append("## 6. 数据缺口与异常")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    for k, cn in (("max_gap_days", "最大缺口(天)"), ("max_gap_at", "缺口位置"),
                  ("gap_count_over_threshold", "超阈值缺口数"),
                  ("null_unit_nav", "单位净值空值"),
                  ("null_acc_nav", "累计净值空值"),
                  ("duplicate_dates", "重复日期"),
                  ("nonpositive_unit_nav", "非正净值"),
                  ("continuity_verification", "连续性验证")):
        L.append(f"| {cn} | {a.get(k)} |")
    L.append("")
    L.append(f"> {a.get('note')}")
    L.append("")

    L.append("## 7. 收益风险描述")
    L.append("")
    rr = doc["7_return_risk"]
    if rr.get("caliber") == "money_market":
        L.append("**货币基金独立口径**（不与净值型混算）")
        L.append("")
        L.append(f"- 每万份收益：状态 `{rr['per_10k_yield'].get('status')}`，"
                 f"样本 {rr['per_10k_yield'].get('sample_days')} 天，"
                 f"累计 {rr['per_10k_yield'].get('cumulative_per_10k')} 元/万份")
        L.append(f"- 7 日年化：最新 {rr['seven_day_annual'].get('latest')}%"
                 f"（{rr['seven_day_annual'].get('latest_date')}），"
                 f"区间 {rr['seven_day_annual'].get('min')}% ~ "
                 f"{rr['seven_day_annual'].get('max')}%")
    else:
        L.append("**口径：`acc_nav` 累计净值**（含分红再投资代理）")
        L.append("")
        rets = rr.get("returns") or {}
        L.append("| 窗口 | 收益 | 状态 |")
        L.append("| --- | --- | --- |")
        for k in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "ret_36m",
                  "ret_since_inception"):
            n = rets.get(k) or {}
            v = n.get("value")
            L.append(f"| {n.get('label') or k} | "
                     f"{'—' if v is None else f'{v:.4%}'} | `{n.get('status')}` |")
    L.append("")

    p = doc["8_peer_comparability"]
    L.append("## 8. 同类可比性")
    L.append("")
    pg = p["peer_group"]
    L.append(f"- 同类组：`{pg.get('peer_key')}`")
    L.append(f"- 成员本体数：{pg.get('member_count')}（A/C 已按 fund_id 去重）")
    L.append(f"- 分组来源：`{pg.get('grouping_source')}`")
    L.append(f"- 评级：**{p['grade']['quality_level']}** "
             f"（`{p['grade']['status']}`）")
    L.append(f"- 结论：{p['grade'].get('reason') or '可作描述性并列'}")
    L.append("")

    s = doc["9_share_cost_evidence"]
    L.append("## 9. A/C 份额成本证据")
    L.append("")
    L.append(f"- 评级：**{s['grade']['quality_level']}** "
             f"（`{s['grade']['status']}`）")
    L.append(f"- 证据：{s['grade'].get('evidence')}")
    L.append(f"- **不给出 A/C 优劣结论**：{s['reason']}")
    L.append("")

    nc = doc["10_not_computable"]
    L.append("## 10. 不可计算指标")
    L.append("")
    L.append(f"共 {nc['count']} 项。")
    L.append("")
    L.append("| 指标 | 状态 | 原因 |")
    L.append("| --- | --- | --- |")
    for k, cell in nc["items"].items():
        L.append(f"| {k} | `{cell['status']}` | {cell.get('reason') or '—'} |")
    L.append("")

    co = doc["11_conclusions"]
    L.append("## 11. 研究结论")
    L.append("")
    L.append("### 11.1 数据支持的事实")
    L.append("")
    for x in co["facts_supported_by_data"]:
        L.append(f"- {x}")
    L.append("")
    L.append("### 11.2 有条件的描述性判断")
    L.append("")
    for x in co["conditional_descriptive_judgements"]:
        L.append(f"- {x}")
    L.append("")
    L.append("### 11.3 目前无法证明的事项")
    L.append("")
    for x in co["cannot_prove_yet"]:
        L.append(f"- {x}")
    L.append("")

    lm = doc["12_limitations"]
    L.append("## 12. 结论限制")
    L.append("")
    L.append("| 用途 | 是否允许 |")
    L.append("| --- | --- |")
    bd = lm["boundary"]
    L.append(f"| {bd['can_be_used_as']} | ✅ |")
    for x in bd["cannot_be_used_as"]:
        L.append(f"| {x} | ❌ |")
    L.append("")
    for x in lm["report_limitations"]:
        L.append(f"- {x}")
    L.append("")
    return "\n".join(L)
