"""基金研究报告生成与同类分析（不排名、不出信号）。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.fund.research.classification import PRODUCT_TAXONOMY
from app.fund.research.data_access import (
    load_fee_info, load_money_series, load_nav_series, load_universe,
)
from app.fund.research.fees import compare_share_costs
from app.fund.research.indicators import (
    compute_money_indicators, compute_nav_indicators,
)

# 单只基金数据准入等级判定
def admission_levels(quality: dict | None, indicators: dict | None,
                     money: bool = False) -> dict:
    """按**字段**给准入等级，不给整只基金一个笼统标签。"""
    levels = {}

    if money:
        levels["per_10k_yield"] = "A" if quality and quality["rows"] > 0 else "D"
        levels["seven_day_annual"] = "A" if quality and quality["rows"] > 0 else "D"
        levels["unit_nav"] = "not_applicable"
        levels["acc_nav"] = "not_applicable"
    else:
        q = quality or {}
        nulls = q.get("null_unit", 0) + q.get("null_acc", 0)
        dup = q.get("duplicate_dates", 0)
        levels["unit_nav"] = ("B" if nulls or dup else "A") if q.get("rows") else "D"
        levels["acc_nav"] = ("B" if nulls or dup else "A") if q.get("rows") else "D"

    levels["aum"] = "C"          # 平台观测日期，不可作时点因子
    levels["dividend"] = "C"     # 完整性未验证
    levels["manager_history"] = "B"
    levels["termination_events"] = "B"
    levels["alipay_purchasable"] = "unknown"
    return levels


def _series_summary(series) -> dict:
    q = series.quality
    return {
        "code": series.code,
        "share_class_id": series.share_class_id,
        "fund_id": series.fund_id,
        "share_class_name": series.share_class_name,
        "nav_kind": series.nav_kind,
        "rows": q.rows,
        "date_min": q.date_min,
        "date_max": q.date_max,
        "duplicate_dates": q.duplicate_dates,
        "out_of_order": q.out_of_order,
        "null_unit_nav": q.null_unit,
        "null_acc_nav": q.null_acc,
        "nonpositive_unit_nav": q.nonpositive_unit,
        "max_gap_days": q.max_gap_days,
        "max_gap_at": list(q.max_gap_at) if q.max_gap_at else None,
        "gap_count_over_threshold": q.gap_count_over_threshold,
        "gaps_sample": q.gaps[:5],
        "acc_equals_unit_ratio": q.acc_equals_unit_ratio,
        "has_dividend_effect": q.has_dividend_effect,
        "acc_usable_as_total_return": q.acc_usable_as_total_return,
        "continuity_verification": q.continuity_verification,
        "quality_flags": q.quality_flags,
    }


def analyze_fund(db_path: Path | None, entry: dict) -> dict:
    """单份额研究报告。entry 来自 load_universe()。"""
    code = entry["share_code"]
    money = entry["product_class"] == "money_market"

    if money:
        m = load_money_series(db_path, code=code)
        ind = compute_money_indicators(m, db_path)
        quality = {"code": code, "rows": m.get("rows", 0),
                   "date_min": m.get("date_min"), "date_max": m.get("date_max"),
                   "null_unit": 0, "null_acc": 0, "duplicate_dates": 0}
        return {
            "fund_id": entry["fund_id"],
            "fund_code": entry["fund_code"],
            "fund_name": entry["fund_name"],
            "share_code": code,
            "share_name": entry["share_name"],
            "product_class": entry["product_class"],
            "investment_subtype": entry["investment_subtype"],
            "classification_basis": entry["basis"],
            "classification_confidence": entry["confidence"],
            "peer_group": entry["peer_group"],
            "is_money_fund": True,
            "data_source": "akshare.fund_open_fund_info_em（天天基金）",
            "quality": m,
            "indicators": ind,
            "admission_levels": admission_levels(m, ind, money=True),
            "fee_info": load_fee_info(db_path, code=code),
            "limitations": [
                "货币基金不使用单位净值/累计净值，完全不参与净值型指标",
                "只能与其他货币基金比较，禁止与净值型基金同榜",
                "净值连续性 cannot_verify",
            ],
        }

    series = load_nav_series(db_path, code=code, nav_kind="net_value")
    if series is None or not series.points:
        return {
            "fund_id": entry["fund_id"], "fund_code": entry["fund_code"],
            "fund_name": entry["fund_name"], "share_code": code,
            "share_name": entry["share_name"],
            "product_class": entry["product_class"],
            "investment_subtype": entry["investment_subtype"],
            "peer_group": entry["peer_group"],
            "is_money_fund": False,
            "status": "no_nav_data",
            "indicators": {"status": "insufficient_data",
                           "reason": "该份额无 net_value 净值记录"},
            "admission_levels": admission_levels(None, None),
            "limitations": ["无净值数据，所有指标不可计算"],
        }

    qdict = series.quality.as_dict()
    ind = compute_nav_indicators(series, field_name="acc_nav")
    # 同时给 unit_nav 口径，明确区分
    ind_unit = compute_nav_indicators(series, field_name="unit_nav")

    return {
        "fund_id": entry["fund_id"],
        "fund_code": entry["fund_code"],
        "fund_name": entry["fund_name"],
        "share_code": code,
        "share_name": entry["share_name"],
        "product_class": entry["product_class"],
        "investment_subtype": entry["investment_subtype"],
        "classification_basis": entry["basis"],
        "classification_confidence": entry["confidence"],
        "peer_group": entry["peer_group"],
        "index_scope": entry.get("index_scope"),
        "benchmark": entry.get("benchmark"),
        "established_date": entry.get("established_date"),
        "is_money_fund": False,
        "data_source": "akshare.fund_open_fund_info_em（天天基金）",
        "quality": _series_summary(series),
        "indicators": ind,
        "indicators_unit_nav": {
            "note": "unit_nav 口径，不含分红，**不是总回报**，仅供对照",
            "returns": ind_unit["returns"],
            "annualized_return": ind_unit["annualized_return"],
        },
        "admission_levels": admission_levels(qdict, ind),
        "fee_info": load_fee_info(db_path, code=code),
        "limitations": [
            "净值连续性 cannot_verify（无真实基金公布日历）",
            "收益基于 acc_nav 原值，**未**用不完整分红数据修复",
            "规模数据是平台观测日期，不可作历史时点因子",
            "支付宝可购买状态 unknown",
            "超额收益/风格稳定性因缺基准序列与持仓数据不可算",
        ],
        "conclusion_boundary": {
            "is_forecast": False,
            "is_investment_advice": False,
            "can_be_used_as": "描述性历史观察",
            "cannot_be_used_as": ["未来收益预测", "买入建议", "跨类别排名依据"],
        },
    }


REPRESENTATIVE_RULES = (
    "代表份额选择顺序（显式规则，不静默取不完整数据）："
    "① 主份额且净值记录数 > 0；"
    "② 任一份额中净值记录数最多者（并列取代码最小）；"
    "③ 全部份额都无净值记录 → status=insufficient_data，performance=None。"
)


def _nav_rows(r: dict) -> int | None:
    """净值记录数。quality 缺失 → None（未知），不当 0。"""
    q = r.get("quality")
    if not q or "rows" not in q:
        return None
    return int(q.get("rows") or 0)


def _pick_representative(rs: list[dict]) -> tuple[dict | None, str]:
    """按显式规则挑代表份额，返回 (份额, 原因)。

    不静默取不完整数据：
    - 记录数未知时不当作 0，而是在原因里说明；
    - 全部份额无数据时返回 None + insufficient_data。
    """
    rows_map = {r["share_code"]: _nav_rows(r) for r in rs}
    known = {k: v for k, v in rows_map.items() if v is not None}
    unknown_count = len(rows_map) - len(known)

    if not known:
        primary = next((r for r in rs if r.get("share_code") == r.get("fund_code")),
                       min(rs, key=lambda r: r["share_code"]))
        return primary, ("净值记录数未知（quality 缺失），"
                         f"按主份额代码优先选择 {primary['share_code']}，"
                         "数据充分性未确认")

    with_data = [r for r in rs if (rows_map.get(r["share_code"]) or 0) > 0]
    if not with_data:
        return None, (f"全部 {len(rs)} 个份额均无净值记录"
                      + (f"（{unknown_count} 个记录数未知）" if unknown_count else "")
                      + "，标记 insufficient_data")

    primaries = [r for r in with_data if r.get("share_code") == r.get("fund_code")]
    if primaries:
        p = max(primaries, key=lambda r: rows_map[r["share_code"]] or 0)
        return p, (f"主份额 {p['share_code']} 且有 "
                   f"{rows_map[p['share_code']]} 条净值记录")

    best = sorted(with_data,
                  key=lambda r: (-(rows_map[r["share_code"]] or 0), r["share_code"]))[0]
    return best, (f"主份额数据不足或不存在，改选净值记录最多的份额 "
                  f"{best['share_code']}（{rows_map[best['share_code']]} 条）")


def _share_coverage(entry: dict, db_path: Path | None) -> dict:
    """数据覆盖审计摘要（不计算指标，只看数据存在性）。"""
    from app.fund.research.lookup import fee_coverage, nav_coverage
    sid = entry["share_class_id"]
    nav = nav_coverage(sid, db_path)
    fee = fee_coverage(sid, db_path)
    return {
        "share_code": entry["share_code"],
        "share_name": entry["share_name"],
        "is_primary": entry.get("is_primary"),
        "nav_rows": nav["rows_"],
        "nav_date_min": nav["dmin"],
        "nav_date_max": nav["dmax"],
        "null_unit_nav": int(nav["null_unit"] or 0),
        "null_acc_nav": int(nav["null_acc"] or 0),
        "nonpositive_unit_nav": int(nav["nonpositive"] or 0),
        "money_yield_rows": nav["money_yield_rows"],
        "fee_rules_total": fee["total"],
        "fee_rules_with_effective_from": fee["with_effective_from"],
        "has_historical_effective_date": fee["has_historical_effective_date"],
        "alipay_purchasable": fee["alipay_purchasable"],
        "alipay_note": fee["alipay_note"],
    }


def analyze_by_code(code: str, db_path: Path | None = None) -> dict:
    """按代码直接查询并生成研究报告（3B-5.2）。

    状态区分明确：
    - not_found / invalid_code / excluded_product / terminated / no_nav_data / found
    不把「没数据」伪装成「净值为 0」。
    """
    from app.fund.research.lookup import STATUS_FOUND, lookup_fund

    res = lookup_fund(code, db_path)
    q = res["query"]

    base = {
        "phase": "3B-5.2",
        "query": q,
        "status": res["status"],
        "reason": res["reason"],
        "fund_entity": res.get("fund_entity"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if res["status"] != STATUS_FOUND:
        base["reports"] = []
        base["merged"] = None
        base["share_reports_available"] = False
        base["gate"] = _gate()
        return base

    entries = res["entries"]
    # 数据覆盖审计（每个份额一条）
    coverage = [_share_coverage(e, db_path) for e in entries]

    # 无净值 → no_nav_data（而不是算出 0 收益）
    has_nav = any(c["nav_rows"] > 0 or c["money_yield_rows"] > 0 for c in coverage)
    if not has_nav:
        base["status"] = "no_nav_data"
        base["reason"] = ("基金信息存在，但名下所有份额都没有净值/货币收益记录；"
                          "不补录、不填 0")
        base["coverage"] = coverage
        base["reports"] = []
        base["merged"] = None
        base["share_reports_available"] = False
        base["gate"] = _gate()
        return base

    reports = [analyze_fund(db_path, e) for e in entries]
    merged = merge_by_fund(reports, db_path)[0] if reports else None

    base.update({
        "coverage": coverage,
        "reports": reports,
        "merged": merged,
        "share_reports_available": True,
        "share_count": len(entries),
        "fund_count": 1,
        "gate": _gate(),
    })
    return base


def _gate() -> dict:
    return {
        "ready_for_research_analysis": True,
        "ready_for_backtest": False,
        "ready_for_formal_ranking": False,
        "reason": ("单只基金历史描述性分析可用；正式回测与真实排名仍不具备条件"),
    }


def merge_by_fund(reports: list[dict],
                  db_path: Path | None = None) -> list[dict]:
    """按 fund_id 归并 A/C/E 份额。

    - **同类分析与表现比较以 fund_id 为唯一统计单位**；
    - 费用比较**保留份额维度**，不因归并丢失 A/C/E 差异；
    - 代表份额选择有显式规则与原因记录。
    """
    by_fund: dict[int, list[dict]] = defaultdict(list)
    for r in reports:
        by_fund[r["fund_id"]].append(r)

    merged = []
    for fid, rs in by_fund.items():
        rep, rep_reason = _pick_representative(rs)
        head = rep if rep is not None else rs[0]
        perf = rep.get("indicators") if rep is not None else None
        status = "ok" if rep is not None else "insufficient_data"

        merged.append({
            "fund_id": fid,
            "fund_code": head["fund_code"],
            "fund_name": head["fund_name"],
            "product_class": head["product_class"],
            "investment_subtype": head["investment_subtype"],
            "peer_group": head["peer_group"],
            "status": status,
            "representative_share": rep["share_code"] if rep else None,
            "representative_share_name": rep["share_name"] if rep else None,
            "representative_reason": rep_reason,
            "representative_rule": REPRESENTATIVE_RULES,
            "performance": perf,
            "share_count": len(rs),
            "shares": [{"share_code": r["share_code"],
                        "share_name": r["share_name"],
                        "nav_rows": (r.get("quality") or {}).get("rows", 0)}
                       for r in rs],
            # 费用比较保留份额维度
            "cost_comparison": compare_share_costs(db_path, fund_id=fid,
                                                   shares=rs),
        })
    return merged


def peer_analysis(merged: list[dict], *, share_count: int | None = None) -> dict:
    """同类研究分析（不排名）。

    **入参必须是 merge_by_fund() 的本体级结果**：
    每个 fund_id 在同类组里只出现一次，A/C/E 不会重复计数。
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set[int]] = defaultdict(set)
    for r in merged:
        key = (r.get("peer_group") or {}).get("peer_key", "unknown")
        # 双保险：同一 fund_id 在同一组只计一次
        if r["fund_id"] in seen[key]:
            continue
        seen[key].add(r["fund_id"])
        groups[key].append(r)

    out = {}
    for key, members in groups.items():
        entries = []
        for r in members:
            perf = r.get("performance") or {}
            rets = perf.get("returns") or {}
            risk = perf.get("risk") or {}
            entries.append({
                "fund_id": r["fund_id"],
                "fund_code": r["fund_code"],
                "fund_name": r["fund_name"],
                "representative_share": r.get("representative_share"),
                "representative_reason": r.get("representative_reason"),
                "share_count": r.get("share_count"),
                "status": r.get("status"),
                "ret_12m": (rets.get("ret_12m") or {}).get("value"),
                "ret_12m_status": (rets.get("ret_12m") or {}).get("status"),
                "max_drawdown": (risk.get("max_drawdown") or {}).get("value"),
                "mdd_status": (risk.get("max_drawdown") or {}).get("status"),
            })
        pg = members[0].get("peer_group") or {}
        out[key] = {
            "member_count": len(members),
            "fund_ids": sorted(m["fund_id"] for m in members),
            "benchmark_family": pg.get("benchmark_family"),
            "benchmark_confidence": pg.get("benchmark_confidence"),
            "benchmark_reason": pg.get("benchmark_reason"),
            "index_scope": pg.get("index_scope"),
            "verifiable_group": pg.get("verifiable_group"),
            "members": entries,
            "ranking_generated": False,
            "note": ("同类描述性对照，**不排名、不推荐**；"
                     "成员按 fund_id 去重（A/C/E 只算一个本体）；"
                     "不同 peer_group 之间不可横向比较"),
        }
    return {
        "groups": out,
        "group_count": len(out),
        "fund_count": len(merged),
        "share_count": share_count,
        "deduped_by_fund_id": True,
        "cross_group_comparison_allowed": False,
        "ranking_generated": False,
        "reason_no_ranking": (
            "样本量小、净值连续性 cannot_verify、无风险利率与基准序列缺失，"
            "不具备生成正式排名的条件"),
    }


def analyze_universe(db_path: Path | None = None, *,
                     include_terminated: bool = False) -> dict:
    universe = load_universe(db_path, include_terminated=include_terminated)
    reports = [analyze_fund(db_path, e) for e in universe]
    merged = merge_by_fund(reports, db_path)
    # 同类分析必须基于**本体级**结果，A/C/E 不能当多个独立基金
    peers = peer_analysis(merged, share_count=len(reports))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universe": {
            "share_count": len(universe),
            "fund_count": len({e["fund_id"] for e in universe}),
            "by_product_class": _count_by(universe, "product_class"),
            "by_peer_group": _count_by(universe, "peer_group", key="peer_key"),
            "onshore_etf_included": False,
            "terminated_included": include_terminated,
        },
        "reports": reports,
        "merged_by_fund": merged,
        "peer_analysis": peers,
        "gate": {
            "ready_for_research_analysis": True,
            "ready_for_backtest": False,
            "ready_for_formal_ranking": False,
            "reason": (
                "研究性描述分析可用；正式回测与真实排名仍不具备条件"
                "（净值连续性 cannot_verify、无风险利率与基准序列缺失、"
                "费率无历史生效日、支付宝状态 unknown）"),
        },
    }


def _count_by(items: list[dict], field: str, *, key: str | None = None) -> dict:
    out: dict[str, int] = defaultdict(int)
    for it in items:
        v = it.get(field)
        if key and isinstance(v, dict):
            v = v.get(key)
        out[str(v)] += 1
    return dict(out)
