"""阶段3B-5.5 数据质量分级与指标级可信度（只读层）。

三条铁律（本模块的设计前提）：

1. **质量等级只看数据，绝不看收益高低。**
   收益差 ≠ 数据差；收益好 ≠ 数据好。
   本模块的输入只有行数、覆盖区间、缺口、空值、来源、字段可用性，
   **不接收任何收益率数值**。

2. **指标级评级独立于基金级评级。**
   整只基金一个总等级不够用：同一只基金可能
   「近1年收益 A、年化收益 D、Sharpe D、同类比较 C」。
   每个指标各自带 status / quality_level / evidence / limitation / reason。

3. **算不出来就标 D / not_available，绝不填数。**
   不用 0 冒充无风险利率，不用 0 冒充缺失收益，不把分段回撤包装成全区间回撤。

等级定义
--------
| 级别 | 含义 |
| --- | --- |
| A | 数据质量较好，可支持常规描述性研究 |
| B | 有条件可用，存在明确限制（如历史缺口） |
| C | 证据不足，只能展示有限描述性信息 |
| D | 数据不合格，不应生成相关研究结论 |

另有 ``not_applicable``：该指标**在产品类型上不适用**
（如货币基金 × 净值型收益），不参与 A~D 评定，
也不等于「数据差」。
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

LEVEL_A = "A"
LEVEL_B = "B"
LEVEL_C = "C"
LEVEL_D = "D"
LEVEL_NA = "not_applicable"

LEVEL_ORDER = {LEVEL_A: 0, LEVEL_B: 1, LEVEL_C: 2, LEVEL_D: 3}

LEVEL_MEANING = {
    LEVEL_A: "数据质量较好，可支持常规描述性研究",
    LEVEL_B: "有条件可用，存在明确限制",
    LEVEL_C: "证据不足，只能展示有限描述性信息",
    LEVEL_D: "数据不合格，不应生成相关研究结论",
    LEVEL_NA: "该指标在产品类型上不适用，不参与质量评定",
}


# ---------------------------------------------------------------- 基础工具
def _span_days(date_min: str | None, date_max: str | None) -> int:
    if not date_min or not date_max:
        return 0
    try:
        d0 = datetime.strptime(date_min[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(date_max[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return max((d1 - d0).days, 0)


def _span_years(date_min: str | None, date_max: str | None) -> float:
    return round(_span_days(date_min, date_max) / 365.25, 2)


def _cell(level: str, *, status: str, value=None, evidence: str,
          limitation: str | None = None, reason: str | None = None) -> dict:
    """统一的评级单元结构。"""
    return {
        "value": value,
        "status": status,
        "quality_level": level,
        "level_meaning": LEVEL_MEANING.get(level, level),
        "evidence": evidence,
        "limitation": limitation,
        "reason": reason,
    }


def worst_level(*levels: str) -> str:
    """取最差等级；not_applicable 不参与比较。"""
    real = [lv for lv in levels if lv in LEVEL_ORDER]
    if not real:
        return LEVEL_NA
    return max(real, key=lambda lv: LEVEL_ORDER[lv])


# ---------------------------------------------------------------- 基金级：净值覆盖
def grade_nav_data(quality: dict | None, *, is_money: bool = False) -> dict:
    """净值/货币收益**数据本身**的质量等级。

    输入只含数据完整性字段，**不含任何收益数值**。
    """
    q = quality or {}
    rows = int(q.get("rows") or 0)
    dmin, dmax = q.get("date_min"), q.get("date_max")
    gaps = int(q.get("gap_count_over_threshold") or 0)
    null_acc = int(q.get("null_acc_nav", q.get("null_acc")) or 0)
    null_unit = int(q.get("null_unit_nav", q.get("null_unit")) or 0)
    dup = int(q.get("duplicate_dates") or 0)
    nonpos = int(q.get("nonpositive_unit_nav", q.get("nonpositive_unit")) or 0)
    span_y = _span_years(dmin, dmax)

    if rows <= 0:
        return _cell(
            LEVEL_D, status="no_data", value=0,
            evidence=f"表内 0 条{'货币收益' if is_money else '净值'}记录",
            limitation="无任何可用序列，所有基于序列的指标均不可计算",
            reason="无数据")

    problems = []
    if dup:
        problems.append(f"{dup} 条重复日期")
    if null_acc:
        problems.append(f"{null_acc} 条累计净值空值")
    if null_unit:
        problems.append(f"{null_unit} 条单位净值空值")
    if nonpos:
        problems.append(f"{nonpos} 条非正净值")

    evidence = (f"{rows} 条记录，覆盖 {dmin} ~ {dmax}"
                f"（{span_y} 年），超阈值缺口 {gaps} 处")

    if problems:
        return _cell(
            LEVEL_C, status="anomalies", value=rows,
            evidence=evidence + "；" + "、".join(problems),
            limitation="存在结构性异常，相关指标只能部分使用",
            reason="数据异常")

    if span_y < 1.0:
        return _cell(
            LEVEL_C, status="short_history", value=rows,
            evidence=evidence,
            limitation="历史不足 1 年，长窗口指标必然 insufficient_data",
            reason="历史过短")

    if gaps:
        return _cell(
            LEVEL_B, status="usable_with_gaps", value=rows,
            evidence=evidence,
            limitation=(f"{gaps} 处超过阈值的缺口；跨越缺口的历史区间"
                        "不得用于年化收益与连续性推断"),
            reason="存在历史缺口")

    if span_y < 3.0:
        return _cell(
            LEVEL_B, status="usable_short_span", value=rows,
            evidence=evidence,
            limitation="历史不足 3 年，近 3 年窗口可能不可计算",
            reason="历史长度有限")

    return _cell(
        LEVEL_A, status="ok", value=rows,
        evidence=evidence + "；无重复、无空值、无超阈值缺口",
        limitation="净值连续性仍为 cannot_verify（无真实公布日历）",
        reason=None)


# ---------------------------------------------------------------- 基金级：来源
def grade_source(source: str | None) -> dict:
    """数据来源等级。第三方公开接口一律 third_party。"""
    if not source:
        return _cell(LEVEL_D, status="unknown_source", value=None,
                     evidence="记录未标注来源",
                     limitation="无法追溯数据出处",
                     reason="来源缺失")
    if source.startswith("akshare.") or "announcement" in source:
        return _cell(LEVEL_B, status="third_party", value=source,
                     evidence=f"来源 {source}（公开第三方接口）",
                     limitation="第三方聚合数据，非基金公司原始披露；不得冒充支付宝数据",
                     reason="第三方来源")
    return _cell(LEVEL_C, status="other_source", value=source,
                 evidence=f"来源 {source}",
                 limitation="来源不属于已审计的公开接口",
                 reason="来源未经审计")


# ---------------------------------------------------------------- 基金级：合计
def grade_fund(quality: dict | None, *, is_money: bool = False,
               source: str | None = None) -> dict:
    """基金级**数据质量**总等级（不含收益）。

    取「序列完整性」与「来源可信度」的较差者。
    费率/经理/规模的缺失属于**指标级**限制，不拉低基金级等级，
    但会在 components 里如实列出。
    """
    nav = grade_nav_data(quality, is_money=is_money)
    src = grade_source(source)
    overall = worst_level(nav["quality_level"], src["quality_level"])

    q = quality or {}
    return {
        "overall_level": overall,
        "level_meaning": LEVEL_MEANING.get(overall, overall),
        "components": {
            "series": nav,
            "source": src,
        },
        "not_influenced_by_returns": True,
        "statement": (
            "本等级只由数据完整性（行数/覆盖区间/缺口/空值/重复/非正）"
            "与来源可信度计算，**与基金收益高低无关**。"
            "收益表现差不会降低本等级，收益表现好也不会提高本等级。"),
        "coverage": {
            "rows": int(q.get("rows") or 0),
            "date_min": q.get("date_min"),
            "date_max": q.get("date_max"),
            "span_years": _span_years(q.get("date_min"), q.get("date_max")),
            "gap_count_over_threshold": int(q.get("gap_count_over_threshold") or 0),
            "continuity_verification": q.get("continuity_verification",
                                             "cannot_verify"),
        },
    }


# ---------------------------------------------------------------- 指标级
def _ret_cell(node: dict | None, label: str, *, quality: dict) -> dict:
    """区间收益指标评级。"""
    n = node or {}
    status = n.get("status")
    if status == "ok":
        gaps = int(quality.get("gap_count_over_threshold") or 0)
        return _cell(
            LEVEL_A, status="ok", value=n.get("value"),
            evidence=(f"{label}：{n.get('start_date')} → {n.get('end_date')}，"
                      f"{n.get('start_value')} → {n.get('end_value')}"
                      f"（{n.get('field')}）"),
            limitation=("全区间存在缺口，但本窗口内无超阈值缺口"
                        if gaps else None),
            reason=None)
    return _cell(
        LEVEL_D, status=status or "insufficient_data", value=None,
        evidence=f"{label}：窗口端点未精确命中或无可用值",
        limitation="不向前后找替代值，不用 0 填充缺失收益",
        reason=n.get("reason") or "窗口数据不足")


def grade_annualized(node: dict | None) -> dict:
    n = node or {}
    if n.get("status") == "ok":
        return _cell(
            LEVEL_A, status="ok", value=n.get("value"),
            evidence=(f"成立以来年化，按实际自然日间隔；"
                      f"起始 {n.get('start_date')}，结束 {n.get('end_date')}"),
            limitation="年化是折算值，不等于未来可实现收益",
            reason=None)
    return _cell(
        LEVEL_D, status=n.get("status") or "insufficient_data", value=None,
        evidence="区间内存在超过阈值的缺口或样本不足",
        limitation="不跨越缺口折算年化",
        reason=n.get("reason") or "样本不足")


def grade_max_drawdown(node: dict | None) -> dict:
    n = node or {}
    if n.get("status") != "ok":
        return _cell(
            LEVEL_D, status=n.get("status") or "insufficient_data", value=None,
            evidence="无连续可观测净值段",
            limitation="无法计算回撤",
            reason=n.get("reason"))
    if n.get("degraded") or n.get("complete_interval") is False:
        return _cell(
            LEVEL_B, status="degraded", value=n.get("value"),
            evidence=(f"分段可观测结果：{n.get('segment_count')} 段，"
                      f"缺口 {n.get('gap_count_over_threshold')} 处，"
                      f"空值 {n.get('null_count')} 条"),
            limitation=("**不是全区间完整最大回撤**，只是可观测连续段内的最大值，"
                        "可能被低估；缺口两端不视为连续路径"),
            reason=n.get("degraded_reason"))
    return _cell(
        LEVEL_A, status="ok", value=n.get("value"),
        evidence=(f"全区间连续，{n.get('segment_count')} 段，"
                  f"无超阈值缺口与空值"),
        limitation="净值连续性仍为 cannot_verify（无真实公布日历）",
        reason=None)


def grade_daily_volatility(node: dict | None) -> dict:
    """日波动率。

    注意字段语义：``value`` 是可对外报告的波动率
    （可年化时是年化值，不可年化时就是日值），
    真正的**日波动**永远是 ``daily_vol``。这里必须取 ``daily_vol``，
    否则会把年化值当日波动展示。
    """
    n = node or {}
    if n.get("status") != "ok":
        return _cell(LEVEL_D, status=n.get("status") or "insufficient_data",
                     value=None, evidence="样本不足",
                     limitation="无法计算日波动", reason=n.get("reason"))
    daily = n.get("daily_vol")
    if daily is None:
        return _cell(LEVEL_D, status="insufficient_data", value=None,
                     evidence="无 daily_vol 字段",
                     limitation="无法确认日波动值", reason="字段缺失")
    return _cell(
        LEVEL_A, status="ok", value=daily,
        evidence=(f"日波动 {daily}（样本 {n.get('sample_size')} 点，"
                  f"观测频率 {n.get('observed_per_year')} 次/年）"),
        limitation="只描述观测到的高频波动，不含未观测日",
        reason=None)


def grade_annualized_volatility(node: dict | None) -> dict:
    """年化波动率：只有在年化条件满足时才有值。"""
    n = node or {}
    if n.get("status") != "ok":
        return _cell(LEVEL_D, status=n.get("status") or "insufficient_data",
                     value=None, evidence="样本不足",
                     limitation="无法计算波动率", reason=n.get("reason"))
    if not n.get("annualized"):
        return _cell(
            LEVEL_D, status="blocked", value=None,
            evidence=(f"日波动可算（{n.get('daily_vol')}），但年化被阻塞："
                      f"{n.get('annualization_blocked_reason')}"),
            limitation="不乘任何年化因子，避免把不连续序列伪装成年度风险",
            reason=n.get("annualization_blocked_reason"))
    return _cell(
        LEVEL_A, status="ok", value=n.get("value"),
        evidence=(f"年化因子 {n.get('annualization_factor')}，"
                  f"依据 {n.get('annualization_basis')}"),
        limitation="年化波动是观测频率的折算，不是未来风险承诺",
        reason=None)


def grade_sharpe(node: dict | None) -> dict:
    n = node or {}
    if n.get("status") == "ok":
        return _cell(LEVEL_B, status="ok", value=n.get("value"),
                     evidence="有可用无风险利率序列",
                     limitation="无风险利率口径需与基金持有期匹配",
                     reason=None)
    return _cell(
        LEVEL_D, status=n.get("status") or "not_available", value=None,
        evidence="无可靠无风险利率数据源",
        limitation="**不把 0 冒充真实无风险利率**，因此不输出常规 Sharpe",
        reason=n.get("reason"))


def grade_excess_return(not_computed: dict | None) -> dict:
    nc = not_computed or {}
    reason = nc.get("excess_return")
    if reason is None:
        return _cell(LEVEL_B, status="computable", value=None,
                     evidence="存在可用基准收益序列",
                     limitation="超额收益依赖基准口径，需与同类组一致",
                     reason=None)
    return _cell(
        LEVEL_D, status="not_computed", value=None,
        evidence="库内无基准收益序列（只有基准描述文本，没有基准净值）",
        limitation="缺基准序列时禁止计算超额收益",
        reason=reason)


def grade_peer_comparison(peer_ctx: dict | None) -> dict:
    """同类比较评级。

    peer_ctx: {peer_key, member_count, grouping_source, benchmark_confidence,
               verifiable_group, index_scope}
    """
    c = peer_ctx or {}
    key = c.get("peer_key")
    n = int(c.get("member_count") or 0)
    src = c.get("grouping_source")
    conf = c.get("benchmark_confidence")
    verifiable = c.get("verifiable_group")

    if not key or key.startswith("unknown"):
        return _cell(
            LEVEL_D, status="no_verifiable_group", value=None,
            evidence=f"同类组键为 {key!r}，无可验证基准或跟踪指数",
            limitation="不得仅凭基金名称相似判定同类",
            reason="分组不可验证")
    if n < 2:
        return _cell(
            LEVEL_D, status="insufficient_peer_sample", value=None,
            evidence=f"同类组 {key} 只有 {n} 个本体",
            limitation="样本不足时**拒绝比较**，不强行构造同类排名",
            reason="同类样本不足")
    if src == "unknown" or conf == "none":
        return _cell(
            LEVEL_C, status="weak_grouping", value=n,
            evidence=f"同类组 {key}，{n} 个本体，但分组依据不可靠（{src}）",
            limitation="分组依据弱，只做描述性并列，不做强弱判断",
            reason="分组依据弱")
    if n < 5:
        return _cell(
            LEVEL_C, status="small_sample", value=n,
            evidence=f"同类组 {key}，{n} 个本体，分组来源 {src}（置信度 {conf}）",
            limitation="样本量小，只能描述性对照，不能推广为同类排名",
            reason="样本量小于 5")
    return _cell(
        LEVEL_B, status="usable", value=n,
        evidence=f"同类组 {key}，{n} 个本体，分组来源 {src}（置信度 {conf}）",
        limitation="仅描述性并列；本项目仍不开放正式排名",
        reason=None)


def grade_share_cost(cost: dict | None) -> dict:
    """A/C 份额成本比较评级。"""
    c = cost or {}
    shares = c.get("shares") or []
    if len(shares) < 2:
        return _cell(
            LEVEL_NA, status="single_share", value=len(shares),
            evidence="该本体只有 1 个份额，不存在 A/C 成本比较",
            limitation="无份额差异可比较",
            reason="单一份额")
    have_sales = sum(1 for s in shares
                     if (s.get("sales_service_fee") or {}).get("status") == "ok")
    have_purchase = sum(1 for s in shares
                        if (s.get("purchase_fee") or {}).get("status") == "partial")
    have_redeem = sum(1 for s in shares
                      if (s.get("redemption_fee") or {}).get("status") == "partial")
    n = len(shares)
    evidence = (f"{n} 个份额；销售服务费可得 {have_sales}/{n}，"
                f"申购费阶梯可得 {have_purchase}/{n}，"
                f"赎回费阶梯可得 {have_redeem}/{n}")
    full = have_sales == n and have_purchase == n and have_redeem == n
    if not full:
        return _cell(
            LEVEL_D, status="insufficient_fee_evidence", value=None,
            evidence=evidence,
            limitation=("费率字段不完整：缺申购/赎回阶梯或持有期口径未确认；"
                        "支付宝实际费率 unknown"),
            reason="费率证据不足，不得给出 A/C 确定性推荐")
    return _cell(
        LEVEL_C, status="partial_evidence", value=None,
        evidence=evidence,
        limitation=("即使字段齐全，持有期口径仍 unknown、"
                    "费率生效日不完整、支付宝实际费率不可验证"),
        reason="只能做条件性费用对照，不做 A/C 推荐")


# ---------------------------------------------------------------- 汇总
INDICATOR_SPECS = (
    ("ret_1m", "近1月收益"),
    ("ret_3m", "近3月收益"),
    ("ret_6m", "近6月收益"),
    ("ret_12m", "近1年收益"),
    ("ret_36m", "近3年收益"),
    ("annualized_return", "年化收益"),
    ("max_drawdown", "最大回撤"),
    ("daily_volatility", "日波动率"),
    ("annualized_volatility", "年化波动率"),
    ("sharpe", "Sharpe"),
    ("excess_return", "超额收益"),
    ("peer_comparison", "同类比较"),
    ("share_cost_comparison", "A/C份额成本比较"),
)


def build_indicator_grades(report: dict, *, peer_ctx: dict | None = None,
                           cost: dict | None = None) -> dict:
    """对一份单份额报告逐指标评级。

    货币基金的净值型指标统一返回 not_applicable，不伪造数值。
    """
    quality = report.get("quality") or {}
    ind = report.get("indicators") or {}
    is_money = bool(report.get("is_money_fund"))

    out: dict[str, dict] = {}

    if is_money:
        for key, label in INDICATOR_SPECS:
            if key == "share_cost_comparison":
                out[key] = grade_share_cost(cost)
            elif key == "peer_comparison":
                out[key] = grade_peer_comparison(peer_ctx)
            else:
                out[key] = _cell(
                    LEVEL_NA, status="not_applicable", value=None,
                    evidence=f"货币基金不使用净值口径，{label}不适用",
                    limitation="每万份收益与 7 日年化为独立口径，"
                               "不得与净值型收益混算",
                    reason="产品类型不适用")
    else:
        rets = ind.get("returns") or {}
        risk = ind.get("risk") or {}
        ra = ind.get("risk_adjusted") or {}
        for key, label in INDICATOR_SPECS:
            if key in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "ret_36m"):
                out[key] = _ret_cell(rets.get(key), label, quality=quality)
            elif key == "annualized_return":
                out[key] = grade_annualized(ind.get("annualized_return"))
            elif key == "max_drawdown":
                out[key] = grade_max_drawdown(risk.get("max_drawdown"))
            elif key == "daily_volatility":
                out[key] = grade_daily_volatility(risk.get("volatility"))
            elif key == "annualized_volatility":
                out[key] = grade_annualized_volatility(risk.get("volatility"))
            elif key == "sharpe":
                out[key] = grade_sharpe(ra.get("sharpe"))
            elif key == "excess_return":
                out[key] = grade_excess_return(ind.get("not_computed"))
            elif key == "peer_comparison":
                out[key] = grade_peer_comparison(peer_ctx)
            elif key == "share_cost_comparison":
                out[key] = grade_share_cost(cost)

    counts: dict[str, int] = {}
    for v in out.values():
        counts[v["quality_level"]] = counts.get(v["quality_level"], 0) + 1

    # 三个数量必须分开统计，不能混：
    # - computable：有真实数值
    # - not_applicable：产品类型上不适用（货币基金 × 净值型指标）
    # - not_computable：适用但算不出来（缺数据/缺条件）
    na_keys = [k for k, v in out.items()
               if v.get("quality_level") == LEVEL_NA]
    computable = [k for k, v in out.items()
                  if v.get("value") is not None
                  and v.get("quality_level") != LEVEL_NA]
    blocked = [k for k, v in out.items()
               if v.get("quality_level") != LEVEL_NA
               and v.get("value") is None]
    return {
        "indicators": out,
        "indicator_count": len(out),
        "level_counts": counts,
        "computable_count": len(computable),
        "not_applicable_count": len(na_keys),
        "not_computable_count": len(blocked),
        "computable_keys": computable,
        "not_applicable_keys": na_keys,
        "not_computable_keys": blocked,
        "note": ("逐指标评级；A/B/C/D 描述**证据强度**，"
                 "不是基金好坏，也不代表收益高低。"
                 "not_applicable 表示产品类型上不适用，不等于数据差。"),
    }
