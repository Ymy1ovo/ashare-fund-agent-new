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
        ind = compute_money_indicators(m)
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


def merge_by_fund(reports: list[dict]) -> list[dict]:
    """按 fund_id 归并 A/C/E 份额：表现归并、费用保留份额维度。"""
    by_fund: dict[int, list[dict]] = defaultdict(list)
    for r in reports:
        by_fund[r["fund_id"]].append(r)

    merged = []
    for fid, rs in by_fund.items():
        primary = next((r for r in rs if r.get("share_code") == r.get("fund_code")),
                       rs[0])
        merged.append({
            "fund_id": fid,
            "fund_code": primary["fund_code"],
            "fund_name": primary["fund_name"],
            "product_class": primary["product_class"],
            "investment_subtype": primary["investment_subtype"],
            "peer_group": primary["peer_group"],
            "representative_share": primary["share_code"],
            "share_count": len(rs),
            "shares": [{"share_code": r["share_code"],
                        "share_name": r["share_name"]} for r in rs],
            # 表现只看代表份额（主代码优先）
            "performance": primary.get("indicators"),
            "cost_comparison": compare_share_costs(None, fund_id=fid, shares=rs),
        })
    return merged


def peer_analysis(reports: list[dict]) -> dict:
    """同类研究分析（不排名）。只按 peer_group 分组，组内给描述性统计。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        key = r.get("peer_group", {}).get("peer_key", "unknown")
        groups[key].append(r)

    out = {}
    for key, members in groups.items():
        entries = []
        for r in members:
            ind = r.get("indicators") or {}
            rets = ind.get("returns") or {}
            entries.append({
                "fund_code": r["fund_code"],
                "share_code": r["share_code"],
                "fund_name": r["fund_name"],
                "ret_12m": (rets.get("ret_12m") or {}).get("value"),
                "ret_12m_status": (rets.get("ret_12m") or {}).get("status"),
                "max_drawdown": ((ind.get("risk") or {}).get("max_drawdown") or {}).get("value"),
                "mdd_status": ((ind.get("risk") or {}).get("max_drawdown") or {}).get("status"),
            })
        out[key] = {
            "member_count": len(members),
            "members": entries,
            "ranking_generated": False,
            "note": ("同类描述性对照，**不排名、不推荐**；"
                     "不同 peer_group 之间不可横向比较"),
        }
    return {
        "groups": out,
        "group_count": len(out),
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
    merged = merge_by_fund(reports)
    peers = peer_analysis(reports)

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
